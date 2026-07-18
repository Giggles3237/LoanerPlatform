"""Fleet orchestration: merge the three inputs and price every loaner."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import InventoryUnit, PricedUnit, RateBook, VAutoVehicle
from .parsers import base_stock_number
from .pricing import price_unit


@dataclass
class FleetReport:
    units: list[PricedUnit]
    ratebook: RateBook
    duplicates_removed: int = 0
    # Active fleet units that never appeared in the vAuto export.
    missing_from_vauto: list[InventoryUnit] = field(default_factory=list)

    @property
    def priced(self) -> list[PricedUnit]:
        return [u for u in self.units if u.priced]

    @property
    def needs_attention(self) -> list[PricedUnit]:
        return [u for u in self.units if not u.priced]

    @property
    def mileage_updates(self) -> list[PricedUnit]:
        return [u for u in self.units if u.mileage_updated]


def _tsd_miles_for(stock: str, inventory: dict[str, InventoryUnit]) -> int | None:
    unit = inventory.get(stock) or inventory.get(base_stock_number(stock))
    return unit.miles if unit else None


def process_fleet(
    inventory: dict[str, InventoryUnit],
    vauto: list[VAutoVehicle],
    ratebook: RateBook,
) -> FleetReport:
    """Price the whole fleet using the greater of vAuto and TSD mileage."""
    # vAuto exports occasionally repeat a stock number; keep the row with the
    # higher odometer so the sheet never understates mileage.
    deduped: dict[str, VAutoVehicle] = {}
    for vehicle in vauto:
        existing = deduped.get(vehicle.stock_number)
        if existing is None or (vehicle.odometer or 0) > (existing.odometer or 0):
            deduped[vehicle.stock_number] = vehicle
    duplicates_removed = len(vauto) - len(deduped)

    units = [
        price_unit(v, ratebook, tsd_miles=_tsd_miles_for(v.stock_number, inventory))
        for v in deduped.values()
    ]
    units.sort(key=lambda u: (u.model.upper(), u.stock_number))

    seen_stocks = {base_stock_number(s) for s in deduped}
    missing = [
        inv for stock, inv in sorted(inventory.items())
        if base_stock_number(stock) not in seen_stocks
    ]

    return FleetReport(
        units=units,
        ratebook=ratebook,
        duplicates_removed=duplicates_removed,
        missing_from_vauto=missing,
    )
