"""Turn the three exports into one weekly task plan per client advisor.

Pipeline:
    1. Every source row is tested against the enabled targeting rules; a hit
       becomes a reason (rule, plain-English detail, priority score).
    2. Reasons for the same customer are merged into one task — Infobahn and
       Mastermind by VIN, VinSolutions leads by name (only when the name is
       unambiguous). A customer flagged by several rules ranks higher.
    3. Each task gets an owner from the roster: VinSolutions sales rep first,
       then Infobahn client advisor, then Mastermind assignee (or original
       salesperson). Anyone else's customers are 'unowned'.
    4. Customers marked Sold / Not Interested in Mastermind, and customers
       already tasked within the cooldown window, are left out.
    5. Advisors get their own customers by priority up to their weekly
       capacity; leftover capacity is filled from the unowned pool, spread
       evenly. Each advisor's list is then split across the work days,
       most urgent first.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from .models import FSAccount, Lead, MastermindRecord, Task
from .settings import RULE_LABELS, normalize_settings

RULE_ACTIONS = {
    "showroom": "Follow up on the visit/inquiry and set an appointment",
    "lease_maturity": "Lease-end call: pull-ahead / new lease, book an appraisal",
    "retail_payoff": "Equity call: show upgrade numbers on a new vehicle",
    "mastermind": "Present the Mastermind upgrade proposal",
    "warranty": "Warranty is ending: upgrade or extended coverage",
}


def money(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def fmt_date(value: date | None) -> str:
    return value.strftime("%m/%d/%Y") if value else "—"


def _tokens(name: str) -> list[str]:
    return re.sub(r"[^a-z ]", " ", name.lower()).split()


def name_key(name: str) -> str:
    tokens = _tokens(name)
    if len(tokens) >= 2:
        return f"{tokens[0]} {tokens[-1]}"
    return " ".join(tokens)


def week_start_for(today: date) -> date:
    """Plans cover Monday–Sunday; on a Monday plan the current week, else next."""
    return today + timedelta(days=(7 - today.weekday()) % 7)


class Roster:
    """Resolve the many spellings of an advisor's name to one roster entry."""

    def __init__(self, advisors: list[dict]):
        self.active = [a["name"] for a in advisors if a["active"]]
        self._lookup: dict[str, str] = {}
        for a in advisors:
            for spelling in [a["name"], *a["aliases"]]:
                full = " ".join(_tokens(spelling))
                self._lookup[full] = a["name"]
                self._lookup.setdefault(name_key(spelling), a["name"])
        self._active = set(self.active)

    def resolve(self, raw: str) -> str:
        """Roster name for an active advisor, or '' (unknown, departed, inactive)."""
        tokens = " ".join(_tokens(raw or ""))
        name = self._lookup.get(tokens) or self._lookup.get(name_key(raw or ""))
        return name if name in self._active else ""


# ---------------------------------------------------------------------------
# Rules — each returns a reason dict or None
# ---------------------------------------------------------------------------

def _reason(rule: str, detail: str, score: float, source: str) -> dict:
    return {"rule": rule, "label": RULE_LABELS[rule], "detail": detail,
            "score": round(score, 1), "source": source}


def _match_any(value: str, options: list[str]) -> bool:
    v = value.lower().replace(" ", "").replace("-", "")
    return any(v == o.lower().replace(" ", "").replace("-", "") for o in options)


def rule_showroom(lead: Lead, cfg: dict, as_of: date) -> dict | None:
    if not cfg["enabled"] or lead.created is None:
        return None
    if cfg["statuses"] and not _match_any(lead.status, cfg["statuses"]):
        return None
    if cfg["lead_types"] and not _match_any(lead.lead_type, cfg["lead_types"]):
        return None
    if any(x.lower() in lead.source.lower() for x in cfg["exclude_sources"]):
        return None
    age = (as_of - lead.created).days
    if age < cfg["min_days"] or age > cfg["max_days"]:
        return None
    span = max(cfg["max_days"] - cfg["min_days"], 1)
    score = cfg["weight"] + 20 * (cfg["max_days"] - age) / span
    walk_in = _match_any(lead.lead_type, ["Walk-in"])
    if walk_in:
        score += cfg["walk_in_bonus"]
    kind = "Showroom visit" if walk_in else f"{lead.lead_type} lead".strip().capitalize()
    detail = f"{kind} {fmt_date(lead.created)} ({age} days ago)"
    if lead.source and lead.source.lower() not in ("walk in", "phone up"):
        detail += f" via {lead.source}"
    if lead.vehicle:
        detail += f". Vehicle: {lead.vehicle}"
    if lead.note:
        detail += f". Note: {lead.note}"
    return _reason("showroom", detail, score, "VinSolutions")


