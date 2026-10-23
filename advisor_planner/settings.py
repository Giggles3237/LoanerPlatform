"""Planner settings: the advisor roster and the targeting rules.

Everything an admin can change lives in one JSON document. DEFAULT_SETTINGS
is the starting point; saved settings are deep-merged over it so rules added
in later versions pick up their defaults automatically.

Storage: $PLANNER_DATA_DIR (default ./data/planner) holds settings.json, the
saved weekly plans, and the most recent uploads (for re-generating after a
rule change without uploading again).
"""

from __future__ import annotations

import copy
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

DEFAULT_SETTINGS: dict = {
    "dealership": "BMW of Pittsburgh",
    "work_days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    "default_weekly_capacity": 50,
    "cooldown_weeks": 2,
    "unowned": {
        "distribute": True,
        "max_per_advisor": 0,
        "use_original_salesperson": True,
    },
    "exclude_mastermind_statuses": ["Sold", "NotInterested"],
    "advisors": [
        {"name": "Gregg Lewis", "aliases": [], "active": True, "capacity": None},
        {"name": "Greg Riley", "aliases": ["Gregory Riley"], "active": True, "capacity": None},
        {"name": "River Riffey", "aliases": [], "active": True, "capacity": None},
        {"name": "Ed Mathieu", "aliases": ["Edward Mathieu", "Edward J Mathieu"],
         "active": True, "capacity": None},
        {"name": "Morgan McLane", "aliases": [], "active": True, "capacity": None},
        {"name": "Mary Limbacher", "aliases": [], "active": True, "capacity": None},
        {"name": "Abdullah Alkhaleel", "aliases": [], "active": True, "capacity": None},
        {"name": "Aleah Cimino", "aliases": [], "active": True, "capacity": None},
    ],
    "rules": {
        "showroom": {
            "enabled": True,
            "max_per_advisor": 30,
            "weight": 100,
            "min_days": 1,
            "max_days": 60,
            "lead_types": ["Walk-in", "Phone", "Internet"],
            "statuses": ["Active"],
            "exclude_sources": [],
            "walk_in_bonus": 15,
        },
        "lease_maturity": {
            "enabled": True,
            "max_per_advisor": 15,
            "weight": 90,
            "days_before": 180,
            "days_after": 45,
            "owner": "Ed Mathieu",
            "originator_keeps": True,
        },
        "retail_payoff": {
            "enabled": True,
            "max_per_advisor": 10,
            "weight": 70,
            "days_before": 120,
            "in_market_tiers": ["Tier 1", "Tier 2", "Tier 3"],
            "min_equity": 15000,
            "min_months_in_contract": 30,
        },
        "mastermind": {
            "enabled": True,
            "max_per_advisor": 15,
            "weight": 60,
            "statuses": ["NotContacted", "Attempted", "Presented"],
            "exclude_sub_statuses": ["NotReady", "Lost", "CreditNotApproved", "OnOrder"],
            "max_payment_difference": 100,
            "always_include_sub_statuses": ["ReadyNow", "ReadySoon"],
            "include_conquest": True,
            "min_months_owned": 12,
        },
        "warranty": {
            "enabled": True,
            "max_per_advisor": 5,
            "weight": 45,
            "months_before": 3,
        },
    },
}

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# The admin form is generated from this spec:
# (rule key, title, explanation, [(setting, label, kind)])
# kinds: bool, int, money, list (comma-separated)
RULE_SPECS = [
    ("showroom", "Showroom & lead follow-up", "VinSolutions",
     "Customers who visited, called or sent a lead in the last few weeks. Days are counted "
     "back from the start of the plan week.",
     [("enabled", "Include", "bool"),
      ("weight", "Priority weight", "int"),
      ("max_per_advisor", "Max per advisor per week (0 = no limit)", "int"),
      ("min_days", "Lead at least this many days old", "int"),
      ("max_days", "…and no older than (days)", "int"),
      ("lead_types", "Lead types", "list"),
      ("statuses", "Lead statuses", "list"),
      ("exclude_sources", "Skip lead sources containing", "list"),
      ("walk_in_bonus", "Extra priority for walk-ins", "int")]),
    ("lease_maturity", "Lease maturity", "Infobahn",
     "BMW FS leases maturing soon, or recently matured and not yet turned in. They go to the "
     "lease owner unless the salesperson who originated the lease (Mastermind original "
     "salesperson, else Infobahn client advisor) is an active advisor. This outranks every "
     "other ownership source, and the lease owner isn't held to the per-advisor limit.",
     [("enabled", "Include", "bool"),
      ("weight", "Priority weight", "int"),
      ("max_per_advisor", "Max per advisor per week (0 = no limit)", "int"),
      ("days_before", "Maturing within (days)", "int"),
      ("days_after", "…or matured up to (days ago)", "int"),
      ("owner", "Lease owner (roster name)", "text"),
      ("originator_keeps", "Originating salesperson keeps their leases", "bool")]),
    ("retail_payoff", "Retail payoff & equity", "Infobahn",
     "BMW FS retail contracts near payoff, flagged in-market by BMW FS, or with strong "
     "equity well into the term. Any one condition qualifies.",
     [("enabled", "Include", "bool"),
      ("weight", "Priority weight", "int"),
      ("max_per_advisor", "Max per advisor per week (0 = no limit)", "int"),
      ("days_before", "Contract ends within (days)", "int"),
      ("in_market_tiers", "In-market tiers", "list"),
      ("min_equity", "Est. equity at least ($, 0 = off)", "money"),
      ("min_months_in_contract", "…and at least (months into contract)", "int")]),
    ("mastermind", "Mastermind upgrade", "Mastermind",
     "Equity-mining matches: customers whose proposed new-vehicle payment is close to "
     "what they pay today.",
     [("enabled", "Include", "bool"),
      ("weight", "Priority weight", "int"),
      ("max_per_advisor", "Max per advisor per week (0 = no limit)", "int"),
      ("statuses", "Sales statuses", "list"),
      ("exclude_sub_statuses", "Skip sub-statuses", "list"),
      ("max_payment_difference", "Payment increase at most ($/mo)", "money"),
      ("always_include_sub_statuses", "Always include sub-statuses", "list"),
      ("include_conquest", "Include Conquest Mastermind (non-owners)", "bool"),
      ("min_months_owned", "Owned at least (months)", "int")]),
    ("warranty", "Warranty expiring", "Infobahn + Mastermind",
     "Factory or CPO warranty running out — a natural reason to talk upgrade or "
     "extended coverage.",
     [("enabled", "Include", "bool"),
      ("weight", "Priority weight", "int"),
      ("max_per_advisor", "Max per advisor per week (0 = no limit)", "int"),
      ("months_before", "Expires within (months)", "int")]),
]

