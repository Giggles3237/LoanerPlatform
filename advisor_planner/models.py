"""Data shapes for the advisor task planner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass
class Lead:
    """One VinSolutions lead (showroom visit, phone-up, internet lead)."""
    rep: str
    customer: str
    status: str
    source: str
    lead_type: str
    year: str
    make: str
    model: str
    created: date | None
    note: str = ""
    phone: str = ""
    email: str = ""

    @property
    def vehicle(self) -> str:
        return " ".join(x for x in (self.year, self.make, self.model) if x)


@dataclass
class FSAccount:
    """One BMW Financial Services contract from Infobahn."""
    customer: str
    cosigner: str
    phones: list[str]
    email: str
    in_market_tier: str
    contract_date: date | None
    maturity: date | None
    contract_type: str
    contract_miles: float | None
    payment: float | None
    equity: float | None
    vin: str
    year: str
    vehicle: str
    odometer: float | None
    last_service: date | None
    advisor: str
    warranty_type: str
    warranty_status: str
    warranty_expires: date | None
    service_contract: str

    @property
    def is_lease(self) -> bool:
        return "lease" in self.contract_type.lower() and "to retail" not in self.contract_type.lower()

    @property
    def description(self) -> str:
        return " ".join(x for x in (self.year, self.vehicle) if x)


@dataclass
class MastermindRecord:
    """One Mastermind equity-mining row."""
    customer: str
    cobuyer: str
    phones: list[str]
    email: str
    email_ok: bool
    household_demand: bool
    vin: str
    year: str
    make: str
    model: str
    trim: str
    lease_mileage_status: str
    warranty_months_left: int | None
    assignee: str
    status: str
    sub_status: str
    original_salesperson: str
    vehicle_type: str
    contract_end: date | None
    deal_type: str
    payment: float | None
    payment_difference: float | None
    trade_equity: float | None
    months_owned: int | None
    new_vehicle: str
    new_payment: float | None

    @property
    def description(self) -> str:
        return " ".join(x for x in (self.year, self.make, self.trim or self.model) if x)


@dataclass
class Task:
    """One customer to work this week, possibly flagged by several rules."""
    key: str
    customer: str
    phones: list[str] = field(default_factory=list)
    email: str = ""
    do_not_email: bool = False
    vehicle: str = ""
    reasons: list[dict] = field(default_factory=list)  # {rule, label, detail, score, source}
    score: float = 0.0
    owner: str = ""            # roster advisor this customer belongs to ('' = unowned)
    owner_basis: str = ""      # e.g. 'VinSolutions sales rep', 'Infobahn client advisor'
    previous_owner: str = ""   # raw owner name when the customer is unowned
    advisor: str = ""          # who gets the task this week
    day: str = ""
    reassigned: bool = False

    @property
    def primary(self) -> dict:
        return max(self.reasons, key=lambda r: r["score"])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(**data)