def rule_lease_maturity(acct: FSAccount, cfg: dict, as_of: date) -> dict | None:
    if not cfg["enabled"] or not acct.is_lease or acct.maturity is None:
        return None
    days = (acct.maturity - as_of).days
    if days > cfg["days_before"] or days < -cfg["days_after"]:
        return None
    if days >= 0:
        score = cfg["weight"] + 20 * (1 - days / max(cfg["days_before"], 1))
        when = f"matures {fmt_date(acct.maturity)} (in {days} days)"
    else:
        score = cfg["weight"] + 20
        when = f"MATURED {fmt_date(acct.maturity)} ({-days} days ago)"
    parts = [f"{acct.description} lease {when}", f"{money(acct.payment)}/mo"]
    if acct.contract_miles and acct.odometer:
        parts.append(f"{acct.odometer:,.0f} of {acct.contract_miles:,.0f} contract miles "
                     f"at last service")
    if acct.equity is not None:
        parts.append(f"est. equity {money(acct.equity)}")
    return _reason("lease_maturity", "; ".join(parts), score, "Infobahn")


def _tier_number(tier: str) -> int | None:
    match = re.search(r"(\d+)", tier or "")
    return int(match.group(1)) if match else None


def rule_retail_payoff(acct: FSAccount, cfg: dict, as_of: date) -> dict | None:
    if not cfg["enabled"] or acct.is_lease or acct.maturity is None:
        return None
    days = (acct.maturity - as_of).days
    why, score = [], cfg["weight"]
    if 0 <= days <= cfg["days_before"]:
        why.append(f"final payment {fmt_date(acct.maturity)} (in {days} days)")
        score += 15 * (1 - days / max(cfg["days_before"], 1))
    if acct.in_market_tier and _match_any(acct.in_market_tier, cfg["in_market_tiers"]):
        why.append(f"BMW FS in-market {acct.in_market_tier}")
        tier = _tier_number(acct.in_market_tier) or 6
        score += max(0, 7 - tier) * 3
    if cfg["min_equity"] > 0 and (acct.equity or 0) >= cfg["min_equity"] and acct.contract_date:
        months_in = (as_of.year - acct.contract_date.year) * 12 + as_of.month - acct.contract_date.month
        if months_in >= cfg["min_months_in_contract"]:
            why.append(f"{months_in} months into contract")
            score += min(10, (acct.equity or 0) / 5000)
    if not why:
        return None
    detail = (f"{acct.description} retail: " + ", ".join(why)
              + f"; {money(acct.payment)}/mo; est. equity {money(acct.equity)}")
    return _reason("retail_payoff", detail, score, "Infobahn")


def rule_warranty_fs(acct: FSAccount, cfg: dict, as_of: date) -> dict | None:
    if not cfg["enabled"] or acct.warranty_expires is None:
        return None
    if acct.warranty_status and acct.warranty_status.lower() != "active":
        return None
    days = (acct.warranty_expires - as_of).days
    window = cfg["months_before"] * 30.5
    if days < 0 or days > window:
        return None
    score = cfg["weight"] + 15 * (1 - days / max(window, 1))
    detail = (f"{acct.description} {acct.warranty_type or ''} warranty expires "
              f"{fmt_date(acct.warranty_expires)} (in {days} days)")
    if acct.service_contract.lower() == "yes":
        detail += "; already has a service contract"
    return _reason("warranty", detail.replace("  ", " "), score, "Infobahn")