RULE_LABELS = {key: title for key, title, *_ in RULE_SPECS}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def normalize_settings(data: dict) -> dict:
    """Merge over defaults and coerce types so the planner can trust the dict."""
    s = _merge(DEFAULT_SETTINGS, data)
    s["work_days"] = [d for d in WEEKDAYS if d in s["work_days"]] or ["Mon"]
    s["default_weekly_capacity"] = max(0, int(s["default_weekly_capacity"]))
    s["cooldown_weeks"] = max(0, int(s["cooldown_weeks"]))
    s["unowned"]["max_per_advisor"] = max(0, int(s["unowned"]["max_per_advisor"]))
    advisors, seen = [], set()
    for a in s["advisors"]:
        name = re.sub(r"\s+", " ", str(a.get("name", ""))).strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        cap = a.get("capacity")
        advisors.append({
            "name": name,
            "aliases": [x.strip() for x in a.get("aliases", []) if str(x).strip()],
            "active": bool(a.get("active", True)),
            "capacity": int(cap) if cap not in (None, "") else None,
        })
    s["advisors"] = advisors
    for key, _title, _src, _desc, fields in RULE_SPECS:
        rule = s["rules"][key]
        for name, _label, kind in fields:
            if kind == "bool":
                rule[name] = bool(rule[name])
            elif kind == "int":
                rule[name] = int(rule[name])
            elif kind == "money":
                rule[name] = float(rule[name])
            elif kind == "list":
                rule[name] = [str(x).strip() for x in rule[name] if str(x).strip()]
            elif kind == "text":
                rule[name] = str(rule[name] or "").strip()
    return s


def data_dir() -> Path:
    return Path(os.environ.get("PLANNER_DATA_DIR", "data/planner"))


class SettingsStore:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else data_dir() / "settings.json"

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> dict:
        if not self.exists():
            return normalize_settings({})
        with open(self.path, encoding="utf-8") as fh:
            return normalize_settings(json.load(fh))

    def save(self, settings: dict) -> None:
        settings = normalize_settings(settings)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def last_updated(self) -> date | None:
        if self.exists():
            return datetime.fromtimestamp(self.path.stat().st_mtime).date()
        return None


class PlanStore:
    """Saved weekly plans (one JSON per plan week) — also the cooldown history."""

    def __init__(self, base: str | os.PathLike | None = None):
        self.dir = Path(base) if base else data_dir() / "plans"

    def save(self, plan: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{plan['week_start']}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(plan), encoding="utf-8")
        tmp.replace(path)

    def load(self, week: str) -> dict | None:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", week):
            return None
        path = self.dir / f"{week}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def weeks(self) -> list[str]:
        if not self.dir.is_dir():
            return []
        return sorted((p.stem for p in self.dir.glob("*.json")), reverse=True)

    def latest(self) -> dict | None:
        weeks = self.weeks()
        return self.load(weeks[0]) if weeks else None

    def recent_keys(self, week_start: date, weeks_back: int) -> dict[str, str]:
        """{customer key: most recent earlier plan week} within the cooldown window."""
        out: dict[str, str] = {}
        if weeks_back <= 0:
            return out
        for week in self.weeks():
            start = date.fromisoformat(week)
            age_days = (week_start - start).days
            if age_days <= 0 or age_days > weeks_back * 7:
                continue
            plan = self.load(week)
            for task in plan.get("tasks", []):
                if task.get("advisor"):
                    out.setdefault(task["key"], week)
        return out


class UploadStore:
    """Keep the last uploaded files so admins can re-run after changing rules."""

    NAMES = ("vinsolutions", "infobahn", "mastermind")

    def __init__(self, base: str | os.PathLike | None = None):
        self.dir = Path(base) if base else data_dir() / "uploads"

    def path(self, name: str) -> Path | None:
        matches = sorted(self.dir.glob(f"{name}.*")) if self.dir.is_dir() else []
        return matches[0] if matches else None

    def complete(self) -> bool:
        return all(self.path(n) for n in self.NAMES)

    def save(self, name: str, source: Path) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        for old in self.dir.glob(f"{name}.*"):
            old.unlink()
        (self.dir / f"{name}{source.suffix.lower()}").write_bytes(source.read_bytes())
