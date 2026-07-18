"""Pricing engine — a faithful port of the Simple Calculator 'Primary' sheet.

Formula sources (Simple_Calculator_2026.xlsx, table 'Primary'):

    Invoice      = MSRP * 0.96 if Odometer < 1000 else MSRP * 0.94
    AVP          = (MSRP - 995) * 0.05 - 300      if Odometer > M3 else 0
    Mileage Adj  = VLOOKUP(Odometer, Discount_Chart, 2)   [range match]
    Sale Price   = MIN(1000 + Invoice - AVP - Mileage Adj, List Price)
    Term         = 39 if model flagged '39 month lease' else 36
    Residual $   = MSRP * Residual% - (Odometer - 500) * 0.25
    Deprec       = Sale Price - Residual $ - Lease Incentive (if eligible)
    Rent         = (Sale Price + Residual $) * Money Factor * Term
    Lease        = ROUND((Deprec + Rent) / Term, 0)
    Profit       = List Price - Sales Cost
    Eligible     = Odometer < 15500 (program mileage limit)
"""

from __future__ import annotations

import math

from .models import PricedUnit, RateBook, VAutoVehicle

INVOICE_PCT_UNDER_1K = 0.96
INVOICE_PCT_OVER_1K = 0.94
INVOICE_MILEAGE_BREAK = 1000
AVP_BASE_DEDUCTION = 995.0
AVP_PCT = 0.05
AVP_FLAT_CREDIT = 300.0
RESIDUAL_MILE_CHARGE = 0.25
RESIDUAL_FREE_MILES = 500


def excel_round(value: float, digits: int = 0) -> float:
    """Excel ROUND: half away from zero (Python's round is banker's)."""
    factor = 10 ** digits
    return math.copysign(math.floor(abs(value) * factor + 0.5), value) / factor


def price_unit(
    vehicle: VAutoVehicle,
    ratebook: RateBook,
    miles: int | None = None,
    tsd_miles: int | None = None,
) -> PricedUnit:
    """Price one loaner. `miles` defaults to the greater of vAuto/TSD readings."""
    if miles is None:
        candidates = [m for m in (vehicle.odometer, tsd_miles) if m is not None]
        miles = max(candidates) if candidates else 0

    unit = PricedUnit(
        stock_number=vehicle.stock_number,
        model=vehicle.model,
        color=vehicle.color,
        odometer=miles,
        vauto_odometer=vehicle.odometer,
        tsd_miles=tsd_miles,
        msrp=vehicle.msrp,
        list_price=vehicle.list_price,
        sales_cost=vehicle.sales_cost,
        in_active_fleet=tsd_miles is not None,
        mileage_updated=(
            tsd_miles is not None
            and vehicle.odometer is not None
            and tsd_miles > vehicle.odometer
        ),
    )

    if vehicle.list_price is not None and vehicle.sales_cost is not None:
        unit.profit = vehicle.list_price - vehicle.sales_cost

    if unit.msrp is None:
        unit.status = "no_msrp"
        unit.warnings.append("No MSRP in vAuto export — cannot price.")
        return unit

    unit.invoice = unit.msrp * (
        INVOICE_PCT_UNDER_1K if miles < INVOICE_MILEAGE_BREAK else INVOICE_PCT_OVER_1K
    )
    unit.avp = (
        (unit.msrp - AVP_BASE_DEDUCTION) * AVP_PCT - AVP_FLAT_CREDIT
        if miles > ratebook.avp_min_miles
        else 0.0
    )
    unit.mileage_adj = ratebook.mileage_discount(miles)

    computed = ratebook.invoice_markup + unit.invoice - unit.avp - unit.mileage_adj
    if unit.list_price is not None:
        unit.sale_price = min(computed, unit.list_price)
    else:
        unit.sale_price = computed
        unit.warnings.append("No List Price — sale price not capped at list.")

    program = ratebook.lookup_program(vehicle.model)
    if program is None:
        unit.status = "no_program"
        unit.warnings.append(
            f"Model '{vehicle.model}' not found on the Rates and Residuals sheet."
        )
        return unit

    unit.term = 39 if program.lease_39_month else 36
    unit.money_factor = program.money_factor
    unit.residual_pct = program.residual_pct
    unit.lease_incentive = program.lease_incentive
    unit.incentive_eligible = miles < ratebook.program_mileage_limit

    if miles >= ratebook.program_mileage_limit:
        unit.status = "over_miles"
        unit.warnings.append(
            f"{miles:,} miles exceeds the {ratebook.program_mileage_limit:,}-mile program limit."
        )
        return unit

    unit.residual_amount = (
        unit.msrp * unit.residual_pct - (miles - RESIDUAL_FREE_MILES) * RESIDUAL_MILE_CHARGE
    )
    incentive = unit.lease_incentive if unit.incentive_eligible else 0.0
    unit.depreciation = unit.sale_price - unit.residual_amount - incentive
    unit.rent = (unit.sale_price + unit.residual_amount) * unit.money_factor * unit.term
    unit.lease_payment = int(excel_round((unit.depreciation + unit.rent) / unit.term))
    unit.due_at_signing = unit.lease_payment + ratebook.acquisition_fee
    unit.disclosure = build_disclosure(unit, ratebook)
    return unit


def build_disclosure(unit: PricedUnit, ratebook: RateBook) -> str:
    """Full legal disclosure, mirroring the Disclosure1–6 columns.

    The spreadsheet's Disclosure1 pulled the term text from a misaligned cell
    (it printed a model name where the month count belongs); here the actual
    term is used instead.
    """
    date_text = (
        ratebook.program_date.strftime("%m/%d/%Y") if ratebook.program_date else ""
    )
    dealer = ratebook.dealership
    residual_text = f"{round(unit.residual_amount or 0, 2):g}"
    return (
        f"Lease financing available from {dealer} through BMW/MINI Financial Services "
        f"through {date_text}. Monthly lease payments of ${unit.lease_payment} per month "
        f"for {unit.term} months based on MSRP of ${unit.msrp:g}. "
        f"${unit.due_at_signing:g} cash due at signing is based on $0 down payment, "
        f"${unit.lease_payment} first month payment, ${ratebook.acquisition_fee:g} "
        f"acquisition fee, and $0 security deposit (not all customers will qualify for "
        f"security deposit waiver). Tax, title, license, registration and dealer fees "
        f"are additional fees due at signing. {dealer} retired courtesy car with "
        f"{unit.odometer} miles. Stock #{unit.stock_number}. Program available to "
        f"eligible, qualified customers with excellent credit history who meet credit "
        f"requirements. Payments do not include applicable taxes. Lessee responsible "
        f"for insurance during the lease term and any excess wear and tear as defined "
        f"in the lease contract, ${ratebook.excess_mileage_rate}/mile over "
        f"{ratebook.annual_mileage_allowance:,} miles per year and a disposition fee "
        f"of ${ratebook.disposition_fee:g} at lease end. Purchase option at lease end "
        f"(excluding tax, title and government fees) is ${residual_text}. "
        f"Visit {dealer} for important details."
    )
