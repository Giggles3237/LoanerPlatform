// Parsers for the two daily exports, using SheetJS (already a chipboard
// dependency). Columns are located by header name, so column reordering in
// future exports won't break the pipeline. Port of loaner_platform/parsers.py.

const XLSX = require('xlsx');

const norm = v => (v === null || v === undefined ? '' : String(v).trim().toLowerCase());

function toInt(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(String(v).replace(/,/g, ''));
  return Number.isFinite(n) ? Math.round(n) : null;
}

function toFloat(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(String(v).replace(/[$,]/g, ''));
  return Number.isFinite(n) ? n : null;
}

function headerMap(headers, wanted) {
  const normed = headers.map(norm);
  const out = {};
  for (const [field, candidates] of Object.entries(wanted)) {
    for (const cand of candidates) {
      const idx = normed.indexOf(cand);
      if (idx !== -1) { out[field] = idx; break; }
    }
  }
  return out;
}

function sheetRows(buffer) {
  const wb = XLSX.read(buffer, { type: 'buffer' });
  const ws = wb.Sheets[wb.SheetNames[0]];
  return XLSX.utils.sheet_to_json(ws, { header: 1, defval: null });
}

// PB3626R -> PB3626, so fleet units match vAuto stocks with letter suffixes.
function baseStockNumber(stock) {
  const s = String(stock || '').trim().toUpperCase();
  const m = s.match(/^([A-Z]+\d+)/);
  return m ? m[1] : s;
}

/** Full Inventory Report (fleet software) -> Map(unitNumber -> {miles, ...}) */
function parseInventory(buffer) {
  const rows = sheetRows(buffer);
  if (!rows.length) return new Map();
  const cols = headerMap(rows[0], {
    unit: ['unit #', 'unit#', 'unit', 'stock #', 'stock#'],
    vin: ['vin'],
    year: ['year'],
    model: ['model'],
    miles: ['miles', 'odometer', 'current miles'],
    status: ['status'],
  });
  if (cols.unit === undefined || cols.miles === undefined) {
    throw new Error(
      `Inventory report is missing a Unit #/Miles column. Found headers: ${JSON.stringify(rows[0])}`);
  }
  const units = new Map();
  for (const row of rows.slice(1)) {
    const unitNo = String(row[cols.unit] ?? '').trim();
    if (!unitNo) continue;
    units.set(unitNo.toUpperCase(), {
      unitNumber: unitNo,
      vin: cols.vin !== undefined ? String(row[cols.vin] ?? '') : '',
      year: cols.year !== undefined ? toInt(row[cols.year]) : null,
      model: cols.model !== undefined ? String(row[cols.model] ?? '') : '',
      miles: toInt(row[cols.miles]),
      status: cols.status !== undefined ? String(row[cols.status] ?? '') : '',
    });
  }
  return units;
}

/** vAuto Payment Calculator export -> array of vehicles in file order */
function parseVauto(buffer) {
  const rows = sheetRows(buffer);
  if (!rows.length) return [];
  const cols = headerMap(rows[0], {
    stock: ['stock #', 'stock#', 'stock'],
    model: ['model'],
    color: ['color', 'exterior color'],
    odometer: ['odometer', 'miles'],
    vin8: ['vin 8', 'vin8', 'vin'],
    age: ['age'],
    listPrice: ['list price'],
    salesCost: ['sales cost', 'cost'],
    msrp: ['msrp'],
  });
  const missing = ['stock', 'model', 'msrp'].filter(k => cols[k] === undefined);
  if (missing.length) {
    throw new Error(
      `vAuto export is missing columns ${JSON.stringify(missing)}. Found headers: ${JSON.stringify(rows[0])}`);
  }
  const cell = (row, key) => (cols[key] !== undefined ? row[cols[key]] : null);
  const vehicles = [];
  for (const row of rows.slice(1)) {
    const stock = String(cell(row, 'stock') ?? '').trim();
    if (!stock) continue;
    vehicles.push({
      stockNumber: stock.toUpperCase(),
      model: String(cell(row, 'model') ?? '').trim(),
      color: String(cell(row, 'color') ?? '').trim(),
      odometer: toInt(cell(row, 'odometer')),
      vin8: String(cell(row, 'vin8') ?? '').trim(),
      age: toInt(cell(row, 'age')),
      listPrice: toFloat(cell(row, 'listPrice')),
      salesCost: toFloat(cell(row, 'salesCost')),
      msrp: toFloat(cell(row, 'msrp')),
    });
  }
  return vehicles;
}

module.exports = { parseInventory, parseVauto, baseStockNumber, toInt, toFloat };
