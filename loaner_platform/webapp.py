"""LoanerPlatform web app — the living payment sheet.

Team flow (any user with APP_PASSWORD):
    upload the Full Inventory Report + vAuto export -> get the HTML sheet.
    Rates come from the app's stored settings, not a spreadsheet.

Admin flow (ADMIN_PASSWORD):
    /admin — edit model programs (money factor, residual, incentive, term),
    the mileage discount chart, and every formula setting; bulk-import a
    Simple Calculator workbook; export/import settings backups.

Environment variables:
    APP_PASSWORD    password for the whole site (required when hosted)
    ADMIN_PASSWORD  password for /admin (required when hosted)
    SECRET_KEY      session signing key (optional; random per boot otherwise)
    SETTINGS_PATH   where settings.json lives (point at a persistent disk)
    PORT            dev-server port (default 5000)
"""

from __future__ import annotations

import hmac
import io
import json
import os
import secrets
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (Flask, Response, redirect, render_template_string, request,
                   send_file, session, url_for)

from .fleet import process_fleet
from .models import ModelProgram, RateBook
from .parsers import parse_inventory, parse_ratebook, parse_vauto
from .report import render_email
from .settings import (ReportStore, SettingsStore, ratebook_from_dict,
                       ratebook_to_dict)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB of uploads


def _secret_key() -> str:
    """Stable session-signing key.

    Without a stable key, each gunicorn worker would mint its own and admin
    sessions would randomly bounce between signed-in and signed-out. Prefer
    an explicit SECRET_KEY; otherwise derive one from the configured
    passwords so all workers agree across restarts too.
    """
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    seed = os.environ.get("ADMIN_PASSWORD", "") + os.environ.get("APP_PASSWORD", "")
    if seed:
        import hashlib

        return hashlib.sha256(b"loanerplatform:" + seed.encode()).hexdigest()
    return secrets.token_hex(32)  # local dev, single process


app.secret_key = _secret_key()

store = SettingsStore()
reports = ReportStore()


def _local_time(iso_utc: str) -> str:
    """Format a stored UTC timestamp in the dealership's timezone."""
    tz = ZoneInfo(os.environ.get("TIMEZONE", "America/New_York"))
    dt = datetime.fromisoformat(iso_utc).astimezone(tz)
    return dt.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    return "ok"


@app.before_request
def _require_password():
    if request.path == "/healthz":
        return None  # hosting platforms probe this; must answer without auth
    password = os.environ.get("APP_PASSWORD")
    if not password:
        return None  # local use — no password configured
    auth = request.authorization
    if auth and auth.password and hmac.compare_digest(auth.password, password):
        return None
    return Response(
        "Password required.", 401,
        {"WWW-Authenticate": 'Basic realm="LoanerPlatform"'},
    )


def is_admin() -> bool:
    if not os.environ.get("ADMIN_PASSWORD"):
        return True  # local use — no admin password configured
    return bool(session.get("is_admin"))


# ---------------------------------------------------------------------------
# Shared page chrome
# ---------------------------------------------------------------------------

