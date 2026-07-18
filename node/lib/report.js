// HTML sheet rendering — port of loaner_platform/report.py.
// Output is email-client safe (tables + inline CSS); the <script> at the end
// adds sorting and brand filtering in browsers and is stripped by email
// clients, so emailed copies degrade to a static sheet.

const BMW_BLUE = '#1c69d4';
const DARK = '#262626';
const MUTED = '#6b7280';
const BORDER = '#e5e7eb';
const ROW_ALT = '#f8fafc';
const AMBER_BG = '#fef3c7';
const AMBER_TX = '#92400e';
const FONT = 'Arial, Helvetica, sans-serif';

const STATUS_LABELS = {
  over_miles: 'Over program miles',
  no_program: 'No rate program for model',
  no_msrp: 'Missing MSRP',
};

const moneyFmt = v => (v === null || v === undefined ? '—'
  : '$' + Math.round(v).toLocaleString('en-US'));
const milesFmt = v => (v === null || v === undefined ? '—' : v.toLocaleString('en-US'));

const esc = v => String(v ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

function brandOf(stock, model) {
  const s = (stock || '').toUpperCase();
  const m = (model || '').toUpperCase();
  return (s.startsWith('PM') || m.includes('MINI')) ? 'MINI' : 'BMW';
}

const FILTER_BTN =
  'font-family:Arial,Helvetica,sans-serif;font-size:12px;font-weight:bold;' +
  'padding:6px 14px;border:1px solid #1c69d4;background:#ffffff;color:#1c69d4;cursor:pointer;';
const FILTER_ON = 'background:#1c69d4;color:#ffffff;';

const TH =
  `style="padding:8px 10px;text-align:left;font-size:11px;letter-spacing:0.06em;` +
  `text-transform:uppercase;color:#ffffff;background:${DARK};white-space:nowrap;"`;
const THR = TH.replace('text-align:left', 'text-align:right');
const THC = TH.replace('text-align:left', 'text-align:center');

function td(extra = '') {
  return `style="padding:7px 10px;border-bottom:1px solid ${BORDER};${extra}"`;
}

function renderSheet(report, settings, { reportDate = new Date(), includeDisclosures = false } = {}) {
  const priced = report.priced;
  const attention = report.needsAttention;
  const updates = report.mileageUpdates;
  const payments = priced.map(u => u.leasePayment).filter(p => p !== null);
  const lowest = payments.length ? Math.min(...payments) : null;

  const rows = priced.map((u, i) => {
    const bg = i % 2 ? ROW_ALT : '#ffffff';
    let milesCell = milesFmt(u.odometer);
    if (u.mileageUpdated) {
      milesCell += ` <span style="color:${AMBER_TX};font-size:11px;" ` +
        `title="Updated from fleet report (vAuto shows ${milesFmt(u.vautoOdometer)})">&#9650;</span>`;
    }
    return `
        <tr data-brand="${brandOf(u.stockNumber, u.model)}" style="background:${bg};">
          <td ${td('font-weight:bold;white-space:nowrap;')}>${esc(u.stockNumber)}</td>
          <td ${td()}>${esc(u.model)}</td>
          <td ${td()}>${esc(u.color)}</td>
          <td data-v="${u.odometer}" ${td('text-align:right;white-space:nowrap;')}>${milesCell}</td>
          <td data-v="${u.msrp || 0}" ${td('text-align:right;')}>${moneyFmt(u.msrp)}</td>
          <td data-v="${u.salePrice || 0}" ${td('text-align:right;')}>${moneyFmt(u.salePrice)}</td>
          <td data-v="${u.term || 0}" ${td('text-align:center;')}>${u.term ?? '—'}</td>
          <td data-v="${u.leasePayment}" ${td(`text-align:right;font-weight:bold;color:${BMW_BLUE};white-space:nowrap;`)}>$${u.leasePayment}<span style="font-weight:normal;color:${MUTED};font-size:11px;">/mo</span></td>
        </tr>`;
  }).join('');

  const sections = [`
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="sortable" style="border-collapse:collapse;font-family:${FONT};font-size:13px;color:${DARK};">
      <thead><tr>
        <th ${TH}>Stock #<span class="arw"></span></th><th ${TH}>Model<span class="arw"></span></th><th ${TH}>Color<span class="arw"></span></th>
        <th ${THR}>Miles<span class="arw"></span></th><th ${THR}>MSRP<span class="arw"></span></th><th ${THR}>Sale Price<span class="arw"></span></th>
        <th ${THC}>Term<span class="arw"></span></th><th ${THR}>Lease<span class="arw"></span></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`];

  if (updates.length) {
    const updateRows = updates.map(u => `<tr data-brand="${brandOf(u.stockNumber, u.model)}">
        <td ${td('font-weight:bold;')}>${esc(u.stockNumber)}</td>
        <td ${td()}>${esc(u.model)}</td>
        <td data-v="${u.vautoOdometer || 0}" ${td('text-align:right;')}>${milesFmt(u.vautoOdometer)}</td>
        <td data-v="${u.tsdMiles || 0}" ${td(`text-align:right;font-weight:bold;color:${AMBER_TX};`)}>${milesFmt(u.tsdMiles)}</td>
        <td data-v="${(u.tsdMiles || 0) - (u.vautoOdometer || 0)}" ${td('text-align:right;')}>${milesFmt((u.tsdMiles || 0) - (u.vautoOdometer || 0))}</td>
      </tr>`).join('');
    sections.push(`
    <h2 style="font-family:${FONT};font-size:15px;color:${DARK};margin:28px 0 8px;">
      &#9650; Mileage updates needed in vAuto (${updates.length})
    </h2>
    <p style="font-family:${FONT};font-size:12px;color:${MUTED};margin:0 0 10px;">
      The fleet report shows more miles than the vAuto export. Pricing above already
      uses the higher reading; update these odometers in vAuto.
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" class="sortable" style="border-collapse:collapse;font-family:${FONT};font-size:13px;color:${DARK};">
      <thead><tr>
        <th ${TH}>Stock #<span class="arw"></span></th><th ${TH}>Model<span class="arw"></span></th>
        <th ${THR}>vAuto Odo<span class="arw"></span></th><th ${THR}>Fleet Miles<span class="arw"></span></th><th ${THR}>Difference<span class="arw"></span></th>
      </tr></thead>
      <tbody>${updateRows}</tbody>
    </table>`);
  }

  if (attention.length) {
    const attRows = attention.map(u => `<tr data-brand="${brandOf(u.stockNumber, u.model)}">
        <td ${td('font-weight:bold;')}>${esc(u.stockNumber)}</td>
        <td ${td()}>${esc(u.model)}</td>
        <td data-v="${u.odometer}" ${td('text-align:right;')}>${milesFmt(u.odometer)}</td>
        <td ${td()}>
          <span style="background:${AMBER_BG};color:${AMBER_TX};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold;">
            ${STATUS_LABELS[u.status] || u.status}
          </span>
        </td>
        <td ${td(`color:${MUTED};font-size:12px;`)}>${esc(u.warnings.join('; '))}</td>
      </tr>`).join('');
    sections.push(`
    <h2 style="font-family:${FONT};font-size:15px;color:${DARK};margin:28px 0 8px;">
      Not priced — needs attention (${attention.length})
    </h2>
    <table role="presentation" cellpadding="0" cellspacing="0" class="sortable" style="border-collapse:collapse;font-family:${FONT};font-size:13px;color:${DARK};">
      <thead><tr>
        <th ${TH}>Stock #<span class="arw"></span></th><th ${TH}>Model<span class="arw"></span></th><th ${THR}>Miles<span class="arw"></span></th><th ${TH}>Reason<span class="arw"></span></th><th ${TH}>Detail</th>
      </tr></thead>
      <tbody>${attRows}</tbody>
    </table>`);
  }

  if (report.missingFromVauto.length) {
    const missingRows = report.missingFromVauto.map(m => `<tr data-brand="${brandOf(m.unitNumber, m.model)}">
        <td ${td('font-weight:bold;')}>${esc(m.unitNumber)}</td>
        <td ${td()}>${esc(m.year ?? '')} ${esc(m.model)}</td>
        <td data-v="${m.miles || 0}" ${td('text-align:right;')}>${milesFmt(m.miles)}</td>
        <td ${td()}>${esc(m.status)}</td>
      </tr>`).join('');
    sections.push(`
    <h2 style="font-family:${FONT};font-size:15px;color:${DARK};margin:28px 0 8px;">
      In the fleet report but not in vAuto (${report.missingFromVauto.length})
    </h2>
    <p style="font-family:${FONT};font-size:12px;color:${MUTED};margin:0 0 10px;">
      Active loaners with no matching vAuto stock number — add them to vAuto to get pricing.
    </p>
    <table role="presentation" cellpadding="0" cellspacing="0" class="sortable" style="border-collapse:collapse;font-family:${FONT};font-size:13px;color:${DARK};">
      <thead><tr><th ${TH}>Unit #<span class="arw"></span></th><th ${TH}>Model<span class="arw"></span></th><th ${THR}>Miles<span class="arw"></span></th><th ${TH}>Status<span class="arw"></span></th></tr></thead>
      <tbody>${missingRows}</tbody>
    </table>`);
  }

  if (includeDisclosures) {
    const disc = priced.map(u =>
      `<p style="font-family:${FONT};font-size:10px;color:${MUTED};margin:0 0 8px;">` +
      `<b>${esc(u.stockNumber)}</b> — ${esc(u.disclosure)}</p>`).join('');
    sections.push(`
    <h2 style="font-family:${FONT};font-size:15px;color:${DARK};margin:28px 0 8px;">Disclosures</h2>
    ${disc}`);
  }

  const programDate = settings.program_date
    ? `${settings.program_date.slice(5, 7)}/${settings.program_date.slice(8, 10)}/${settings.program_date.slice(0, 4)}`
    : '';
  const stats = [
    `<b>${priced.length}</b> loaners priced`,
    lowest !== null ? `payments from <b>$${lowest}</b>/mo` : '',
    updates.length ? `<b>${updates.length}</b> mileage updates` : '',
    attention.length ? `<b>${attention.length}</b> need attention` : '',
  ].filter(Boolean).join(' &nbsp;&bull;&nbsp; ');

  const dateLong = reportDate.toLocaleDateString('en-US',
    { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
  const dateShort = reportDate.toLocaleDateString('en-US');

  return `<div style="max-width:860px;margin:0 auto;background:#ffffff;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
    <tr>
      <td style="background:${DARK};padding:22px 24px;border-top:4px solid ${BMW_BLUE};">
        <div style="font-family:${FONT};font-size:20px;font-weight:bold;color:#ffffff;">
          Loaner Payment Sheet
        </div>
        <div style="font-family:${FONT};font-size:13px;color:#c7cdd6;margin-top:4px;">
          ${esc(settings.dealership)} &nbsp;&bull;&nbsp; ${dateLong}
          ${programDate ? `&nbsp;&bull;&nbsp; Programs through ${programDate}` : ''}
        </div>
      </td>
    </tr>
    <tr>
      <td style="padding:14px 24px;background:#eef4fc;font-family:${FONT};font-size:13px;color:${DARK};">
        <span id="brand-filter" style="display:none;float:right;margin-left:12px;">
          <button data-brand="ALL" style="${FILTER_BTN}${FILTER_ON}border-radius:6px 0 0 6px;">All</button><button data-brand="BMW" style="${FILTER_BTN}">BMW</button><button data-brand="MINI" style="${FILTER_BTN}border-radius:0 6px 6px 0;">MINI</button>
        </span>
        ${stats}
      </td>
    </tr>
    <tr>
      <td style="padding:0 24px;font-family:${FONT};font-size:11px;color:${MUTED};display:none;" class="sort-hint">
        Click any column header to sort.
      </td>
    </tr>
    <tr><td style="padding:18px 24px 6px;">${sections.join('')}</td></tr>
    <tr>
      <td style="padding:18px 24px 26px;">
        <p style="font-family:${FONT};font-size:10px;color:${MUTED};line-height:1.5;margin:0;">
          Lease financing available from ${esc(settings.dealership)} through BMW/MINI Financial
          Services${programDate ? ` through ${programDate}` : ''}. Payments shown are
          monthly, based on $0 down payment, first month payment and $${settings.acquisition_fee}
          acquisition fee due at signing, with $0 security deposit (not all customers will
          qualify for security deposit waiver). Tax, title, license, registration and dealer
          fees additional. Vehicles are retired courtesy cars; mileage as shown. Programs
          available to eligible, qualified customers with excellent credit history who meet
          credit requirements. Payments do not include applicable taxes. Lessee responsible
          for insurance and excess wear and tear, $${settings.excess_mileage_rate}/mile over
          ${settings.annual_mileage_allowance.toLocaleString()} miles per year, and a
          $${settings.disposition_fee} disposition fee at lease end. See dealer for complete
          details on any vehicle.
        </p>
        <p style="font-family:${FONT};font-size:10px;color:${MUTED};margin:10px 0 0;">
          Confidential — generated ${dateShort} by LoanerPlatform.
        </p>
      </td>
    </tr>
  </table>
</div>
${SORT_SCRIPT}
`;
}

// Sorting + brand filtering, browser only (email clients strip <script>).
const SORT_SCRIPT = `<script>
(function () {
  var hints = document.querySelectorAll('.sort-hint');
  for (var h = 0; h < hints.length; h++) hints[h].style.display = 'table-cell';

  function restripe(body) {
    var visible = 0;
    for (var r = 0; r < body.rows.length; r++) {
      var row = body.rows[r];
      if (row.style.display === 'none') continue;
      row.style.background = visible % 2 ? '#f8fafc' : '#ffffff';
      visible++;
    }
  }

  var tables = document.querySelectorAll('table.sortable');
  for (var t = 0; t < tables.length; t++) (function (table) {
    if (!table.tHead || !table.tBodies.length) return;
    var ths = table.tHead.rows[0].cells;
    var body = table.tBodies[0];
    var dir = {};
    for (var i = 0; i < ths.length; i++) (function (i) {
      var th = ths[i];
      if (!th.querySelector('.arw')) return;
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
        for (var r = 0; r < rows.length; r++) body.appendChild(rows[r]);
        restripe(body);
        for (var k = 0; k < ths.length; k++) {
          var arw = ths[k].querySelector('.arw');
          if (arw) arw.textContent = (k === i) ? (asc ? ' \\u25B2' : ' \\u25BC') : '';
        }
      });
    })(i);
  })(tables[t]);

  var bar = document.getElementById('brand-filter');
  if (!bar) return;
  bar.style.display = 'inline';
  var buttons = bar.querySelectorAll('button');
  function applyFilter(brand) {
    for (var b = 0; b < buttons.length; b++) {
      var on = buttons[b].getAttribute('data-brand') === brand;
      buttons[b].style.background = on ? '#1c69d4' : '#ffffff';
      buttons[b].style.color = on ? '#ffffff' : '#1c69d4';
    }
    var rows = document.querySelectorAll('tr[data-brand]');
    for (var r = 0; r < rows.length; r++) {
      var match = brand === 'ALL' || rows[r].getAttribute('data-brand') === brand;
      rows[r].style.display = match ? '' : 'none';
    }
    for (var t2 = 0; t2 < tables.length; t2++) {
      if (tables[t2].tBodies.length) restripe(tables[t2].tBodies[0]);
    }
  }
  for (var b = 0; b < buttons.length; b++) (function (btn) {
    btn.addEventListener('click', function () {
      applyFilter(btn.getAttribute('data-brand'));
    });
  })(buttons[b]);
})();
</script>`;

module.exports = { renderSheet, brandOf };