def rule_warranty_mm(rec: MastermindRecord, cfg: dict) -> dict | None:
    months = rec.warranty_months_left
    if not cfg["enabled"] or months is None or months > cfg["months_before"]:
        return None
    score = cfg["weight"] + 15 * (1 - months / max(cfg["months_before"], 1))
    return _reason("warranty", f"{rec.description} warranty ends in about {months} "
                               f"month{'s' if months != 1 else ''}", score, "Mastermind")


PAYMENT_DIFF_SANITY = 5000  # Mastermind emits garbage differences for some cash deals


def rule_mastermind(rec: MastermindRecord, cfg: dict) -> dict | None:
    if not cfg["enabled"]:
        return None
    if cfg["statuses"] and not _match_any(rec.status, cfg["statuses"]):
        return None
    if rec.sub_status and _match_any(rec.sub_status, cfg["exclude_sub_statuses"]):
        return None
    if not cfg["include_conquest"] and "conquest" in rec.assignee.lower():
        return None
    if rec.months_owned is not None and rec.months_owned < cfg["min_months_owned"]:
        return None
    diff = rec.payment_difference
    if diff is not None and abs(diff) > PAYMENT_DIFF_SANITY:
        diff = None
    hot = bool(rec.sub_status) and _match_any(rec.sub_status, cfg["always_include_sub_statuses"])
    close_payment = diff is not None and diff <= cfg["max_payment_difference"]
    if not (hot or close_payment):
        return None

    score = cfg["weight"]
    if close_payment:
        score += 10 * (1 - max(diff, 0) / max(cfg["max_payment_difference"], 1))
        if diff <= 0:
            score += 5
    if _match_any(rec.sub_status, ["ReadyNow"]):
        score += 20
    elif _match_any(rec.sub_status, ["ReadySoon"]):
        score += 10
    if rec.household_demand:
        score += 5
    if rec.lease_mileage_status.lower() == "exceeded":
        score += 5

    current = f"{rec.description} ({rec.deal_type.lower() or 'owned'}"
    current += f", {money(rec.payment)}/mo)" if rec.payment else ")"
    detail = f"Owns {current}"
    if rec.new_vehicle:
        detail += f". Proposal: {rec.new_vehicle}"
        if rec.new_payment:
            detail += f" at {money(rec.new_payment)}/mo"
        if diff is not None:
            detail += f" ({'+' if diff >= 0 else '-'}{money(abs(diff))}/mo)"
    if rec.trade_equity is not None and abs(rec.trade_equity) < 500000:
        detail += f". Trade equity {money(rec.trade_equity)}"
    extras = []
    if rec.sub_status and rec.sub_status.lower() != "unknown":
        extras.append(f"status {rec.status}/{rec.sub_status}")
    if rec.household_demand:
        extras.append("household demand")
    if rec.lease_mileage_status.lower() == "exceeded":
        extras.append("over lease miles")
    if extras:
        text = ", ".join(extras)
        detail += ". " + text[0].upper() + text[1:]
    return _reason("mastermind", detail, score, "Mastermind")


# ---------------------------------------------------------------------------
# Plan building
# ---------------------------------------------------------------------------