STYLE = """
  body { font-family: Arial, Helvetica, sans-serif; background:#f3f4f6; margin:0; }
  .wrap { max-width:{width}px; margin:32px auto; background:#fff; border-radius:10px;
          box-shadow:0 2px 10px rgba(0,0,0,.08); padding:32px; }
  h1 { font-size:22px; margin:0 0 4px; color:#262626; }
  h1 span { color:#1c69d4; }
  h2 { font-size:16px; color:#262626; margin:28px 0 10px; border-bottom:2px solid #e5e7eb;
       padding-bottom:6px; }
  p.sub { color:#6b7280; margin:0 0 20px; font-size:14px; }
  label { display:block; font-weight:bold; font-size:13px; margin:14px 0 6px; color:#262626; }
  small, .muted { color:#6b7280; font-weight:normal; }
  input[type=file] { width:100%; padding:10px; border:2px dashed #d1d5db; border-radius:8px;
                     background:#fafafa; font-size:13px; box-sizing:border-box; }
  input[type=text], input[type=number], input[type=password], input[type=date] {
      padding:7px 9px; border:1px solid #d1d5db; border-radius:6px; font-size:13px;
      box-sizing:border-box; }
  button, .btn { background:#1c69d4; color:#fff; border:0; padding:11px 24px; font-size:14px;
           border-radius:8px; cursor:pointer; font-weight:bold; text-decoration:none;
           display:inline-block; }
  button:hover, .btn:hover { background:#155ab6; }
  .btn2 { background:#e5e7eb; color:#262626; }
  .btn2:hover { background:#d1d5db; }
  .err { background:#fef2f2; color:#991b1b; padding:12px 16px; border-radius:8px;
         font-size:14px; margin:0 0 16px; }
  .okmsg { background:#f0fdf4; color:#166534; padding:12px 16px; border-radius:8px;
         font-size:14px; margin:0 0 16px; }
  .warn { background:#fffbeb; color:#92400e; padding:12px 16px; border-radius:8px;
         font-size:13px; margin:0 0 16px; }
  table.grid { border-collapse:collapse; width:100%; font-size:13px; }
  table.grid th { background:#262626; color:#fff; padding:7px 9px; text-align:left;
                  font-size:11px; text-transform:uppercase; letter-spacing:.05em; }
  table.grid td { padding:5px 6px; border-bottom:1px solid #e5e7eb; }
  table.grid input { width:100%; }
  .cfg { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:6px 18px; }
  .cfg label { margin:8px 0 4px; }
  .topbar { display:flex; justify-content:space-between; align-items:center; }
  .row { display:flex; gap:14px; align-items:center; margin-top:22px; flex-wrap:wrap; }
"""


def page(title: str, body: str, width: int = 680) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>{STYLE.replace('{width}', str(width))}</style>"
        f"</head><body><div class='wrap'>{body}</div></body></html>"
    )


# ---------------------------------------------------------------------------
# Team flow: view the latest sheet; upload new data to refresh it
# ---------------------------------------------------------------------------

SHEET_TOOLBAR = """
  <div style="max-width:860px;margin:0 auto 14px;background:#ffffff;border-radius:10px;
              box-shadow:0 2px 10px rgba(0,0,0,.08);padding:14px 24px;
              display:flex;justify-content:space-between;align-items:center;
              flex-wrap:wrap;gap:10px;font-family:Arial,Helvetica,sans-serif;">
    <div style="font-size:13px;color:#262626;">
      <b>Data last uploaded:</b> {{ generated }}
      <span class="muted" style="color:#6b7280;">
        &bull; {{ meta.priced }} priced
        {% if meta.attention %} &bull; {{ meta.attention }} need attention{% endif %}
      </span>
      {% if stale_rates %}
      <div style="color:#92400e;font-size:12px;margin-top:4px;">
        &#9888; Rates were changed after this sheet was generated — upload fresh data to reprice.
      </div>
      {% endif %}
    </div>
    <div style="display:flex;gap:10px;">
      <a class="btn" href="{{ url_for('upload') }}"
         style="background:#1c69d4;color:#fff;border-radius:8px;padding:10px 20px;
                text-decoration:none;font-weight:bold;font-size:13px;">Upload new data</a>
      <a class="btn" href="{{ url_for('admin') }}"
         style="background:#e5e7eb;color:#262626;border-radius:8px;padding:10px 20px;
                text-decoration:none;font-weight:bold;font-size:13px;">&#9881; Admin</a>
    </div>
  </div>
"""


@app.route("/", methods=["GET"])
def index():
    saved = reports.load()
    if saved is None:
        return redirect(url_for("upload"))
    body, meta = saved
    settings_updated = store.last_updated()
    generated_date = datetime.fromisoformat(meta["generated_at"]).date()
    toolbar = render_template_string(
        SHEET_TOOLBAR,
        meta=meta,
        generated=_local_time(meta["generated_at"]),
        stale_rates=settings_updated is not None and settings_updated > generated_date,
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Loaner Payment Sheet</title></head>"
        "<body style='margin:0;background:#f3f4f6;padding:24px 12px;'>"
        f"{toolbar}{body}</body></html>"
    )


