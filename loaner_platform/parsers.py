"""Parsers for the three input files.

All parsers locate columns by header name rather than position, so column
reordering in future exports won't break the pipeline.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from .models import InventoryUnit, ModelProgram, RateBook, VAutoVehicle


def _norm(value) -> str:
    return str(value).strip().lower() if value is not None else ""


def _to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(round(float(str(value).replace(",", ""))))
    except (TypeError, ValueError):
        return None


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _header_map(headers: list, wanted: dict[str, list[str]]) -> dict[str, int]:
    """Map logical field name -> column index by fuzzy header match."""
    normed = [_norm(h) for h in headers]
    out: dict[str, int] = {}
    for field_name, candidates in wanted.items():
        for cand in candidates:
            if cand in normed:
                out[field_name] = normed.index(cand)
                break
    return out


# ---------------------------------------------------------------------------
# 1. TSD Full Inventory Report (.xlsx) — source of truth for current miles
# ---------------------------------------------------------------------------

def parse_inventory(path: str | Path) -> dict[str, InventoryUnit]:
    """Return {unit_number: InventoryUnit} from the fleet software export."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    headers = next(rows)
    cols = _header_map(list(headers), {
        "unit": ["unit #", "unit#", "unit", "stock #", "stock#"],
        "vin": ["vin"],
        "year": ["year"],
        "model": ["model"],
        "miles": ["miles", "odometer", "current miles"],
        "status": ["status"],
        "last_used": ["last used"],
        "subsidy": ["subsidy status"],
    })
    if "unit" not in cols or "miles" not in cols:
        raise ValueError(
            f"Inventory report is missing a Unit #/Miles column. Found headers: {list(headers)}"
        )

    units: dict[str, InventoryUnit] = {}
    for row in rows:
        unit_no = str(row[cols["unit"]] or "").strip()
        if not unit_no:
            continue
        last_used = row[cols["last_used"]] if "last_used" in cols else None
        units[unit_no.upper()] = InventoryUnit(
            unit_number=unit_no,
            vin=str(row[cols["vin"]] or "") if "vin" in cols else "",
            year=_to_int(row[cols["year"]]) if "year" in cols else None,
            model=str(row[cols["model"]] or "") if "model" in cols else "",
            miles=_to_int(row[cols["miles"]]),
            status=str(row[cols["status"]] or "") if "status" in cols else "",
            last_used=last_used if isinstance(last_used, datetime) else None,
            subsidy_status=str(row[cols["subsidy"]] or "") if "subsidy" in cols else "",
        )
    wb.close()
    return units


# ---------------------------------------------------------------------------
# 2. vAuto Payment Calculator export (.xls or .xlsx) — the loaner list
# ---------------------------------------------------------------------------

_VAUTO_COLUMNS = {
    "stock": ["stock #", "stock#", "stock"],
    "model": ["model"],
    "color": ["color", "exterior color"],
    "odometer": ["odometer", "miles"],
    "vin8": ["vin 8", "vin8", "vin"],
    "age": ["age"],
    "list_price": ["list price"],
    "sales_cost": ["sales cost", "cost"],
    "msrp": ["msrp"],
}


def parse_vauto(path: str | Path) -> list[VAutoVehicle]:
    """Return every vehicle row from the vAuto export, in file order."""
    path = Path(path)
    if path.suffix.lower() == ".xls":
        raw = _read_xls_rows(path)
    else:
        raw = _read_xlsx_rows(path)
    if not raw:
        return []

    headers = raw[0]
    cols = _header_map(headers, _VAUTO_COLUMNS)
    missing = {"stock", "model", "msrp"} - set(cols)
    if missing:
        raise ValueError(
            f"vAuto export is missing columns {sorted(missing)}. Found headers: {headers}"
        )

    def cell(row, key):
        idx = cols.get(key)
        return row[idx] if idx is not None and idx < len(row) else None

    vehicles = []
    for row in raw[1:]:
        stock = str(cell(row, "stock") or "").strip()
        if not stock:
            continue
        vehicles.append(VAutoVehicle(
            stock_number=stock.upper(),
            model=str(cell(row, "model") or "").strip(),
            color=str(cell(row, "color") or "").strip(),
            odometer=_to_int(cell(row, "odometer")),
            vin8=str(cell(row, "vin8") or "").strip(),
            age=_to_int(cell(row, "age")),
            list_price=_to_float(cell(row, "list_price")),
            sales_cost=_to_float(cell(row, "sales_cost")),
            msrp=_to_float(cell(row, "msrp")),
        ))
    return vehicles