class _Merger:
    """Merge reasons for the same customer into one Task."""

    def __init__(self, roster: Roster):
        self.roster = roster
        self.tasks: dict[str, Task] = {}
        self.by_vin: dict[str, str] = {}
        self.by_name: dict[str, set[str]] = defaultdict(set)
        self.unmatched_owners: Counter = Counter()

    def _find(self, vin: str, name: str, phones: list[str], email: str) -> Task | None:
        if vin and vin in self.by_vin:
            return self.tasks[self.by_vin[vin]]
        candidates = [self.tasks[k] for k in self.by_name.get(name_key(name), ())]
        if len(candidates) != 1:
            return None  # unknown or ambiguous name — don't guess
        task = candidates[0]
        # Same name: merge when contact details agree, or one side has none.
        if not (phones or email) or not (task.phones or task.email):
            return task
        if set(phones) & set(task.phones) or (email and email.lower() == task.email.lower()):
            return task
        return None

    def add(self, reason: dict, *, customer: str, vin: str = "", phones=(), email: str = "",
            email_ok: bool = True, vehicle: str = "", owner_raw: str = "",
            owner_basis: str = "", fallback_owner_raw: str = "") -> None:
        phones = list(phones)
        task = self._find(vin, customer, phones, email)
        if task is None:
            key = f"vin:{vin}" if vin else f"name:{name_key(customer)}"
            while key in self.tasks:
                key += "+"
            task = Task(key=key, customer=customer)
            self.tasks[key] = task
            self.by_name[name_key(customer)].add(key)
        if vin:
            self.by_vin.setdefault(vin, task.key)

        task.reasons.append(reason)
        task.phones = list(dict.fromkeys(task.phones + phones))
        task.email = task.email or email
        task.do_not_email = task.do_not_email or not email_ok
        task.vehicle = task.vehicle or vehicle

        if not task.owner:
            owner = self.roster.resolve(owner_raw)
            basis = owner_basis
            if not owner and fallback_owner_raw:
                owner = self.roster.resolve(fallback_owner_raw)
                basis = "Mastermind original salesperson"
            if owner:
                task.owner, task.owner_basis, task.previous_owner = owner, basis, ""
            elif owner_raw and not task.previous_owner:
                task.previous_owner = owner_raw
                self.unmatched_owners[owner_raw] += 1