UPLOAD_BODY = """
  <div class="topbar">
    <div>
      <h1>Upload <span>fresh data</span></h1>
      <p class="sub">The two daily exports — rates come from this app's settings.</p>
    </div>
    <div>
      {% if has_sheet %}<a class="btn btn2" href="{{ url_for('index') }}">&larr; Current sheet</a>{% endif %}
      <a class="btn btn2" href="{{ url_for('admin') }}">&#9881; Admin</a>
    </div>
  </div>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  {% if not has_sheet %}
    <div class="warn">No sheet has been generated yet — upload the two files to create the first one.</div>
  {% endif %}
  <div class="warn" style="background:#eef4fc;color:#262626;">
    <b>{{ programs }} models</b> on the rate sheet &bull; programs through
    <b>{{ program_date or 'not set' }}</b> &bull; settings last updated
    <b>{{ updated or 'defaults' }}</b>
  </div>
  <form method="post" action="{{ url_for('generate') }}" enctype="multipart/form-data">
    <label>Full Inventory Report <small>(.xlsx from the fleet software — current miles)</small></label>
    <input type="file" name="inventory" accept=".xlsx" required>
    <label>Payment Calculator export <small>(.xls/.xlsx from vAuto — the loaner list)</small></label>
    <input type="file" name="vauto" accept=".xls,.xlsx" required>
    <div class="row">
      <button type="submit">Generate payment sheet</button>
      <label style="margin:0;font-weight:normal;font-size:13px;">
        <input type="checkbox" name="disclosures"> include per-unit disclosures
      </label>
    </div>
  </form>
"""


@app.route("/upload", methods=["GET"])
def upload():
    rb = store.load()
    return render_template_string(
        page("Upload data", UPLOAD_BODY),
        error=request.args.get("error"),
        has_sheet=reports.exists(),
        programs=len(rb.programs),
        program_date=rb.program_date.strftime("%m/%d/%Y") if rb.program_date else None,
        updated=store.last_updated().strftime("%m/%d/%Y") if store.last_updated() else None,
    )


@app.route("/generate", methods=["POST"])
def generate():
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            paths = {}
            for key in ("inventory", "vauto"):
                file_upload = request.files.get(key)
                if file_upload is None or not file_upload.filename:
                    return redirect(url_for("upload", error=f"Missing file: {key}"))
                dest = tmp_path / f"{key}{Path(file_upload.filename).suffix.lower()}"
                file_upload.save(dest)
                paths[key] = dest
            inventory = parse_inventory(paths["inventory"])
            vauto = parse_vauto(paths["vauto"])
        ratebook = store.load()
        report = process_fleet(inventory, vauto, ratebook)
        body = render_email(
            report,
            report_date=date.today(),
            include_disclosures=bool(request.form.get("disclosures")),
        )
        reports.save(body, {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "priced": len(report.priced),
            "attention": len(report.needs_attention),
            "mileage_updates": len(report.mileage_updates),
        })
        return redirect(url_for("index"))
    except Exception as exc:
        return redirect(url_for("upload", error=str(exc)))


# ---------------------------------------------------------------------------
# Admin: login
# ---------------------------------------------------------------------------

LOGIN_BODY = """
  <h1>Admin <span>login</span></h1>
  <p class="sub">Settings changes are limited to admins.</p>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <form method="post" action="{{ url_for('admin_login') }}">
    <label>Admin password</label>
    <input type="password" name="password" autofocus style="width:100%;">
    <div class="row">
      <button type="submit">Sign in</button>
      <a class="btn btn2" href="{{ url_for('index') }}">Back</a>
    </div>
  </form>
"""


@app.route("/admin/login", methods=["POST"])
def admin_login():
    expected = os.environ.get("ADMIN_PASSWORD", "")
    supplied = request.form.get("password", "")
    if expected and hmac.compare_digest(supplied, expected):
        session["is_admin"] = True
        return redirect(url_for("admin"))
    return render_template_string(page("Admin login", LOGIN_BODY),
                                  error="Wrong password.")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Admin: settings editor
# ---------------------------------------------------------------------------

