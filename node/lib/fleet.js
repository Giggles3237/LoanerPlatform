// Fleet orchestration: merge the two exports and price every loaner.
// Port of loaner_platform/fleet.py.

const { baseStockNumber } = require('./parsers');
const { priceUnit } = require('./pricing');

function tsdMilesFor(stock, inventory) {
  const unit = inventory.get(stock) || inventory.get(baseStockNumber(stock));
  return unit ? unit.miles : null;
}

/**
 * inventory: Map from parseInventory; vauto: array from parseVauto;
 * settings: ratebook settings object.
 */
function processFleet(inventory, vauto, settings) {
  // vAuto exports occasionally repeat a stock number; keep the row with the
  // higher odometer so the sheet never understates mileage.
  const deduped = new Map();
  for (const vehicle of vauto) {
    const existing = deduped.get(vehicle.stockNumber);
    if (!existing || (vehicle.odometer || 0) > (existing.odometer || 0)) {
      deduped.set(vehicle.stockNumber, vehicle);
    }
  }
  const duplicatesRemoved = vauto.length - deduped.size;

  const units = [...deduped.values()].map(v =>
    priceUnit(v, settings, { tsdMiles: tsdMilesFor(v.stockNumber, inventory) }));
  units.sort((a, b) =>
    a.model.toUpperCase().localeCompare(b.model.toUpperCase())
    || a.stockNumber.localeCompare(b.stockNumber));

  const seen = new Set([...deduped.keys()].map(baseStockNumber));
  const missingFromVauto = [...inventory.entries()]
    .filter(([stock]) => !seen.has(baseStockNumber(stock)))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, inv]) => inv);

  return {
    units,
    duplicatesRemoved,
    missingFromVauto,
    priced: units.filter(u => u.status === 'ok' && u.leasePayment !== null),
    needsAttention: units.filter(u => !(u.status === 'ok' && u.leasePayment !== null)),
    mileageUpdates: units.filter(u => u.mileageUpdated),
  };
}

module.exports = { processFleet };
