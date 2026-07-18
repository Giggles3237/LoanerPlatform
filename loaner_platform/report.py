"""HTML email rendering.

Output is email-client safe: table-based layout, fully inlined CSS, no
external images, fonts, or scripts. Renders fine in Outlook/Gmail and in a
browser.
"""

from __future__ import annotations

import html
from datetime import date

from .fleet import FleetReport

BMW_BLUE = "#1c69d4"
DARK = "#262626"
MUTED = "#6b7280"
BORDER = "#e5e7eb"
ROW_ALT = "#f8fafc"
AMBER_BG = "#fef3c7"
AMBER_TX = "#92400e"
GREEN_TX = "#166534"

FONT = "Arial, Helvetica, sans-serif"


def _money(value: float | None) -> str:
    return f"${value:,.0f}" if value is not None else "—"


def _miles(value: int | None) -> str:
    return f"{value:,}" if value is not None else "—"


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


_STATUS_LABELS = {
    "over_miles": "Over program miles",
    "no_program": "No rate program for model",
    "no_msrp": "Missing MSRP",
}


def render_email(
    report: FleetReport,
    report_date: date | None = None,
    include_disclosures: bool = False,
) -> str:
    """Render the loaner sheet as a self-contained HTML email body."""
    report_date = report_date or date.today()
    rb = report.ratebook
    priced = report.priced
    attention = report.needs_attention
    updates = report.mileage_updates

    payments = [u.lease_payment for u in priced if u.lease_payment is not None]
    lowest = min(payments) if payments else None

    rows_html = []
    for i, u in enumerate(priced):
        bg = ROW_ALT if i % 2 else "#ffffff"
        miles_cell = _miles(u.odometer)
        if u.mileage_updated:
            miles_cell += (
                f' <span style="color:{AMBER_TX};font-size:11px;" '
                f'title="Updated from fleet report (vAuto shows {_miles(u.vauto_odometer)})">'
                f"&#9650;</span>"
            )
        rows_html.append(f"""
        <tr style="background:{bg};">
          <td style="padding:7px 10px;border-bottom:1px solid {BORDER};font-weight:bold;white-space:nowrap;">{_esc(u.stock_number)}</td>
          <td style="padding:7px 10px;border-bottom:1px solid {BORDER};">{_esc(u.model)}</td>
          <td style="padding:7px 10px;border-bottom:1px solid {BORDER};">{_esc(u.color)}</td>
          <td data-v="{u.odometer}" style="padding:7px 10px;border-bottom:1px solid {BORDER};text-align:right;white-space:nowrap;">{miles_cell}</td>
          <td data-v="{u.msrp or 0}" style="padding:7px 10px;border-bottom:1px solid {BORDER};text-align:right;">{_money(u.msrp)}</td>
          <td data-v="{u.sale_price or 0}" style="padding:7px 10px;border-bottom:1px solid {BORDER};text-align:right;">{_money(u.sale_price)}</td>
          <td data-v="{u.term or 0}" style="padding:7px 10px;border-bottom:1px solid {BORDER};text-align:center;">{u.term or "—"}</td>
          <td data-v="{u.lease_payment}" style="padding:7px 10px;border-bottom:1px solid {BORDER};text-align:right;font-weight:bold;color:{BMW_BLUE};white-space:nowrap;">${u.lease_payment}<span style="font-weight:normal;color:{MUTED};font-size:11px;">/mo</span></td>
        </tr>""")

    th = (
        f'style="padding:8px 10px;text-align:left;font-size:11px;letter-spacing:0.06em;'
        f'text-transform:uppercase;color:#ffffff;background:{DARK};white-space:nowrap;"'
    )
    thr = th.replace("text-align:left", "text-align:right")
    thc = th.replace("text-align:left", "text-align:center")

    sections = [f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="sortable" style="border-collapse:collapse;font-family:{FONT};font-size:13px;color:{DARK};">
      <thead><tr>
        <th {th}>Stock #<span class="arw"></span></th><th {th}>Model<span class="arw"></span></th><th {th}>Color<span class="arw"></span></th>
        <th {thr}>Miles<span class="arw"></span></th><th {thr}>MSRP<span class="arw"></span></th><th {thr}>Sale Price<span class="arw"></span></th>
        <th {thc}>Term<span class="arw"></span></th><th {thr}>Lease<span class="arw"></span></th>
      </tr></thead>
      <tbody>{''.join(rows_html)}</tbody>
    </table>"""]

    if updates:
        update_rows = "".join(
            f"""<tr>
              <td style="padding:6px 10px;border-bottom:1px solid {BORDER};font-weight:bold;">{_esc(u.stock_number)}</td>
              <td style="padding:6px 10px;border-bottom:1px solid {BORDER};">{_esc(u.model)}</td>
              <td data-v="{u.vauto_odometer or 0}" style="padding:6px 10px;border-bottom:1px solid {BORDER};text-align:right;">{_miles(u.vauto_odometer)}</td>
              <td data-v="{u.tsd_miles or 0}" style="padding:6px 10px;border-bottom:1px solid {BORDER};text-align:right;font-weight:bold;color:{AMBER_TX};">{_miles(u.tsd_miles)}</td>
              <td data-v="{(u.tsd_miles or 0) - (u.vauto_odometer or 0)}" style="padding:6px 10px;border-bottom:1px solid {BORDER};text-align:right;">{_miles((u.tsd_miles or 0) - (u.vauto_odometer or 0))}</td>
            </tr>"""
            for u in updates
        )
        sections.append(f"""
    <h2 style="font-family:{FONT};font-size:15px;color:{DARK};margin:28px 0 8px;">
      &#9650; Mileage updates needed in vAuto ({len(updates)})
    </h2>
    <p style="font-family:{FONT};font-size:12px;color:{MUTED};margin:0 0 10px;">
      The fleet report shows more miles than the vAuto export. Pricing above already
      uses the higher reading; update these odometers in vAuto.
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" class="sortable" style="border-collapse:collapse;font-family:{FONT};font-size:13px;color:{DARK};">
      <thead><tr>
        <th {th}>Stock #<span class="arw"></span></th><th {th}>Model<span class="arw"></span></th>
        <th {thr}>vAuto Odo<span class="arw"></span></th><th {thr}>Fleet Miles<span class="arw"></span></th><th {thr}>Difference<span class="arw"></span></th>
      </tr></thead>
      <tbody>{update_rows}</tbody>
    </table>""")

    if attention:
        att_rows = "".join(
            f"""<tr>
              <td style="padding:6px 10px;border-bottom:1px solid {BORDER};font-weight:bold;">{_esc(u.stock_number)}</td>
              <td style="padding:6px 10px;border-bottom:1px solid {BORDER};">{_esc(u.model)}</td>
              <td data-v="{u.odometer}" style="padding:6px 10px;border-bottom:1px solid {BORDER};text-align:right;">{_miles(u.odometer)}</td>
              <td style="padding:6px 10px;border-bottom:1px solid {BORDER};">
                <span style="background:{AMBER_BG};color:{AMBER_TX};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold;">
                  {_STATUS_LABELS.get(u.status, u.status)}
                </span>
              </td>
              <td style="padding:6px 10px;border-bottom:1px solid {BORDER};color:{MUTED};font-size:12px;">{_esc('; '.join(u.warnings))}</td>
            </tr>"""
            for u in attention
        )
        sections.append(f"""
    <h2 style="font-family:{FONT};font-size:15px;color:{DARK};margin:28px 0 8px;">
      Not priced — needs attention ({len(attention)})
    </h2>
    <table role="presentation" cellpadding="0" cellspacing="0" class="sortable" style="border-collapse:collapse;font-family:{FONT};font-size:13px;color:{DARK};">
      <thead><tr>
        <th {th}>Stock #<span class="arw"></span></th><th {th}>Model<span class="arw"></span></th><th {thr}>Miles<span class="arw"></span></th><th {th}>Reason<span class="arw"></span></th><th {th}>Detail</th>
      </tr></thead>
      <tbody>{att_rows}</tbody>
    </table>""")

    if report.missing_from_vauto:
        missing_rows = "".join(
            f"""<tr>
              <td style="padding:6px 10px;border-bottom:1px solid {BORDER};font-weight:bold;">{_esc(m.unit_number)}</td>
              <td style="padding:6px 10px;border-bottom:1px solid {BORDER};">{_esc(m.year or '')} {_esc(m.model)}</td>
              <td data-v="{m.miles or 0}" style="padding:6px 10px;border-bottom:1px solid {BORDER};text-align:right;">{_miles(m.miles)}</td>
              <td style="padding:6px 10px;border-bottom:1px solid {BORDER};">{_esc(m.status)}</td>
            </tr>"""
            for m in report.missing_from_vauto
        )
        sections.append(f"""
    <h2 style="font-family:{FONT};font-size:15px;color:{DARK};margin:28px 0 8px;">
      In the fleet report but not in vAuto ({len(report.missing_from_vauto)})
    </h2>
    <p style="font-family:{FONT};font-size:12px;color:{MUTED};margin:0 0 10px;">
      Active loaners with no matching vAuto stock number — add them to vAuto to get pricing.
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" class="sortable" style="border-collapse:collapse;font-family:{FONT};font-size:13px;color:{DARK};">
      <thead><tr><th {th}>Unit #<span class="arw"></span></th><th {th}>Model<span class="arw"></span></th><th {thr}>Miles<span class="arw"></span></th><th {th}>Status<span class="arw"></span></th></tr></thead>
      <tbody>{missing_rows}</tbody>
    </table>""")

    if include_disclosures:
        disc = "".join(
            f'<p style="font-family:{FONT};font-size:10px;color:{MUTED};margin:0 0 8px;">'
            f"<b>{_esc(u.stock_number)}</b> — {_esc(u.disclosure)}</p>"
            for u in priced
        )
        sections.append(f"""
    <h2 style="font-family:{FONT};font-size:15px;color:{DARK};margin:28px 0 8px;">Disclosures</h2>
    {disc}""")

    program_date = rb.program_date.strftime("%m/%d/%Y") if rb.program_date else ""
    stats = [
        f"<b>{len(priced)}</b> loaners priced",
        f"payments from <b>${lowest}</b>/mo" if lowest else "",
        f"<b>{len(updates)}</b> mileage updates" if updates else "",
        f"<b>{len(attention)}</b> need attention" if attention else "",
    ]
    stats_html = " &nbsp;&bull;&nbsp; ".join(s for s in stats if s)

    return f"""<div style="max-width:860px;margin:0 auto;background:#ffffff;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
    <tr>
      <td style="background:{DARK};padding:22px 24px;border-top:4px solid {BMW_BLUE};">
        <div style="font-family:{FONT};font-size:20px;font-weight:bold;color:#ffffff;">
          Loaner Payment Sheet
        </div>
        <div style="font-family:{FONT};font-size:13px;color:#c7cdd6;margin-top:4px;">
          {_esc(rb.dealership)} &nbsp;&bull;&nbsp; {report_date.strftime('%A, %B %d, %Y')}
          {f'&nbsp;&bull;&nbsp; Programs through {program_date}' if program_date else ''}
        </div>
      </td>
    </tr>
    <tr>
      <td style="padding:14px 24px;background:#eef4fc;font-family:{FONT};font-size:13px;color:{DARK};">
        {stats_html}
      </td>
    </tr>
    <tr><td style="padding:18px 24px 6px;">{''.join(sections)}</td></tr>
    <tr>
      <td style="padding:0 24px;font-family:{FONT};font-size:11px;color:{MUTED};display:none;" class="sort-hint">
        Click any column header to sort.
      </td>
    </tr>
    <tr>
      <td style="padding:18px 24px 26px;">
        <p style="font-family:{FONT};font-size:10px;color:{MUTED};line-height:1.5;margin:0;">
          Lease financing available from {_esc(rb.dealership)} through BMW/MINI Financial
          Services{f' through {program_date}' if program_date else ''}. Payments shown are
          monthly, based on $0 down payment, first month payment and ${rb.acquisition_fee:g}
          acquisition fee due at signing, with $0 security deposit (not all customers will
          qualify for security deposit waiver). Tax, title, license, registration and dealer
          fees additional. Vehicles are retired courtesy cars; mileage as shown. Programs
          available to eligible, qualified customers with excellent credit history who meet
          credit requirements. Payments do not include applicable taxes. Lessee responsible
          for insurance and excess wear and tear, ${rb.excess_mileage_rate}/mile over
          {rb.annual_mileage_allowance:,} miles per year, and a ${rb.disposition_fee:g}
          disposition fee at lease end. See dealer for complete details on any vehicle.
        </p>
        <p style="font-family:{FONT};font-size:10px;color:{MUTED};margin:10px 0 0;">
          Confidential — generated {report_date.strftime('%m/%d/%Y')} by LoanerPlatform.
        </p>
      </td>
    </tr>
  </table>
</div>
{SORT_SCRIPT}
"""


# Click-to-sort for browser viewing (web UI preview or the saved .html file).
# Email clients strip <script>, so the emailed copy stays a static table and
# the sort hint (display:none until revealed here) never shows there.
SORT_SCRIPT = """<script>
(function () {
  var hints = document.querySelectorAll('.sort-hint');
  for (var h = 0; h < hints.length; h++) hints[h].style.display = 'table-cell';
  var tables = document.querySelectorAll('table.sortable');
  for (var t = 0; t < tables.length; t++) (function (table) {
    if (!table.tHead || !table.tBodies.length) return;
    var ths = table.tHead.rows[0].cells;
    var body = table.tBodies[0];
    var dir = {};
    for (var i = 0; i < ths.length; i++) (function (i) {
      var th = ths[i];
      if (!th.querySelector('.arw')) return;  // column not sortable
      th.style.cursor = 'pointer';
      th.title = 'Click to sort';
      th.addEventListener('click', function () {
        var asc = dir[i] = !dir[i];
        var rows = Array.prototype.slice.call(body.rows);
        rows.sort(function (a, b) {
          var av = a.cells[i].getAttribute('data-v');
          var bv = b.cells[i].getAttribute('data-v');
          var cmp;
          if (av !== null && bv !== null) {
            cmp = parseFloat(av) - parseFloat(bv);
          } else {
            cmp = a.cells[i].textContent.trim().localeCompare(
                  b.cells[i].textContent.trim(), undefined, {numeric: true});
          }
          return asc ? cmp : -cmp;
        });
        for (var r = 0; r < rows.length; r++) {
          rows[r].style.background = r % 2 ? '#f8fafc' : '#ffffff';
          body.appendChild(rows[r]);
        }
        for (var k = 0; k < ths.length; k++) {
          var arw = ths[k].querySelector('.arw');
          if (arw) arw.textContent = (k === i) ? (asc ? ' \\u25B2' : ' \\u25BC') : '';
        }
      });
    })(i);
  })(tables[t]);
})();
</script>"""