CONFIG_FIELDS = [
    # (field, label, step)
    ("dealership", "Dealership name", None),
    ("program_mileage_limit", "Program mileage limit", "1"),
    ("avp_min_miles", "AVP applies above (miles)", "1"),
    ("invoice_markup", "Sale price markup ($ over invoice)", "1"),
    ("invoice_pct_under_break", "Invoice % of MSRP (low miles)", "0.0001"),
    ("invoice_pct_over_break", "Invoice % of MSRP (high miles)", "0.0001"),
    ("invoice_mileage_break", "Invoice low/high mileage break", "1"),
    ("avp_base_deduction", "AVP: MSRP deduction ($)", "1"),
    ("avp_pct", "AVP: percent of (MSRP − deduction)", "0.0001"),
    ("avp_flat_credit", "AVP: flat credit ($)", "1"),
    ("residual_mile_charge", "Residual charge per mile ($)", "0.01"),
    ("residual_free_miles", "Residual free miles", "1"),
    ("acquisition_fee", "Acquisition fee ($)", "1"),
    ("disposition_fee", "Disposition fee ($)", "1"),
    ("excess_mileage_rate", "Excess mileage rate ($/mi)", "0.01"),
    ("annual_mileage_allowance", "Annual mileage allowance", "1"),
]

ADMIN_BODY = """
  <div class="topbar">
    <div>
      <h1>Pricing <span>settings</span></h1>
      <p class="sub">The live rate sheet — changes apply to every sheet generated after saving.</p>
    </div>
    <div>
      <a class="btn btn2" href="{{ url_for('index') }}">&larr; Sheet generator</a>
      {% if has_admin_password %}
      <form method="post" action="{{ url_for('admin_logout') }}" style="display:inline;">
        <button class="btn2" style="color:#262626;">Sign out</button>
      </form>
      {% endif %}
    </div>
  </div>
  {% if not has_admin_password %}
    <div class="warn"><b>No ADMIN_PASSWORD is set</b> — anyone who can reach this site can
    edit settings. Set the ADMIN_PASSWORD environment variable before sharing the URL.</div>
  {% endif %}
  {% if message %}<div class="okmsg">{{ message }}</div>{% endif %}
  {% if error %}<div class="err">{{ error }}</div>{% endif %}

  <form method="post" action="{{ url_for('admin_save') }}">
    <h2>Program settings</h2>
    <div class="cfg">
      {% for name, label, step in config_fields %}
        <div>
          <label>{{ label }}</label>
          {% if step %}
            <input type="number" step="{{ step }}" name="{{ name }}" value="{{ config[name] }}" style="width:100%;">
          {% else %}
            <input type="text" name="{{ name }}" value="{{ config[name] }}" style="width:100%;">
          {% endif %}
        </div>
      {% endfor %}
      <div>
        <label>Programs valid through</label>
        <input type="date" name="program_date" value="{{ config['program_date'] or '' }}" style="width:100%;">
      </div>
    </div>

    <h2>Mileage discount chart</h2>
    <p class="muted" style="font-size:12px;margin:0 0 8px;">
      Discount applied once a unit reaches the mileage breakpoint (largest breakpoint &le; miles wins).
      Leave a row's miles blank — or tick remove — to drop it. Blank rows at the bottom add new breakpoints.
    </p>
    <table class="grid" style="max-width:420px;">
      <tr><th>Miles &ge;</th><th>Discount $</th><th style="width:70px;">Remove</th></tr>
      {% for m, d in chart %}
      <tr>
        <td><input type="number" step="1" name="cm_{{ loop.index0 }}" value="{{ m }}"></td>
        <td><input type="number" step="1" name="cd_{{ loop.index0 }}" value="{{ d }}"></td>
        <td style="text-align:center;"><input type="checkbox" name="cx_{{ loop.index0 }}"></td>
      </tr>
      {% endfor %}
      {% for i in range(chart|length, chart|length + 3) %}
      <tr>
        <td><input type="number" step="1" name="cm_{{ i }}" placeholder="new"></td>
        <td><input type="number" step="1" name="cd_{{ i }}"></td>
        <td></td>
      </tr>
      {% endfor %}
    </table>
    <input type="hidden" name="chart_rows" value="{{ chart|length + 3 }}">

    <h2>Rates, residuals &amp; incentives ({{ programs|length }} models)</h2>
    <p class="muted" style="font-size:12px;margin:0 0 8px;">
      Money factor and residual use the same format as the old spreadsheet
      (e.g. 0.00095 and 0.57). Blank rows at the bottom add new models.
    </p>
    <table class="grid">
      <tr><th>Model (must match vAuto exactly)</th><th style="width:110px;">Money Factor</th>
          <th style="width:90px;">Residual</th><th style="width:100px;">Incentive $</th>
          <th style="width:70px;">39-mo</th><th style="width:70px;">Remove</th></tr>
      {% for p in programs %}
      <tr>
        <td><input type="text" name="pm_{{ loop.index0 }}" value="{{ p.model }}"></td>
        <td><input type="number" step="0.00001" name="pf_{{ loop.index0 }}" value="{{ p.money_factor }}"></td>
        <td><input type="number" step="0.01" name="pr_{{ loop.index0 }}" value="{{ p.residual_pct }}"></td>
        <td><input type="number" step="1" name="pi_{{ loop.index0 }}" value="{{ p.lease_incentive }}"></td>
        <td style="text-align:center;"><input type="checkbox" name="p9_{{ loop.index0 }}" {% if p.lease_39_month %}checked{% endif %}></td>
        <td style="text-align:center;"><input type="checkbox" name="px_{{ loop.index0 }}"></td>
      </tr>
      {% endfor %}
      {% for i in range(programs|length, programs|length + 3) %}
      <tr>
        <td><input type="text" name="pm_{{ i }}" placeholder="e.g. 2026 BMW X3 30 xDrive"></td>
        <td><input type="number" step="0.00001" name="pf_{{ i }}"></td>
        <td><input type="number" step="0.01" name="pr_{{ i }}"></td>
        <td><input type="number" step="1" name="pi_{{ i }}"></td>
        <td style="text-align:center;"><input type="checkbox" name="p9_{{ i }}"></td>
        <td></td>
      </tr>
      {% endfor %}
    </table>
    <input type="hidden" name="program_rows" value="{{ programs|length + 3 }}">

    <div class="row">
      <button type="submit">Save all settings</button>
    </div>
  </form>

  <h2>Import / backup</h2>
  <div class="row" style="margin-top:8px;">
    <form method="post" action="{{ url_for('admin_import_workbook') }}" enctype="multipart/form-data">
      <label style="margin-top:0;">Import a Simple Calculator workbook <small>(replaces rates,
      chart &amp; program limits)</small></label>
      <input type="file" name="workbook" accept=".xlsx" required>
      <div class="row" style="margin-top:10px;"><button type="submit">Import workbook</button></div>
    </form>
    <form method="post" action="{{ url_for('admin_import_json') }}" enctype="multipart/form-data">
      <label style="margin-top:0;">Restore a settings backup <small>(.json)</small></label>
      <input type="file" name="settings" accept=".json" required>
      <div class="row" style="margin-top:10px;"><button type="submit">Restore backup</button></div>
    </form>
    <div>
      <label style="margin-top:0;">Download a backup</label>
      <a class="btn btn2" href="{{ url_for('admin_export') }}">Export settings.json</a>
    </div>
  </div>
  <p class="muted" style="font-size:12px;margin-top:18px;">
    Settings file: <code>{{ settings_path }}</code>. On hosting without a persistent disk,
    saved changes can be lost when the service redeploys — download a backup after big edits,
    or point SETTINGS_PATH at a persistent disk.
  </p>
"""


