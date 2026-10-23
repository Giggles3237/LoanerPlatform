"""Advisor Task Planner web app — weekly task plans for client advisors.

Team flow (any user with APP_PASSWORD):
    upload the VinSolutions, Infobahn and Mastermind exports -> a saved plan
    for the week: overview, printable plan per advisor, Excel download.

Admin flow (ADMIN_PASSWORD):
    /admin — the advisor roster (names, aliases, capacity, active) and every
    targeting rule; settings backup/restore.

Environment variables:
    APP_PASSWORD      password for the whole site (required when hosted — the
                      plans contain customer contact details)
    ADMIN_PASSWORD    password for /admin (required when hosted)
    SECRET_KEY        session signing key (optional)
    PLANNER_DATA_DIR  where settings, plans and the last uploads live
                      (point at a persistent disk; default ./data/planner)
    TIMEZONE          dealership timezone (default America/New_York)
    PORT              dev-server port (default 5001)
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import secrets
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (Flask, Response, abort, redirect, render_template_string, request,
                   send_file, session, url_for)

from .export import assignment_note, plan_workbook, tasks_for
from .parsers import parse_infobahn, parse_mastermind, parse_vinsolutions
from .planner import RULE_ACTIONS, build_plan, week_start_for
from .settings import (RULE_LABELS, RULE_SPECS, WEEKDAYS, PlanStore, SettingsStore,
                       UploadStore, data_dir, normalize_settings)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024


def _secret_key() -> str:
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    seed = os.environ.get("ADMIN_PASSWORD", "") + os.environ.get("APP_PASSWORD", "")
    if seed:
        return hashlib.sha256(b"advisorplanner:" + seed.encode()).hexdigest()
    return secrets.token_hex(32)


app.secret_key = _secret_key()

store = SettingsStore()
plans = PlanStore()
uploads = UploadStore()

DAY_NAMES = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday",
             "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday"}


def _local_time(iso_utc: str) -> str:
    tz = ZoneInfo(os.environ.get("TIMEZONE", "America/New_York"))
    dt = datetime.fromisoformat(iso_utc).astimezone(tz)
    return dt.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")


def _today() -> date:
    return datetime.now(ZoneInfo(os.environ.get("TIMEZONE", "America/New_York"))).date()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    return "ok"


@app.before_request
def _require_password():
    if request.path == "/healthz":
        return None
    password = os.environ.get("APP_PASSWORD")
    if not password:
        return None
    auth = request.authorization
    if auth and auth.password and hmac.compare_digest(auth.password, password):
        return None
    return Response("Password required.", 401,
                    {"WWW-Authenticate": 'Basic realm="Advisor Task Planner"'})


def is_admin() -> bool:
    if not os.environ.get("ADMIN_PASSWORD"):
        return True
    return bool(session.get("is_admin"))


def storage_warning() -> str | None:
    hosted = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RENDER")
                  or os.environ.get("APP_PASSWORD"))
    if hosted and not os.environ.get("PLANNER_DATA_DIR"):
        return ("Storage is not persistent: PLANNER_DATA_DIR is not set, so plans, settings "
                "and the cooldown history are lost on every deploy or restart. Attach a "
                "volume (mount path /data) and set PLANNER_DATA_DIR=/data/planner.")
    return None


# ---------------------------------------------------------------------------
# Page chrome
# ---------------------------------------------------------------------------

STYLE = """
  body { font-family: Arial, Helvetica, sans-serif; background:#f3f4f6; margin:0; color:#262626; }
  .wrap { max-width:{width}px; margin:32px auto; background:#fff; border-radius:10px;
          box-shadow:0 2px 10px rgba(0,0,0,.08); padding:32px; }
  h1 { font-size:22px; margin:0 0 4px; }
  h1 span { color:#1c69d4; }
  h2 { font-size:16px; margin:28px 0 10px; border-bottom:2px solid #e5e7eb; padding-bottom:6px; }
  h2 small { font-weight:normal; color:#6b7280; font-size:13px; }
  h3 { font-size:14px; margin:18px 0 4px; }
  p.sub { color:#6b7280; margin:0 0 20px; font-size:14px; }
  label { display:block; font-weight:bold; font-size:13px; margin:14px 0 6px; }
  small, .muted { color:#6b7280; font-weight:normal; }
  input[type=file] { width:100%; padding:10px; border:2px dashed #d1d5db; border-radius:8px;
                     background:#fafafa; font-size:13px; box-sizing:border-box; }
  input[type=text], input[type=number], input[type=password], input[type=date] {
      padding:7px 9px; border:1px solid #d1d5db; border-radius:6px; font-size:13px;
      box-sizing:border-box; }
  button, .btn { background:#1c69d4; color:#fff; border:0; padding:11px 22px; font-size:14px;
           border-radius:8px; cursor:pointer; font-weight:bold; text-decoration:none;
           display:inline-block; }
  button:hover, .btn:hover { background:#155ab6; }
  .btn2 { background:#e5e7eb; color:#262626; }
  .btn2:hover { background:#d1d5db; }
  .btn-sm { padding:6px 12px; font-size:12px; }
  .err { background:#fef2f2; color:#991b1b; padding:12px 16px; border-radius:8px; font-size:14px; margin:0 0 16px; }
  .okmsg { background:#f0fdf4; color:#166534; padding:12px 16px; border-radius:8px; font-size:14px; margin:0 0 16px; }
  .warn { background:#fffbeb; color:#92400e; padding:12px 16px; border-radius:8px; font-size:13px; margin:0 0 16px; }
  .info { background:#eef4fc; padding:12px 16px; border-radius:8px; font-size:13px; margin:0 0 16px; }
  table.grid { border-collapse:collapse; width:100%; font-size:13px; }
  table.grid th { background:#262626; color:#fff; padding:7px 9px; text-align:left; font-size:11px;
                  text-transform:uppercase; letter-spacing:.05em; }
  table.grid td { padding:6px 8px; border-bottom:1px solid #e5e7eb; }
  table.grid td.n { text-align:right; font-variant-numeric:tabular-nums; }
  table.grid input[type=text], table.grid input[type=number] { width:100%; }
  .cfg { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:6px 18px; }
  .cfg label { margin:8px 0 4px; }
  .cfg input[type=text], .cfg input[type=number] { width:100%; }
  .topbar { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap; }
  .row { display:flex; gap:12px; align-items:center; margin-top:20px; flex-wrap:wrap; }
  .cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px; margin:18px 0 4px; }
  .card { background:#f9fafb; border:1px solid #e5e7eb; border-radius:8px; padding:10px 12px; }
  .card b { display:block; font-size:22px; }
  .card span { font-size:12px; color:#6b7280; }
  .rule { border:1px solid #e5e7eb; border-radius:8px; padding:4px 16px 14px; margin:12px 0; }
  .rule p { font-size:12px; color:#6b7280; margin:2px 0 4px; }
  .tag { display:inline-block; font-size:10px; font-weight:bold; text-transform:uppercase;
         letter-spacing:.04em; padding:2px 6px; border-radius:4px; margin-right:4px;
         background:#e5e7eb; color:#262626; white-space:nowrap; }
  .r-showroom { background:#dbeafe; color:#1e40af; }
  .r-lease_maturity { background:#fef3c7; color:#92400e; }
  .r-retail_payoff { background:#dcfce7; color:#166534; }
  .r-mastermind { background:#ede9fe; color:#5b21b6; }
  .r-warranty { background:#fee2e2; color:#991b1b; }
"""

PLAN_STYLE = """
  .advisor { background:#fff; max-width:1100px; margin:0 auto 24px; padding:28px 32px;
             border-radius:10px; box-shadow:0 2px 10px rgba(0,0,0,.08); }
  .plan-head { display:flex; justify-content:space-between; align-items:flex-end; gap:12px;
               flex-wrap:wrap; border-bottom:3px solid #1c69d4; padding-bottom:10px; }
  .plan-head h1 { font-size:24px; }
  .plan-head .sub { margin:0; }
  table.tasks { border-collapse:collapse; width:100%; font-size:12.5px; }
  table.tasks th { text-align:left; font-size:10px; text-transform:uppercase; letter-spacing:.05em;
                   color:#6b7280; border-bottom:2px solid #262626; padding:4px 6px; }
  table.tasks td { border-bottom:1px solid #e5e7eb; padding:7px 6px; vertical-align:top; }
  table.tasks tr { page-break-inside:avoid; }
  td.c { width:22px; text-align:center; }
  .box { display:inline-block; width:14px; height:14px; border:1.5px solid #262626; border-radius:3px; }
  td.cust { width:200px; }
  .contact { color:#374151; margin-top:2px; line-height:1.45; }
  .veh { color:#6b7280; font-size:11.5px; margin-top:2px; }
  .dne { color:#991b1b; font-weight:bold; font-size:11px; }
  .reason { margin-bottom:3px; line-height:1.4; }
  .re { color:#6b7280; font-size:11px; font-style:italic; margin-top:3px; }
  td.act { width:170px; color:#374151; }
  td.out { width:150px; border-left:1px dashed #d1d5db; }
  .toolbar { max-width:1100px; margin:0 auto 14px; display:flex; gap:10px; justify-content:flex-end; }
  @media print {
    body { background:#fff; }
    .toolbar { display:none; }
    .advisor { box-shadow:none; border-radius:0; margin:0; padding:0; max-width:none;
               page-break-after:always; }
    @page { size: landscape; margin: 12mm; }
  }
"""


def page(title: str, body: str, width: int = 980) -> str:
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{title}</title><style>{STYLE.replace('{width}', str(width))}</style>"
            f"</head><body><div class='wrap'>{body}</div></body></html>")


def week_label(week: str) -> str:
    return date.fromisoformat(week).strftime("%B %d, %Y").replace(" 0", " ")


# ---------------------------------------------------------------------------
# Upload & generate
# ---------------------------------------------------------------------------

UPLOAD_BODY = """
  <div class="topbar">
    <div>
      <h1>Advisor <span>task plans</span></h1>
      <p class="sub">Upload this week's three exports to build every client advisor's plan.</p>
    </div>
    <div>
      {% if latest %}<a class="btn btn2" href="{{ url_for('plan_overview', week=latest) }}">&larr; Latest plan</a>{% endif %}
      <a class="btn btn2" href="{{ url_for('admin') }}">&#9881; Admin</a>
    </div>
  </div>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  {% if storage_warning %}<div class="err">&#9888; {{ storage_warning }}</div>{% endif %}
  <div class="info">
    <b>{{ active }} active advisors</b> &bull; {{ capacity }} tasks each by default &bull;
    targeting rules last changed <b>{{ updated or 'never (defaults)' }}</b>
  </div>
  <form method="post" action="{{ url_for('generate') }}" enctype="multipart/form-data">
    <label>VinSolutions lead report <small>(.xlsx — last 60 days of visits, phone-ups and internet leads by sales rep)</small></label>
    <input type="file" name="vinsolutions" accept=".xlsx,.xls,.csv" required>
    <label>Infobahn export <small>(.xls — BMW Financial Services portfolio)</small></label>
    <input type="file" name="infobahn" accept=".xls,.xlsx,.csv,.html" required>
    <label>Mastermind export <small>(.xlsx — equity mining)</small></label>
    <input type="file" name="mastermind" accept=".xlsx,.xls,.csv" required>
    <label>Plan week starting</label>
    <input type="date" name="week_start" value="{{ week_start }}">
    <div class="row"><button type="submit">Build weekly plans</button></div>
  </form>
  {% if can_regenerate %}
  <h2>Re-run without uploading</h2>
  <form method="post" action="{{ url_for('regenerate') }}" class="row" style="margin-top:0;">
    <span class="muted" style="font-size:13px;">Rebuild from the files uploaded {{ uploaded_at }} using the current settings — handy after changing targeting rules.</span>
    <input type="date" name="week_start" value="{{ week_start }}">
    <button class="btn2" style="color:#262626;">Rebuild plans</button>
  </form>
  {% endif %}
"""


@app.route("/")
def index():
    weeks = plans.weeks()
    if weeks:
        return redirect(url_for("plan_overview", week=weeks[0]))
    return redirect(url_for("upload"))


@app.route("/upload")
def upload():
    s = store.load()
    last = uploads.path("mastermind")
    return render_template_string(
        page("Upload exports", UPLOAD_BODY, width=720),
        error=request.args.get("error"),
        storage_warning=storage_warning(),
        latest=(plans.weeks() or [None])[0],
        active=sum(a["active"] for a in s["advisors"]),
        capacity=s["default_weekly_capacity"],
        updated=store.last_updated().strftime("%m/%d/%Y") if store.last_updated() else None,
        week_start=week_start_for(_today()).isoformat(),
        can_regenerate=uploads.complete(),
        uploaded_at=(datetime.fromtimestamp(last.stat().st_mtime).strftime("%m/%d/%Y")
                     if last else ""),
    )


def _week_from_form() -> date:
    raw = request.form.get("week_start") or ""
    return date.fromisoformat(raw) if raw else week_start_for(_today())


def _build_and_save(paths: dict[str, Path], week_start: date) -> dict:
    leads = parse_vinsolutions(paths["vinsolutions"])
    accounts = parse_infobahn(paths["infobahn"])
    records = parse_mastermind(paths["mastermind"])
    settings = store.load()
    history = plans.recent_keys(week_start, settings["cooldown_weeks"])
    plan = build_plan(leads, accounts, records, settings, week_start, history)
    plans.save(plan)
    return plan


@app.route("/generate", methods=["POST"])
def generate():
    try:
        week_start = _week_from_form()
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for key in UploadStore.NAMES:
                f = request.files.get(key)
                if f is None or not f.filename:
                    return redirect(url_for("upload", error=f"Missing file: {key}"))
                dest = Path(tmp) / f"{key}{Path(f.filename).suffix.lower() or '.bin'}"
                f.save(dest)
                paths[key] = dest
            plan = _build_and_save(paths, week_start)
            for key, path in paths.items():
                uploads.save(key, path)
        return redirect(url_for("plan_overview", week=plan["week_start"]))
    except Exception as exc:
        return redirect(url_for("upload", error=f"Could not build plans — {exc}"))


@app.route("/regenerate", methods=["POST"])
def regenerate():
    if not uploads.complete():
        return redirect(url_for("upload", error="No saved uploads — upload the three files."))
    try:
        plan = _build_and_save({n: uploads.path(n) for n in UploadStore.NAMES}, _week_from_form())
        return redirect(url_for("plan_overview", week=plan["week_start"]))
    except Exception as exc:
        return redirect(url_for("upload", error=f"Could not rebuild plans — {exc}"))


# ---------------------------------------------------------------------------
# Plan views
# ---------------------------------------------------------------------------

OVERVIEW_BODY = """
  <div class="topbar">
    <div>
      <h1>Week of <span>{{ week_label }}</span></h1>
      <p class="sub">Built {{ generated }} from {{ stats.inputs.leads }} leads,
        {{ stats.inputs.infobahn }} Infobahn accounts and {{ stats.inputs.mastermind }} Mastermind customers.</p>
    </div>
    <div>
      <a class="btn" href="{{ url_for('plan_print', week=week) }}" target="_blank">&#128424; Print all plans</a>
      <a class="btn btn2" href="{{ url_for('plan_xlsx', week=week) }}">&#8681; Excel</a>
      <a class="btn btn2" href="{{ url_for('upload') }}">Upload new data</a>
      <a class="btn btn2" href="{{ url_for('admin') }}">&#9881; Admin</a>
    </div>
  </div>
  {% if stale %}<div class="warn">&#9888; Targeting rules were changed after this plan was built.
    <a href="{{ url_for('upload') }}">Rebuild</a> to apply them.</div>{% endif %}
  {% if storage_warning %}<div class="err">&#9888; {{ storage_warning }}</div>{% endif %}

  <div class="cards">
    <div class="card"><b>{{ stats.scheduled }}</b><span>tasks scheduled</span></div>
    <div class="card"><b>{{ stats.qualified_customers }}</b><span>customers matched a rule</span></div>
    <div class="card"><b>{{ reassigned }}</b><span>reassigned from unowned books</span></div>
    <div class="card"><b>{{ stats.suppressed.get('cooldown', 0) }}</b><span>skipped (worked in last {{ cooldown }} wk)</span></div>
    <div class="card"><b>{{ stats.suppressed.get('sold_or_not_interested', 0) }}</b><span>skipped (sold / not interested)</span></div>
  </div>

  <h2>Advisors</h2>
  <table class="grid">
    <tr><th>Advisor</th><th>Tasks</th>{% for r in rules %}<th>{{ labels[r] }}</th>{% endfor %}
        <th>Reassigned</th><th>Own, didn't fit</th><th></th></tr>
    {% for a in advisors %}
    <tr>
      <td><b>{{ a.name }}</b></td>
      <td class="n">{{ a.tasks }} / {{ a.capacity }}</td>
      {% for r in rules %}<td class="n">{{ a.by_rule.get(r, '') }}</td>{% endfor %}
      <td class="n">{{ a.reassigned or '' }}</td>
      <td class="n">{{ a.own_not_scheduled or '' }}</td>
      <td style="white-space:nowrap;"><a class="btn btn-sm" href="{{ url_for('plan_advisor', week=week, name=a.name) }}" target="_blank">Open plan</a></td>
    </tr>
    {% endfor %}
  </table>
  <p class="muted" style="font-size:12px;">Columns count each task's main reason. "Own, didn't fit" means
    the advisor's own customers who matched a rule but were past their weekly capacity; they stay
    eligible next week.</p>

  <h2>Matches by rule <small>(a customer can match more than one)</small></h2>
  <table class="grid" style="max-width:520px;">
    {% for r in rules %}<tr><td><span class="tag r-{{ r }}">{{ labels[r] }}</span></td>
      <td class="n">{{ stats.qualified_by_rule.get(r, 0) }}</td></tr>{% endfor %}
  </table>

  {% if stats.unmatched_owners %}
  <h2>Owners not on the roster</h2>
  <p class="muted" style="font-size:13px;margin-top:0;">Customers belonging to these names are treated as
    unowned{% if distribute %} and spread across advisors with spare capacity{% else %} and left out{% endif %}
    ({{ stats.unowned_pool }} matched; {{ stats.unowned_not_scheduled }} didn't fit this week). If a name
    is really one of your advisors spelled differently, add it as an alias in Admin.</p>
  <table class="grid" style="max-width:520px;">
    {% for name, n in stats.unmatched_owners.items() %}<tr><td>{{ name }}</td><td class="n">{{ n }}</td></tr>{% endfor %}
  </table>
  {% endif %}

  {% if other_weeks %}
  <h2>Earlier weeks</h2>
  <div class="row" style="margin-top:0;">
    {% for w in other_weeks %}<a class="btn btn2 btn-sm" href="{{ url_for('plan_overview', week=w) }}">{{ w }}</a>{% endfor %}
  </div>
  {% endif %}
"""

PLAN_BODY = """
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title><style>{{ style|safe }}</style></head>
<body style="padding:24px 12px;">
  <div class="toolbar">
    <a class="btn btn2" href="{{ url_for('plan_overview', week=week) }}">&larr; Overview</a>
    <button onclick="window.print()">&#128424; Print</button>
  </div>
  {% for adv in sections %}
  <section class="advisor">
    <div class="plan-head">
      <div>
        <h1>{{ adv.name }}</h1>
        <p class="sub">{{ dealership }} &bull; weekly task plan &bull; week of {{ week_label }} &bull;
          {{ adv.count }} tasks</p>
      </div>
      <div>{% for r, n in adv.mix %}<span class="tag r-{{ r }}">{{ labels[r] }} &middot; {{ n }}</span>{% endfor %}</div>
    </div>
    {% if not adv.days %}<p class="muted">No tasks this week.</p>{% endif %}
    {% for day, items in adv.days %}
    <h2>{{ day }} <small>&mdash; {{ items|length }} tasks</small></h2>
    <table class="tasks">
      <tr><th class="c"></th><th>Customer</th><th>Why</th><th>Do this</th><th>Outcome</th></tr>
      {% for t in items %}
      <tr>
        <td class="c"><span class="box"></span></td>
        <td class="cust"><b>{{ t.customer }}</b>
          <div class="contact">
            {% for p in t.phones %}{{ p }}<br>{% else %}<i class="muted">No phone on file &mdash; check VinSolutions</i><br>{% endfor %}
            {% if t.do_not_email %}<span class="dne">Do not email</span>{% elif t.email %}{{ t.email }}{% endif %}
          </div>
          {% if t.vehicle %}<div class="veh">{{ t.vehicle }}</div>{% endif %}
        </td>
        <td>
          {% for r in t.reasons %}<div class="reason"><span class="tag r-{{ r.rule }}">{{ r.label }}</span>{{ r.detail }}</div>{% endfor %}
          {% if t.reassigned %}<div class="re">{{ t.note }}</div>{% endif %}
        </td>
        <td class="act">{{ t.action }}</td>
        <td class="out"></td>
      </tr>
      {% endfor %}
    </table>
    {% endfor %}
  </section>
  {% endfor %}
</body></html>
"""


def _load_plan(week: str) -> dict:
    plan = plans.load(week)
    if plan is None:
        abort(404)
    return plan


@app.route("/plan/<week>")
def plan_overview(week: str):
    plan = _load_plan(week)
    s = store.load()
    updated = store.last_updated()
    built = datetime.fromisoformat(plan["generated_at"]).date()
    return render_template_string(
        page(f"Plans — week of {week}", OVERVIEW_BODY, width=1100),
        week=week,
        week_label=week_label(week),
        generated=_local_time(plan["generated_at"]),
        stats=plan["stats"],
        advisors=plan["advisors"],
        reassigned=sum(a["reassigned"] for a in plan["advisors"]),
        rules=list(RULE_LABELS),
        labels=RULE_LABELS,
        cooldown=s["cooldown_weeks"],
        distribute=s["unowned"]["distribute"],
        stale=updated is not None and updated > built,
        storage_warning=storage_warning(),
        other_weeks=[w for w in plans.weeks() if w != week][:12],
    )


def _sections(plan: dict, names: list[str]) -> list[dict]:
    start = date.fromisoformat(plan["week_start"])
    out = []
    for name in names:
        items = tasks_for(plan, name)
        days = []
        for day in plan["work_days"]:
            todays = [t for t in items if t["day"] == day]
            if not todays:
                continue
            when = start + timedelta(days=WEEKDAYS.index(day))
            for t in todays:
                primary = max(t["reasons"], key=lambda r: r["score"])
                t["action"] = RULE_ACTIONS[primary["rule"]]
                t["note"] = assignment_note(t)
            days.append((f"{DAY_NAMES[day]}, {when:%b} {when.day}", todays))
        mix = Counter(max(t["reasons"], key=lambda r: r["score"])["rule"] for t in items)
        out.append({"name": name, "count": len(items), "days": days,
                    "mix": [(r, mix[r]) for r in RULE_LABELS if mix[r]]})
    return out


def _render_plan(plan: dict, names: list[str], title: str) -> str:
    return render_template_string(
        PLAN_BODY, title=title, style=STYLE.replace("{width}", "1100") + PLAN_STYLE,
        week=plan["week_start"], week_label=week_label(plan["week_start"]),
        dealership=plan["dealership"], labels=RULE_LABELS,
        sections=_sections(plan, names))


@app.route("/plan/<week>/advisor/<name>")
def plan_advisor(week: str, name: str):
    plan = _load_plan(week)
    if name not in [a["name"] for a in plan["advisors"]]:
        abort(404)
    return _render_plan(plan, [name], f"{name} — week of {week}")


@app.route("/plan/<week>/print")
def plan_print(week: str):
    plan = _load_plan(week)
    return _render_plan(plan, [a["name"] for a in plan["advisors"]], f"All plans — week of {week}")


@app.route("/plan/<week>/plans.xlsx")
def plan_xlsx(week: str):
    plan = _load_plan(week)
    return send_file(io.BytesIO(plan_workbook(plan)), as_attachment=True,
                     download_name=f"advisor_plans_{week}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

LOGIN_BODY = """
  <h1>Admin <span>login</span></h1>
  <p class="sub">The roster and targeting rules are limited to admins.</p>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <form method="post" action="{{ url_for('admin_login') }}">
    <label>Admin password</label>
    <input type="password" name="password" autofocus style="width:100%;">
    <div class="row"><button type="submit">Sign in</button>
      <a class="btn btn2" href="{{ url_for('index') }}">Back</a></div>
  </form>
"""

ADMIN_BODY = """
  <div class="topbar">
    <div>
      <h1>Planner <span>settings</span></h1>
      <p class="sub">Who gets plans and which customers they target. Changes apply to the next plan you build.</p>
    </div>
    <div>
      <a class="btn btn2" href="{{ url_for('index') }}">&larr; Plans</a>
      {% if has_admin_password %}
      <form method="post" action="{{ url_for('admin_logout') }}" style="display:inline;">
        <button class="btn2" style="color:#262626;">Sign out</button></form>
      {% endif %}
    </div>
  </div>
  {% if not has_admin_password %}<div class="warn"><b>No ADMIN_PASSWORD is set</b> — anyone who can
    reach this site can change settings.</div>{% endif %}
  {% if message %}<div class="okmsg">{{ message }}</div>{% endif %}
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  {% if storage_warning %}<div class="err">&#9888; {{ storage_warning }}</div>{% endif %}

  <form method="post" action="{{ url_for('admin_save') }}">
    <h2>Client advisors</h2>
    <p class="muted" style="font-size:12px;margin:0 0 8px;">
      Aliases are other spellings used in the exports (e.g. "Edward J Mathieu"); matching ignores
      capitalization and middle names/initials. Untick <b>Active</b> for someone who shouldn't
      get a plan; their customers become unowned. Blank capacity uses the default.
      Blank rows at the bottom add advisors.</p>
    <table class="grid">
      <tr><th style="width:200px;">Name</th><th>Aliases (comma-separated)</th>
          <th style="width:110px;">Weekly tasks</th><th style="width:60px;">Active</th>
          <th style="width:60px;">Remove</th></tr>
      {% for a in s.advisors %}
      <tr>
        <td><input type="text" name="an_{{ loop.index0 }}" value="{{ a.name }}"></td>
        <td><input type="text" name="aa_{{ loop.index0 }}" value="{{ a.aliases|join(', ') }}"></td>
        <td><input type="number" min="0" name="ac_{{ loop.index0 }}" value="{{ a.capacity if a.capacity is not none else '' }}" placeholder="{{ s.default_weekly_capacity }}"></td>
        <td style="text-align:center;"><input type="checkbox" name="at_{{ loop.index0 }}" {% if a.active %}checked{% endif %}></td>
        <td style="text-align:center;"><input type="checkbox" name="ax_{{ loop.index0 }}"></td>
      </tr>
      {% endfor %}
      {% for i in range(s.advisors|length, s.advisors|length + 3) %}
      <tr>
        <td><input type="text" name="an_{{ i }}" placeholder="New advisor"></td>
        <td><input type="text" name="aa_{{ i }}"></td>
        <td><input type="number" min="0" name="ac_{{ i }}" placeholder="{{ s.default_weekly_capacity }}"></td>
        <td style="text-align:center;"><input type="checkbox" name="at_{{ i }}" checked></td>
        <td></td>
      </tr>
      {% endfor %}
    </table>
    <input type="hidden" name="advisor_rows" value="{{ s.advisors|length + 3 }}">

    <h2>Plan basics</h2>
    <div class="cfg">
      <div><label>Dealership name</label><input type="text" name="dealership" value="{{ s.dealership }}"></div>
      <div><label>Default weekly tasks per advisor</label>
        <input type="number" min="0" name="default_weekly_capacity" value="{{ s.default_weekly_capacity }}"></div>
      <div><label>Don't repeat a customer for (weeks)</label>
        <input type="number" min="0" name="cooldown_weeks" value="{{ s.cooldown_weeks }}"></div>
      <div><label>Skip Mastermind statuses <small>(anywhere)</small></label>
        <input type="text" name="exclude_mastermind_statuses" value="{{ s.exclude_mastermind_statuses|join(', ') }}"></div>
    </div>
    <label>Work days</label>
    <div>{% for d in weekdays %}<label style="display:inline-block;margin:0 14px 0 0;font-weight:normal;">
      <input type="checkbox" name="wd_{{ d }}" {% if d in s.work_days %}checked{% endif %}> {{ d }}</label>{% endfor %}</div>

    <h2>Unowned customers</h2>
    <p class="muted" style="font-size:12px;margin:0;">Orphan/Conquest Mastermind records and customers of
      people not on the active roster.</p>
    <div class="cfg">
      <div><label><input type="checkbox" name="un_distribute" {% if s.unowned.distribute %}checked{% endif %}>
        Spread across advisors with spare capacity</label></div>
      <div><label>Max unowned per advisor per week <small>(0 = no limit)</small></label>
        <input type="number" min="0" name="un_max" value="{{ s.unowned.max_per_advisor }}"></div>
      <div><label><input type="checkbox" name="un_original" {% if s.unowned.use_original_salesperson %}checked{% endif %}>
        Give an orphan back to its original salesperson when they're on the roster</label></div>
    </div>

    <h2>Targeting rules</h2>
    <p class="muted" style="font-size:12px;margin:0;">Higher <b>priority weight</b> = scheduled earlier in
      the week and kept when an advisor is over capacity. <b>Max per advisor</b> keeps a mix of work in
      each plan; spare capacity is then backfilled by priority.</p>
    {% for key, title, source, desc, fields in specs %}
    <div class="rule">
      <h3><span class="tag r-{{ key }}">{{ source }}</span> {{ title }}</h3>
      <p>{{ desc }}</p>
      <div class="cfg">
        {% for name, label, kind in fields %}
        <div>
          {% set v = s.rules[key][name] %}
          {% if kind == 'bool' %}
            <label><input type="checkbox" name="r_{{ key }}_{{ name }}" {% if v %}checked{% endif %}> {{ label }}</label>
          {% elif kind == 'list' %}
            <label>{{ label }}</label><input type="text" name="r_{{ key }}_{{ name }}" value="{{ v|join(', ') }}">
          {% else %}
            <label>{{ label }}</label><input type="number" step="{{ '0.01' if kind == 'money' else '1' }}" name="r_{{ key }}_{{ name }}" value="{{ v|int if kind == 'money' and v == v|int else v }}">
          {% endif %}
        </div>
        {% endfor %}
      </div>
    </div>
    {% endfor %}
    <div class="row"><button type="submit">Save settings</button></div>
  </form>

  <h2>Backup</h2>
  <div class="row" style="margin-top:8px;">
    <a class="btn btn2" href="{{ url_for('admin_export') }}">Export settings.json</a>
    <form method="post" action="{{ url_for('admin_import') }}" enctype="multipart/form-data" class="row" style="margin:0;">
      <input type="file" name="settings" accept=".json" required style="width:260px;">
      <button class="btn2" style="color:#262626;">Restore backup</button>
    </form>
    <form method="post" action="{{ url_for('admin_reset') }}" style="margin:0;"
          onsubmit="return confirm('Reset every setting, including the roster, to the defaults?');">
      <button class="btn2" style="color:#991b1b;">Reset to defaults</button>
    </form>
  </div>
  <p class="muted" style="font-size:12px;margin-top:14px;">Data folder: <code>{{ data_dir }}</code></p>
"""


def _admin_page(message: str | None = None, error: str | None = None, settings: dict | None = None):
    return render_template_string(
        page("Planner settings", ADMIN_BODY, width=1000),
        s=settings or store.load(), specs=RULE_SPECS, weekdays=WEEKDAYS,
        has_admin_password=bool(os.environ.get("ADMIN_PASSWORD")),
        storage_warning=storage_warning(), data_dir=str(data_dir()),
        message=message, error=error)


@app.route("/admin")
def admin():
    if not is_admin():
        return render_template_string(page("Admin login", LOGIN_BODY, width=480), error=None)
    return _admin_page(message=request.args.get("message"))


@app.route("/admin/login", methods=["POST"])
def admin_login():
    expected = os.environ.get("ADMIN_PASSWORD", "")
    if expected and hmac.compare_digest(request.form.get("password", ""), expected):
        session["is_admin"] = True
        return redirect(url_for("admin"))
    return render_template_string(page("Admin login", LOGIN_BODY, width=480), error="Wrong password.")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))


def _csv(raw: str | None) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def _int(name: str, default):
    raw = (request.form.get(name) or "").strip()
    return int(float(raw)) if raw else default


def settings_from_form(form, current: dict) -> dict:
    s = json.loads(json.dumps(current))
    advisors = []
    for i in range(int(form.get("advisor_rows", 0))):
        name = (form.get(f"an_{i}") or "").strip()
        if not name or form.get(f"ax_{i}"):
            continue
        cap = (form.get(f"ac_{i}") or "").strip()
        advisors.append({"name": name, "aliases": _csv(form.get(f"aa_{i}")),
                         "active": bool(form.get(f"at_{i}")),
                         "capacity": int(float(cap)) if cap else None})
    if not any(a["active"] for a in advisors):
        raise ValueError("At least one active advisor is required.")
    s["advisors"] = advisors
    s["dealership"] = (form.get("dealership") or s["dealership"]).strip()
    s["default_weekly_capacity"] = _int("default_weekly_capacity", s["default_weekly_capacity"])
    s["cooldown_weeks"] = _int("cooldown_weeks", s["cooldown_weeks"])
    s["exclude_mastermind_statuses"] = _csv(form.get("exclude_mastermind_statuses"))
    s["work_days"] = [d for d in WEEKDAYS if form.get(f"wd_{d}")]
    if not s["work_days"]:
        raise ValueError("Pick at least one work day.")
    s["unowned"] = {"distribute": bool(form.get("un_distribute")),
                    "max_per_advisor": _int("un_max", s["unowned"]["max_per_advisor"]),
                    "use_original_salesperson": bool(form.get("un_original"))}
    for key, _title, _src, _desc, fields in RULE_SPECS:
        for name, label, kind in fields:
            field = f"r_{key}_{name}"
            if kind == "bool":
                s["rules"][key][name] = bool(form.get(field))
            elif kind == "list":
                s["rules"][key][name] = _csv(form.get(field))
            else:
                raw = (form.get(field) or "").strip()
                if raw == "":
                    raise ValueError(f"{RULE_LABELS[key]}: '{label}' is required.")
                s["rules"][key][name] = float(raw) if kind == "money" else int(float(raw))
    return normalize_settings(s)


@app.route("/admin/save", methods=["POST"])
def admin_save():
    if not is_admin():
        return redirect(url_for("admin"))
    try:
        store.save(settings_from_form(request.form, store.load()))
        return redirect(url_for("admin", message="Settings saved. Rebuild the plan to apply them."))
    except (ValueError, TypeError) as exc:
        return _admin_page(error=f"Nothing saved — {exc}")


@app.route("/admin/export")
def admin_export():
    if not is_admin():
        return redirect(url_for("admin"))
    payload = json.dumps(store.load(), indent=2).encode()
    return send_file(io.BytesIO(payload), mimetype="application/json", as_attachment=True,
                     download_name=f"planner_settings_{date.today().isoformat()}.json")


@app.route("/admin/import", methods=["POST"])
def admin_import():
    if not is_admin():
        return redirect(url_for("admin"))
    f = request.files.get("settings")
    if f is None or not f.filename:
        return _admin_page(error="No settings file selected.")
    try:
        store.save(normalize_settings(json.load(f.stream)))
        return redirect(url_for("admin", message="Settings backup restored."))
    except Exception as exc:
        return _admin_page(error=f"Restore failed — {exc}")


@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    if not is_admin():
        return redirect(url_for("admin"))
    store.save(normalize_settings({}))
    return redirect(url_for("admin", message="Settings reset to defaults."))


def main() -> None:
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), debug=False)


if __name__ == "__main__":
    main()
