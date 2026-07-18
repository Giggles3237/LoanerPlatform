"""Data models shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class InventoryUnit:
    """A row from the TSD Full Inventory Report (active loaner fleet)."""

    unit_number: str
    vin: str = ""
    year: int | None = None
    model: str = ""
    miles: int | None = None
    status: str = ""
    last_used: datetime | None = None
    subsidy_status: str = ""


@dataclass
class VAutoVehicle:
    """A row from the vAuto Payment Calculator export (incl. retired units)."""

    stock_number: str
    model: str
    color: str
    odometer: int | None
    vin8: str
    age: int | None
    list_price: float | None
    sales_cost: float | None
    msrp: float | None


@dataclass
class ModelProgram:
    """Lease program terms for one model, from 'Rates and Residuals'."""

    model: str
    money_factor: float
    residual_pct: float
    lease_incentive: float = 0.0
    lease_39_month: bool = False


@dataclass
class RateBook:
    """Everything parsed from the Simple Calculator workbook."""

    programs: dict[str, ModelProgram]
    # Sorted (min_miles, discount) breakpoints; VLOOKUP-style range match.
    discount_chart: list[tuple[int, float]]
    avp_min_miles: int = -1          # 'Mileage for AVP Discount' (M3)
    program_mileage_limit: int = 15500  # 'Mileage Limit for programs' (M7)
    dealership: str = "BMW/MINI of Pittsburgh"
    program_date: date | None = None  # Primary!C2 — programs valid through
    invoice_markup: float = 1000.0    # hardcoded '1000 +' in Sale Price formula
    acquisition_fee: float = 925.0
    disposition_fee: float = 495.0
    excess_mileage_rate: float = 0.25
    annual_mileage_allowance: int = 10000

    def lookup_program(self, model: str) -> ModelProgram | None:
        model = model.strip()
        program = self.programs.get(model)
        if program is None and model.lower().endswith(" base"):
            # vAuto sometimes appends the trim ("2026 MINI Cooper S Base");
            # the rates sheet lists the model without it.
            program = self.programs.get(model[: -len(" base")].strip())
        return program

    def mileage_discount(self, miles: int) -> float:
        """Excel VLOOKUP approximate match: largest breakpoint <= miles."""
        discount = 0.0
        for min_miles, amount in self.discount_chart:
            if miles >= min_miles:
                discount = amount
            else:
                break
        return discount


@dataclass
class PricedUnit:
    """A fully priced loaner ready for the report."""

    stock_number: str
    model: str
    color: str
    odometer: int              # miles used for pricing (greater of the two)
    vauto_odometer: int | None
    tsd_miles: int | None
    msrp: float | None
    list_price: float | None
    sales_cost: float | None

    invoice: float | None = None
    avp: float | None = None
    mileage_adj: float | None = None
    sale_price: float | None = None
    term: int | None = None
    money_factor: float | None = None
    residual_pct: float | None = None
    residual_amount: float | None = None
    incentive_eligible: bool = False
    lease_incentive: float = 0.0
    depreciation: float | None = None
    rent: float | None = None
    lease_payment: int | None = None
    due_at_signing: float | None = None
    profit: float | None = None

    status: str = "ok"          # ok | over_miles | no_program | no_msrp
    in_active_fleet: bool = False
    mileage_updated: bool = False  # TSD miles exceeded the vAuto odometer
    disclosure: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def priced(self) -> bool:
        return self.status == "ok" and self.lease_payment is not None