def _admin_page(message: str | None = None, error: str | None = None):
    rb = store.load()
    config = ratebook_to_dict(rb)
    programs = sorted(rb.programs.values(), key=lambda p: p.model)
    return render_template_string(
        page("Pricing settings", ADMIN_BODY, width=980),
        config_fields=CONFIG_FIELDS,
        config=config,
        chart=rb.discount_chart,
        programs=programs,
        has_admin_password=bool(os.environ.get("ADMIN_PASSWORD")),
        settings_path=str(store.path),
        message=message,
        error=error,
    )


@app.route("/admin", methods=["GET"])
def admin():
    if not is_admin():
        return render_template_string(page("Admin login", LOGIN_BODY), error=None)
    return _admin_page(message=request.args.get("message"),
                       error=request.args.get("error"))


def _f(name: str, default=None):
    raw = (request.form.get(name) or "").strip()
    if raw == "":
        return default
    return float(raw)


@app.route("/admin/save", methods=["POST"])
def admin_save():
    if not is_admin():
        return redirect(url_for("admin"))
    try:
        current = store.load()

        chart = []
        for i in range(int(request.form.get("chart_rows", 0))):
            if request.form.get(f"cx_{i}"):
                continue
            miles = _f(f"cm_{i}")
            if miles is None:
                continue
            chart.append((int(miles), _f(f"cd_{i}", 0.0)))
        if not chart:
            raise ValueError("The discount chart needs at least one row (0 miles / $0 works).")

        programs: dict[str, ModelProgram] = {}
        errors = []
        for i in range(int(request.form.get("program_rows", 0))):
            if request.form.get(f"px_{i}"):
                continue
            model = (request.form.get(f"pm_{i}") or "").strip()
            if not model:
                continue
            mf, res = _f(f"pf_{i}"), _f(f"pr_{i}")
            if mf is None or res is None:
                errors.append(f"'{model}': money factor and residual are required.")
                continue
            programs[model] = ModelProgram(
                model=model, money_factor=mf, residual_pct=res,
                lease_incentive=_f(f"pi_{i}", 0.0) or 0.0,
                lease_39_month=bool(request.form.get(f"p9_{i}")),
            )
        if errors:
            raise ValueError(" ".join(errors))
        if not programs:
            raise ValueError("At least one model program is required.")

        program_date = None
        if request.form.get("program_date"):
            program_date = datetime.strptime(request.form["program_date"], "%Y-%m-%d").date()

        rb = RateBook(
            programs=programs,
            discount_chart=sorted(chart),
            program_date=program_date,
            dealership=(request.form.get("dealership") or current.dealership).strip(),
            avp_min_miles=int(_f("avp_min_miles", current.avp_min_miles)),
            program_mileage_limit=int(_f("program_mileage_limit", current.program_mileage_limit)),
            invoice_markup=_f("invoice_markup", current.invoice_markup),
            acquisition_fee=_f("acquisition_fee", current.acquisition_fee),
            disposition_fee=_f("disposition_fee", current.disposition_fee),
            excess_mileage_rate=_f("excess_mileage_rate", current.excess_mileage_rate),
            annual_mileage_allowance=int(_f("annual_mileage_allowance",
                                            current.annual_mileage_allowance)),
            invoice_pct_under_break=_f("invoice_pct_under_break", current.invoice_pct_under_break),
            invoice_pct_over_break=_f("invoice_pct_over_break", current.invoice_pct_over_break),
            invoice_mileage_break=int(_f("invoice_mileage_break", current.invoice_mileage_break)),
            avp_base_deduction=_f("avp_base_deduction", current.avp_base_deduction),
            avp_pct=_f("avp_pct", current.avp_pct),
            avp_flat_credit=_f("avp_flat_credit", current.avp_flat_credit),
            residual_mile_charge=_f("residual_mile_charge", current.residual_mile_charge),
            residual_free_miles=int(_f("residual_free_miles", current.residual_free_miles)),
        )
        store.save(rb)
        return redirect(url_for("admin", message="Settings saved."))
    except (ValueError, TypeError) as exc:
        return _admin_page(error=f"Nothing saved — {exc}")