def _read_xls_rows(path: Path) -> list[list]:
    import xlrd

    book = xlrd.open_workbook(str(path))
    sheet = book.sheet_by_index(0)
    return [[sheet.cell_value(r, c) for c in range(sheet.ncols)]
            for r in range(sheet.nrows)]


def _read_xlsx_rows(path: Path) -> list[list]:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


# ---------------------------------------------------------------------------
# 3. Simple Calculator workbook (.xlsx) — rates, residuals, programs
# ---------------------------------------------------------------------------

RATES_SHEET = "Rates and Residuals"
PRIMARY_SHEET = "Primary"


def parse_ratebook(path: str | Path) -> RateBook:
    """Read lease programs, the mileage discount chart, and config values."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    if RATES_SHEET not in wb.sheetnames:
        raise ValueError(
            f"Calculator workbook has no '{RATES_SHEET}' sheet. Sheets: {wb.sheetnames}"
        )
    ws = wb[RATES_SHEET]

    # Model programs live in A2:I155 (the 'Rates' named range).
    programs: dict[str, ModelProgram] = {}
    for row in ws.iter_rows(min_row=2, max_row=200, min_col=1, max_col=9, values_only=True):
        model, money_factor, residual = row[0], row[1], row[2]
        if not model or _to_float(money_factor) is None or _to_float(residual) is None:
            continue
        model = str(model).strip()
        programs[model] = ModelProgram(
            model=model,
            money_factor=float(money_factor),
            residual_pct=float(residual),
            lease_incentive=_to_float(row[3]) or 0.0,
            lease_39_month=_norm(row[8]) == "y",
        )

    discount_chart = _parse_discount_chart(wb, ws)
    avp_min_miles = _to_int(ws["M3"].value)
    program_limit = _to_int(ws["M7"].value)

    dealership = "BMW/MINI of Pittsburgh"
    program_date: date | None = None
    if PRIMARY_SHEET in wb.sheetnames:
        primary = wb[PRIMARY_SHEET]
        if primary["D2"].value:
            dealership = str(primary["D2"].value).strip()
        c2 = primary["C2"].value
        if isinstance(c2, datetime):
            program_date = c2.date()
        elif isinstance(c2, date):
            program_date = c2
    wb.close()

    return RateBook(
        programs=programs,
        discount_chart=discount_chart,
        avp_min_miles=avp_min_miles if avp_min_miles is not None else -1,
        program_mileage_limit=program_limit if program_limit is not None else 15500,
        dealership=dealership,
        program_date=program_date,
    )


def _parse_discount_chart(wb, ws) -> list[tuple[int, float]]:
    """Read the mileage discount chart, preferring the Discount_Chart named range."""
    cells = None
    defined = wb.defined_names.get("Discount_Chart") if hasattr(wb.defined_names, "get") else None
    if defined is not None:
        try:
            dests = list(defined.destinations)
            sheet_name, ref = dests[0]
            cells = wb[sheet_name][ref]
        except (KeyError, IndexError, ValueError):
            cells = None
    if cells is None:
        cells = ws["J12:K19"]

    chart: list[tuple[int, float]] = []
    for row in cells:
        miles = _to_int(row[0].value)
        amount = _to_float(row[1].value)
        if miles is not None and amount is not None:
            chart.append((miles, amount))
    chart.sort(key=lambda t: t[0])
    if not chart:
        raise ValueError("Could not read the mileage Discount Chart from the calculator workbook.")
    return chart


_STOCK_SUFFIX = re.compile(r"[A-Z]+$")


def base_stock_number(stock: str) -> str:
    """PB3626R -> PB3626, so TSD units match vAuto stocks with letter suffixes."""
    stock = stock.strip().upper()
    match = re.match(r"^([A-Z]+\d+)", stock)
    return match.group(1) if match else stock