def build_plan(leads: list[Lead], accounts: list[FSAccount], records: list[MastermindRecord],
               settings: dict, week_start: date,
               history: dict[str, str] | None = None) -> dict:
    s = normalize_settings(settings)
    rules = s["rules"]
    roster = Roster(s["advisors"])
    merger = _Merger(roster)
    history = history or {}

    excluded_status = s["exclude_mastermind_statuses"]
    closed_vins = {r.vin for r in records if r.vin and _match_any(r.status, excluded_status)}
    closed_names = {name_key(r.customer) for r in records if _match_any(r.status, excluded_status)}
    suppressed = Counter()

    def closed(name: str, vin: str = "") -> bool:
        return (vin and vin in closed_vins) or name_key(name) in closed_names

    # VinSolutions first: the rep the customer is actively working with wins ownership.
    for lead in leads:
        reason = rule_showroom(lead, rules["showroom"], week_start)
        if not reason:
            continue
        if closed(lead.customer):
            suppressed["sold_or_not_interested"] += 1
            continue
        merger.add(reason, customer=lead.customer,
                   phones=[lead.phone] if lead.phone else [], email=lead.email,
                   owner_raw=lead.rep, owner_basis="VinSolutions sales rep")

    for acct in accounts:
        found = [r for r in (rule_lease_maturity(acct, rules["lease_maturity"], week_start),
                             rule_retail_payoff(acct, rules["retail_payoff"], week_start),
                             rule_warranty_fs(acct, rules["warranty"], week_start)) if r]
        if not found:
            continue
        if closed(acct.customer, acct.vin):
            suppressed["sold_or_not_interested"] += 1
            continue
        for reason in found:
            merger.add(reason, customer=acct.customer, vin=acct.vin, phones=acct.phones,
                       email=acct.email, vehicle=acct.description, owner_raw=acct.advisor,
                       owner_basis="Infobahn client advisor")

    use_original = s["unowned"]["use_original_salesperson"]
    for rec in records:
        if _match_any(rec.status, excluded_status):
            continue
        found = [r for r in (rule_mastermind(rec, rules["mastermind"]),
                             rule_warranty_mm(rec, rules["warranty"])) if r]
        for reason in found:
            merger.add(reason, customer=rec.customer, vin=rec.vin, phones=rec.phones,
                       email=rec.email, email_ok=rec.email_ok, vehicle=rec.description,
                       owner_raw=rec.assignee, owner_basis="Mastermind assignee",
                       fallback_owner_raw=rec.original_salesperson if use_original else "")

    # Collapse duplicate rule hits (e.g. warranty from both Infobahn and Mastermind).
    tasks = []
    for task in merger.tasks.values():
        best: dict[str, dict] = {}
        for r in task.reasons:
            if r["rule"] not in best or r["score"] > best[r["rule"]]["score"]:
                best[r["rule"]] = r
        task.reasons = sorted(best.values(), key=lambda r: -r["score"])
        task.score = round(task.reasons[0]["score"] + 5 * (len(task.reasons) - 1), 1)
        tasks.append(task)

    # Cooldown: skip customers tasked recently, unless they've since come back in.
    fresh = []
    for task in tasks:
        last = history.get(task.key)
        if last:
            new_lead = any(r["rule"] == "showroom" for r in task.reasons) and any(
                lead.created and lead.created >= date.fromisoformat(last)
                and name_key(lead.customer) == name_key(task.customer) for lead in leads)
            if not new_lead:
                suppressed["cooldown"] += 1
                continue
        fresh.append(task)
    fresh.sort(key=lambda t: (-t.score, t.customer))

    # Assign. Pass 1 honours each rule's per-advisor limit so every plan gets
    # a mix of work; pass 2 backfills any spare capacity strictly by priority.
    # In each pass the advisor's own customers go first, then the unowned pool.
    capacity = {a["name"]: (a["capacity"] if a["capacity"] is not None
                            else s["default_weekly_capacity"])
                for a in s["advisors"] if a["active"]}
    assigned: dict[str, list[Task]] = {name: [] for name in capacity}
    per_rule: dict[str, Counter] = {name: Counter() for name in capacity}
    taken = Counter()
    unowned_limit = s["unowned"]["max_per_advisor"] or float("inf")
    if not s["unowned"]["distribute"]:
        unowned_limit = 0
    pool = [t for t in fresh if t.owner not in assigned]

    def fits(name: str, task: Task, enforce_mix: bool) -> bool:
        if len(assigned[name]) >= capacity[name]:
            return False
        rule = task.primary["rule"]
        limit = rules[rule]["max_per_advisor"]
        return not (enforce_mix and limit and per_rule[name][rule] >= limit)

    def give(name: str, task: Task, reassigned: bool) -> None:
        task.advisor, task.reassigned = name, reassigned
        assigned[name].append(task)
        per_rule[name][task.primary["rule"]] += 1
        taken[name] += reassigned

    for enforce_mix in (True, False):
        for task in fresh:
            if task.owner in assigned and not task.advisor and fits(task.owner, task, enforce_mix):
                give(task.owner, task, False)
        for task in pool:
            if task.advisor:
                continue
            open_advisors = [n for n in assigned
                             if taken[n] < unowned_limit and fits(n, task, enforce_mix)]
            if open_advisors:
                pick = max(open_advisors,
                           key=lambda n: (capacity[n] - len(assigned[n]), -taken[n], n))
                give(pick, task, True)

    days = s["work_days"]
    for name, items in assigned.items():
        items.sort(key=lambda t: (-t.score, t.customer))
        per_day, extra = divmod(len(items), len(days))
        i = 0
        for d, day in enumerate(days):
            for _ in range(per_day + (1 if d < extra else 0)):
                items[i].day = day
                i += 1

    qualified = Counter(r["rule"] for t in fresh for r in t.reasons)
    scheduled = [t for t in fresh if t.advisor]
    advisors_out = []
    for name in assigned:
        items = assigned[name]
        own_left = sum(1 for t in fresh if t.owner == name and not t.advisor)
        advisors_out.append({
            "name": name,
            "capacity": capacity[name],
            "tasks": len(items),
            "own": sum(1 for t in items if not t.reassigned),
            "reassigned": sum(1 for t in items if t.reassigned),
            "own_not_scheduled": own_left,
            "by_rule": dict(Counter(t.primary["rule"] for t in items)),
        })

    return {
        "week_start": week_start.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dealership": s["dealership"],
        "work_days": days,
        "advisors": advisors_out,
        "tasks": [t.to_dict() for t in fresh],
        "stats": {
            "inputs": {"leads": len(leads), "infobahn": len(accounts),
                       "mastermind": len(records)},
            "qualified_customers": len(fresh),
            "qualified_by_rule": dict(qualified),
            "scheduled": len(scheduled),
            "unowned_pool": len(pool),
            "unowned_not_scheduled": sum(1 for t in pool if not t.advisor),
            "suppressed": dict(suppressed),
            "unmatched_owners": dict(merger.unmatched_owners.most_common(25)),
        },
    }