@app.route("/admin/import-workbook", methods=["POST"])
def admin_import_workbook():
    if not is_admin():
        return redirect(url_for("admin"))
    upload = request.files.get("workbook")
    if upload is None or not upload.filename:
        return _admin_page(error="No workbook selected.")
    try:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            upload.save(tmp.name)
            rb = parse_ratebook(tmp.name)
        os.unlink(tmp.name)
        store.save(rb)
        return redirect(url_for(
            "admin",
            message=f"Imported {len(rb.programs)} model programs from the workbook."))
    except Exception as exc:
        return _admin_page(error=f"Import failed — {exc}")


@app.route("/admin/export")
def admin_export():
    if not is_admin():
        return redirect(url_for("admin"))
    payload = json.dumps(store.load_dict(), indent=2).encode()
    return send_file(
        io.BytesIO(payload), mimetype="application/json", as_attachment=True,
        download_name=f"loaner_settings_{date.today().isoformat()}.json",
    )


@app.route("/admin/import-json", methods=["POST"])
def admin_import_json():
    if not is_admin():
        return redirect(url_for("admin"))
    upload = request.files.get("settings")
    if upload is None or not upload.filename:
        return _admin_page(error="No settings file selected.")
    try:
        data = json.load(upload.stream)
        rb = ratebook_from_dict(data)
        if not rb.programs:
            raise ValueError("backup contains no model programs")
        store.save(rb)
        return redirect(url_for("admin", message="Settings backup restored."))
    except Exception as exc:
        return _admin_page(error=f"Restore failed — {exc}")


def main() -> None:
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)


if __name__ == "__main__":
    main()
