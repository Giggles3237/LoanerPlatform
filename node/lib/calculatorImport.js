// Bulk-import a Simple Calculator workbook (.xlsx) into settings.
// Port of loaner_platform/parsers.py::parse_ratebook — reads the
// 'Rates and Residuals' sheet (programs, discount chart, mileage limits)
// and the Primary sheet header (dealership name, program date).

const XLSX = require('xlsx');
const { toFloat, toInt } = require('./parsers');

const RATES_SHEET = 'Rates and Residuals';
const PRIMARY_SHEET = 'Primary';

function cellValue(ws, addr) {
  const cell = ws[addr];
  return cell ? cell.v : null;
}

/** Returns a full settings object; formula knobs carry over from `current`. */
function parseCalculatorWorkbook(buffer, current) {
  const wb = XLSX.read(buffer, { type: 'buffer', cellDates: true });
  const ws = wb.Sheets[RATES_SHEET];
  if (!ws) {
    throw new Error(`Calculator workbook has no '${RATES_SHEET}' sheet. ` +
      `Sheets: ${wb.SheetNames.join(', ')}`);
  }

  const programs = [];
  for (let r = 2; r <= 200; r++) {
    const model = cellValue(ws, `A${r}`);
    const mf = toFloat(cellValue(ws, `B${r}`));
    const res = toFloat(cellValue(ws, `C${r}`));
    if (!model || mf === null || res === null) continue;
    programs.push({
      model: String(model).trim(),
      money_factor: mf,
      residual_pct: res,
      lease_incentive: toFloat(cellValue(ws, `D${r}`)) || 0,
      lease_39_month: String(cellValue(ws, `I${r}`) || '').trim().toLowerCase() === 'y',
    });
  }
  if (!programs.length) {
    throw new Error('No model programs found on the Rates and Residuals sheet.');
  }

  const chart = [];
  for (let r = 12; r <= 19; r++) {
    const miles = toInt(cellValue(ws, `J${r}`));
    const amount = toFloat(cellValue(ws, `K${r}`));
    if (miles !== null && amount !== null) chart.push([miles, amount]);
  }
  chart.sort((a, b) => a[0] - b[0]);
  if (!chart.length) {
    throw new Error('Could not read the mileage Discount Chart (J12:K19).');
  }

  const avpMin = toInt(cellValue(ws, 'M3'));
  const limit = toInt(cellValue(ws, 'M7'));

  let dealership = current.dealership;
  let programDate = current.program_date;
  const primary = wb.Sheets[PRIMARY_SHEET];
  if (primary) {
    const d2 = cellValue(primary, 'D2');
    if (d2) dealership = String(d2).trim();
    const c2 = cellValue(primary, 'C2');
    if (c2 instanceof Date) programDate = c2.toISOString().slice(0, 10);
  }

  return {
    ...current,
    programs,
    discount_chart: chart,
    avp_min_miles: avpMin !== null ? avpMin : current.avp_min_miles,
    program_mileage_limit: limit !== null ? limit : current.program_mileage_limit,
    dealership,
    program_date: programDate,
  };
}

module.exports = { parseCalculatorWorkbook };
