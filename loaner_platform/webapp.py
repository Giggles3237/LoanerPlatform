"""Drag-and-drop web UI: upload the three files, get the email back.

Run with:
    python -m loaner_platform.webapp
then open http://localhost:5000

Set the APP_PASSWORD environment variable to require a password — do this
whenever the app is hosted anywhere beyond your own PC, since the sheet
contains cost data.
"""

from __future__ import annotations

import hmac
import os
import tempfile
from datetime import date
from pathlib import Path

from flask import Flask, Response, render_template_string, request

from .fleet import process_fleet
from .parsers import parse_inventory, parse_ratebook, parse_vauto
from .report import render_email

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB of uploads


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

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>LoanerPlatform — Payment Sheet Generator</title>
<style>
  body { font-family: Arial, Helvetica, sans-serif; background:#f3f4f6; margin:0; }
  .wrap { max-width:640px; margin:48px auto; background:#fff; border-radius:10px;
          box-shadow:0 2px 10px rgba(0,0,0,.08); padding:32px; }
  h1 { font-size:22px; margin:0 0 4px; color:#262626; }
  h1 span { color:#1c69d4; }
  p.sub { color:#6b7280; margin:0 0 24px; font-size:14px; }
  label { display:block; font-weight:bold; font-size:13px; margin:16px 0 6px; color:#262626; }
  small { color:#6b7280; font-weight:normal; }
  input[type=file] { width:100%; padding:10px; border:2px dashed #d1d5db; border-radius:8px;
                     background:#fafafa; font-size:13px; }
  .row { display:flex; gap:16px; align-items:center; margin-top:20px; }
  button { background:#1c69d4; color:#fff; border:0; padding:12px 28px; font-size:15px;
           border-radius:8px; cursor:pointer; font-weight:bold; }
  button:hover { background:#155ab6; }
  .check { font-size:13px; color:#262626; }
  .err { background:#fef2f2; color:#991b1b; padding:12px 16px; border-radius:8px;
         font-size:14px; margin-bottom:16px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Loaner <span>Payment Sheet</span> Generator</h1>
  <p class="sub">Upload the three files and get the HTML email, ready to send.</p>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <form method="post" enctype="multipart/form-data">
    <label>Full Inventory Report <small>(.xlsx from the fleet software — current miles)</small></label>
    <input type="file" name="inventory" accept=".xlsx" required>
    <label>Payment Calculator export <small>(.xls/.xlsx from vAuto — the loaner list)</small></label>
    <input type="file" name="vauto" accept=".xls,.xlsx" required>
    <label>Simple Calculator <small>(.xlsx — rates, residuals &amp; programs)</small></label>
    <input type="file" name="calculator" accept=".xlsx" required>
    <div class="row">
      <button type="submit">Generate payment sheet</button>
      <label class="check" style="margin:0;font-weight:normal;">
        <input type="checkbox" name="disclosures"> include per-unit disclosures
      </label>
    </div>
  </form>
</div>
</body>
</html>"""


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template_string(PAGE, error=None)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            paths = {}
            for key in ("inventory", "vauto", "calculator"):
                upload = request.files.get(key)
                if upload is None or not upload.filename:
                    return render_template_string(PAGE, error=f"Missing file: {key}")
                dest = tmp_path / f"{key}{Path(upload.filename).suffix.lower()}"
                upload.save(dest)
                paths[key] = dest

            inventory = parse_inventory(paths["inventory"])
            vauto = parse_vauto(paths["vauto"])
            ratebook = parse_ratebook(paths["calculator"])
            report = process_fleet(inventory, vauto, ratebook)
            body = render_email(
                report,
                report_date=date.today(),
                include_disclosures=bool(request.form.get("disclosures")),
            )
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Loaner Payment Sheet</title></head>"
            "<body style='margin:0;background:#f3f4f6;padding:24px 0;'>"
            f"{body}</body></html>"
        )
    except Exception as exc:  # surface parse errors to the user
        return render_template_string(PAGE, error=str(exc))


def main() -> None:
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)


if __name__ == "__main__":
    main()
