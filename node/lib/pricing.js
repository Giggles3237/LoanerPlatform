// Pricing engine — port of the Python loaner_platform.pricing module,
// itself a verified port of the dealership's Simple Calculator 'Primary'
// sheet. Any change here must keep test/engine.test.js green: it replays
// every row of the original workbook and the payments must match exactly.

// Excel ROUND: half away from zero (JS Math.round differs for negatives).
function excelRound(value, digits = 0) {
  const factor = 10 ** digits;
  return (Math.sign(value) * Math.floor(Math.abs(value) * factor + 0.5)) / factor;
}

// Excel VLOOKUP approximate match: largest breakpoint <= miles.
function mileageDiscount(chart, miles) {
  let discount = 0;
  for (const [minMiles, amount] of chart) {
    if (miles >= minMiles) discount = amount;
    else break;
  }
  return discount;
}

function lookupProgram(settings, model) {
  const wanted = (model || '').trim();
  let program = settings.programs.find(p => p.model === wanted);
  if (!program && wanted.toLowerCase().endsWith(' base')) {
    // vAuto sometimes appends the trim ("2026 MINI Cooper S Base");
    // the rate sheet lists the model without it.
    const stripped = wanted.slice(0, -' base'.length).trim();
    program = settings.programs.find(p => p.model === stripped);
  }
  return program || null;
}

/**
 * Price one loaner.
 * vehicle: { stockNumber, model, color, odometer, vin8, age, listPrice, salesCost, msrp }
 * settings: the ratebook settings object (see seed/default_settings.json)
 * tsdMiles: current miles from the fleet inventory report, if the unit is active
 */
function priceUnit(vehicle, settings, { miles = null, tsdMiles = null } = {}) {
  const candidates = [vehicle.odometer, tsdMiles].filter(m => m !== null && m !== undefined);
  const usedMiles = miles !== null ? miles : (candidates.length ? Math.max(...candidates) : 0);

  const unit = {
    stockNumber: vehicle.stockNumber,
    model: vehicle.model,
    color: vehicle.color,
    odometer: usedMiles,
    vautoOdometer: vehicle.odometer ?? null,
    tsdMiles: tsdMiles ?? null,
    msrp: vehicle.msrp ?? null,
    listPrice: vehicle.listPrice ?? null,
    salesCost: vehicle.salesCost ?? null,
    invoice: null, avp: null, mileageAdj: null, salePrice: null,
    term: null, moneyFactor: null, residualPct: null, residualAmount: null,
    incentiveEligible: false, leaseIncentive: 0,
    depreciation: null, rent: null, leasePayment: null, dueAtSigning: null,
    profit: null,
    status: 'ok',
    inActiveFleet: tsdMiles !== null && tsdMiles !== undefined,
    mileageUpdated: tsdMiles != null && vehicle.odometer != null && tsdMiles > vehicle.odometer,
    warnings: [],
  };

  if (unit.listPrice !== null && unit.salesCost !== null) {
    unit.profit = unit.listPrice - unit.salesCost;
  }

  if (unit.msrp === null || unit.msrp === undefined) {
    unit.msrp = null;
    unit.status = 'no_msrp';
    unit.warnings.push('No MSRP in vAuto export — cannot price.');
    return unit;
  }

  unit.invoice = unit.msrp * (
    usedMiles < settings.invoice_mileage_break
      ? settings.invoice_pct_under_break
      : settings.invoice_pct_over_break
  );
  unit.avp = usedMiles > settings.avp_min_miles
    ? (unit.msrp - settings.avp_base_deduction) * settings.avp_pct - settings.avp_flat_credit
    : 0;
  unit.mileageAdj = mileageDiscount(settings.discount_chart, usedMiles);

  const computed = settings.invoice_markup + unit.invoice - unit.avp - unit.mileageAdj;
  if (unit.listPrice !== null) {
    unit.salePrice = Math.min(computed, unit.listPrice);
  } else {
    unit.salePrice = computed;
    unit.warnings.push('No List Price — sale price not capped at list.');
  }

  const program = lookupProgram(settings, vehicle.model);
  if (!program) {
    unit.status = 'no_program';
    unit.warnings.push(`Model '${vehicle.model}' not found on the rate sheet.`);
    return unit;
  }

  unit.term = program.lease_39_month ? 39 : 36;
  unit.moneyFactor = program.money_factor;
  unit.residualPct = program.residual_pct;
  unit.leaseIncentive = program.lease_incentive || 0;
  unit.incentiveEligible = usedMiles < settings.program_mileage_limit;

  if (usedMiles >= settings.program_mileage_limit) {
    unit.status = 'over_miles';
    unit.warnings.push(
      `${usedMiles.toLocaleString()} miles exceeds the ` +
      `${settings.program_mileage_limit.toLocaleString()}-mile program limit.`);
    return unit;
  }

  unit.residualAmount = unit.msrp * unit.residualPct
    - (usedMiles - settings.residual_free_miles) * settings.residual_mile_charge;
  const incentive = unit.incentiveEligible ? unit.leaseIncentive : 0;
  unit.depreciation = unit.salePrice - unit.residualAmount - incentive;
  unit.rent = (unit.salePrice + unit.residualAmount) * unit.moneyFactor * unit.term;
  unit.leasePayment = excelRound((unit.depreciation + unit.rent) / unit.term);
  unit.dueAtSigning = unit.leasePayment + settings.acquisition_fee;
  unit.disclosure = buildDisclosure(unit, settings);
  return unit;
}

function money(value) {
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : String(rounded);
}

function buildDisclosure(unit, settings) {
  const dateText = settings.program_date
    ? `${settings.program_date.slice(5, 7)}/${settings.program_date.slice(8, 10)}/${settings.program_date.slice(0, 4)}`
    : '';
  const dealer = settings.dealership;
  return (
    `Lease financing available from ${dealer} through BMW/MINI Financial Services ` +
    `through ${dateText}. Monthly lease payments of $${unit.leasePayment} per month ` +
    `for ${unit.term} months based on MSRP of $${money(unit.msrp)}. ` +
    `$${money(unit.dueAtSigning)} cash due at signing is based on $0 down payment, ` +
    `$${unit.leasePayment} first month payment, $${money(settings.acquisition_fee)} ` +
    `acquisition fee, and $0 security deposit (not all customers will qualify for ` +
    `security deposit waiver). Tax, title, license, registration and dealer fees ` +
    `are additional fees due at signing. ${dealer} retired courtesy car with ` +
    `${unit.odometer} miles. Stock #${unit.stockNumber}. Program available to ` +
    `eligible, qualified customers with excellent credit history who meet credit ` +
    `requirements. Payments do not include applicable taxes. Lessee responsible ` +
    `for insurance during the lease term and any excess wear and tear as defined ` +
    `in the lease contract, $${settings.excess_mileage_rate}/mile over ` +
    `${settings.annual_mileage_allowance.toLocaleString()} miles per year and a ` +
    `disposition fee of $${money(settings.disposition_fee)} at lease end. ` +
    `Purchase option at lease end (excluding tax, title and government fees) is ` +
    `$${money(unit.residualAmount)}. Visit ${dealer} for important details.`
  );
}

module.exports = { excelRound, mileageDiscount, lookupProgram, priceUnit };
