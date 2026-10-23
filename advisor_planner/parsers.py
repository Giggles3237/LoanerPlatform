"""Readers for the three planner inputs.

Every reader sniffs the real file format first (the Infobahn ".xls" is an
HTML table; a future export might be a true .xls or .xlsx) and then locates
columns by header name, so reordered or relabelled exports keep working.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from .models import FSAccount, Lead, MastermindRecord


# ---------------------------------------------------------------------------
# Generic table loading
# ---------------------------------------------------------------------------

class _TableParser(HTMLParser):
    """Collect the rows of the first HTML <table> as lists of cell text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell).replace("\xa0", " ").strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def read_table(path: str | Path) -> list[list]:
    """Return every row of the first sheet/table, whatever the file really is."""
    path = Path(path)
    head = path.read_bytes()[:8]
    if head.startswith(b"PK"):
        import openpyxl

        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        rows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
        wb.close()
        return rows
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        import xlrd

        sheet = xlrd.open_workbook(str(path)).sheet_by_index(0)
        return [sheet.row_values(i) for i in range(sheet.nrows)]
    text = path.read_bytes().decode("utf-8", errors="replace")
    if "<table" in text[:5000].lower() or "<tr" in text[:5000].lower():
        parser = _TableParser()
        parser.feed(text)
        return parser.rows
    import csv
    import io

    return [row for row in csv.reader(io.StringIO(text))]


def _norm(value) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().lower() if value is not None else ""


def _header_map(headers: list, wanted: dict[str, list[str]]) -> dict[str, int]:
    """Map logical field name -> column index by header match."""
    normed = [_norm(h) for h in headers]
    out: dict[str, int] = {}
    for field_name, candidates in wanted.items():
        for cand in candidates:
            if cand in normed:
                out[field_name] = normed.index(cand)
                break
    return out


def _find_header_row(rows: list[list], must_have: str) -> int:
    for i, row in enumerate(rows[:25]):
        if must_have in [_norm(c) for c in row]:
            return i
    raise ValueError(f"Could not find a header row containing '{must_have}'.")


def _cell(row: list, cols: dict[str, int], name: str):
    idx = cols.get(name)
    if idx is None or idx >= len(row):
        return None
    return row[idx]


_BLANKS = {"", "n/a", "unknown", "(empty string)", "none", "nan"}


def clean(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # spreadsheet numbers: model "540", not "540.0"
    text = re.sub(r"\s+", " ", str(value)).strip() if value is not None else ""
    return "" if text.lower() in _BLANKS else text


def to_float(value) -> float | None:
    text = clean(value)
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.replace("$", "").replace(",", "").replace("%", "").strip("()")
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def to_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean(value)
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %I:%M %p"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def phone(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10 or set(digits) == {"0"}:
        return ""
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def _year(value) -> str:
    number = to_float(value)
    return str(int(number)) if number else ""


# ---------------------------------------------------------------------------
# 1. VinSolutions lead / showroom report
# ---------------------------------------------------------------------------

_LEAD_TYPES = {"internet", "phone", "walk-in", "walk in", "walkin", "email", "chat", "text"}
_LEAD_STATUSES = {"active", "sold", "lost", "bad", "inactive", "duplicate", "closed", "pending"}


def parse_vinsolutions(path: str | Path) -> list[Lead]:
    """Leads grouped under 'Sales Rep' header rows (or with the rep on every row).

    The export's 'Lead Source' / 'Lead Type' / 'Lead Status' headers sit one
    column off from their data, so those three columns are identified by
    their contents instead of their labels.
    """
    rows = read_table(path)
    h = _find_header_row(rows, "customer")
    headers = rows[h]
    cols = _header_map(headers, {
        "rep": ["sales rep", "salesperson", "sales person", "user"],
        "customer": ["customer", "customer name"],
        "year": ["year"],
        "make": ["make"],
        "model": ["model"],
        "date": ["lead origination date", "origination date", "created", "lead date", "date"],
        "note": ["customer note", "note", "notes"],
        "phone": ["phone", "cell phone", "home phone", "customer phone"],
        "email": ["email", "customer email"],
    })
    if "customer" not in cols:
        raise ValueError(f"VinSolutions report has no Customer column. Headers: {headers}")
    data = rows[h + 1:]

    lead_cols = [i for i, name in enumerate(headers)
                 if _norm(name) in ("lead source", "lead type", "lead status")]
    roles: dict[str, int] = {}
    for i in lead_cols:
        values = [_norm(r[i]) for r in data if i < len(r) and clean(r[i])]
        if not values:
            continue
        type_share = sum(v in _LEAD_TYPES for v in values) / len(values)
        status_share = sum(v in _LEAD_STATUSES for v in values) / len(values)
        if status_share > 0.6 and "status" not in roles:
            roles["status"] = i
        elif type_share > 0.6 and "type" not in roles:
            roles["type"] = i
    leftover = [i for i in lead_cols if i not in roles.values()]
    if leftover:
        roles["source"] = leftover[0]
    cols.update(roles)

    leads: list[Lead] = []
    current_rep = ""
    for row in data:
        rep = clean(_cell(row, cols, "rep"))
        customer = clean(_cell(row, cols, "customer"))
        if rep:
            current_rep = rep
        if not customer:
            continue
        leads.append(Lead(
            rep=current_rep,
            customer=customer,
            status=clean(_cell(row, cols, "status")),
            source=clean(_cell(row, cols, "source")),
            lead_type=clean(_cell(row, cols, "type")),
            year=_year(_cell(row, cols, "year")),
            make=clean(_cell(row, cols, "make")),
            model=clean(_cell(row, cols, "model")),
            created=to_date(_cell(row, cols, "date")),
            note=clean(_cell(row, cols, "note")),
            phone=phone(_cell(row, cols, "phone")),
            email=clean(_cell(row, cols, "email")),
        ))
    if not leads:
        raise ValueError("No leads found in the VinSolutions report.")
    return leads


# ---------------------------------------------------------------------------
# 2. Infobahn (BMW Financial Services portfolio)
# ---------------------------------------------------------------------------

def parse_infobahn(path: str | Path) -> list[FSAccount]:
    rows = read_table(path)
    h = _find_header_row(rows, "vin")
    headers = rows[h]
    cols = _header_map(headers, {
        "last": ["last/company name", "last name"],
        "first": ["first name"],
        "cosigner": ["co-signer"],
        "home": ["home phone"],
        "work": ["work phone"],
        "cell": ["cell phone", "mobile phone"],
        "email": ["email"],
        "tier": ["in market tier"],
        "maturity": ["maturity date"],
        "contract_date": ["contract date"],
        "contract_type": ["contract type"],
        "contract_miles": ["contract miles"],
        "payment": ["monthly payment"],
        "equity": ["estimated equity"],
        "vin": ["vin"],
        "year": ["year"],
        "vehicle": ["make & model", "make and model"],
        "odometer": ["last service odometer"],
        "last_service": ["last service date"],
        "advisor": ["client advisor"],
        "status": ["account status"],
        "warranty_type": ["warranty type"],
        "warranty_status": ["warranty status"],
        "warranty_exp": ["warranty expiration date"],
        "service_contract": ["service contract"],
    })
    for required in ("vin", "maturity", "advisor"):
        if required not in cols:
            raise ValueError(f"Infobahn export is missing '{required}'. Headers: {headers}")

    accounts = []
    for row in rows[h + 1:]:
        vin = clean(_cell(row, cols, "vin")).upper()
        if not vin:
            continue
        status = clean(_cell(row, cols, "status"))
        if status and status.lower() != "active":
            continue
        first, last = clean(_cell(row, cols, "first")), clean(_cell(row, cols, "last"))
        phones = [phone(_cell(row, cols, k)) for k in ("cell", "home", "work")]
        accounts.append(FSAccount(
            customer=f"{first} {last}".strip(),
            cosigner=clean(_cell(row, cols, "cosigner")),
            phones=[p for p in dict.fromkeys(phones) if p],
            email=clean(_cell(row, cols, "email")),
            in_market_tier=clean(_cell(row, cols, "tier")),
            contract_date=to_date(_cell(row, cols, "contract_date")),
            maturity=to_date(_cell(row, cols, "maturity")),
            contract_type=clean(_cell(row, cols, "contract_type")),
            contract_miles=to_float(_cell(row, cols, "contract_miles")),
            payment=to_float(_cell(row, cols, "payment")),
            equity=to_float(_cell(row, cols, "equity")),
            vin=vin,
            year=_year(_cell(row, cols, "year")),
            vehicle=clean(_cell(row, cols, "vehicle")),
            odometer=to_float(_cell(row, cols, "odometer")),
            last_service=to_date(_cell(row, cols, "last_service")),
            advisor=clean(_cell(row, cols, "advisor")),
            warranty_type=clean(_cell(row, cols, "warranty_type")),
            warranty_status=clean(_cell(row, cols, "warranty_status")),
            warranty_expires=to_date(_cell(row, cols, "warranty_exp")),
            service_contract=clean(_cell(row, cols, "service_contract")),
        ))
    if not accounts:
        raise ValueError("No accounts found in the Infobahn export.")
    return accounts


# ---------------------------------------------------------------------------
# 3. Mastermind equity-mining export
# ---------------------------------------------------------------------------

def _months(value) -> int | None:
    """'14 months' -> 14; anything else (Good Standing, Expired, ...) -> None."""
    match = re.match(r"\s*(\d+)\s*months?", str(value or ""), re.I)
    return int(match.group(1)) if match else None


def parse_mastermind(path: str | Path) -> list[MastermindRecord]:
    rows = read_table(path)
    h = _find_header_row(rows, "vin")
    headers = rows[h]
    cols = _header_map(headers, {
        "customer": ["customer name"],
        "cobuyer": ["co-buyer name"],
        "email": ["customer email"],
        "office": ["phone office"],
        "home": ["phone home"],
        "cell": ["cell phone"],
        "email_flag": ["do not email until date"],
        "household": ["household demand indicator"],
        "vin": ["vin"],
        "year": ["current vehicle year"],
        "make": ["current make"],
        "model": ["current vehicle model"],
        "trim": ["current vehicle trim"],
        "lease_miles": ["lease mileage status"],
        "warranty": ["warranty status"],
        "assignee": ["assignee"],
        "status": ["sales status"],
        "sub_status": ["sub status"],
        "original": ["original sales person"],
        "vehicle_type": ["current vehicle type"],
        "contract_end": ["current contract end date"],
        "deal_type": ["current deal type"],
        "payment": ["current vehicle monthly payment"],
        "payment_diff": ["payment difference"],
        "trade_equity": ["trade equity"],
        "months_owned": ["months of ownership"],
        "new_year": ["new vehicle year"],
        "new_make": ["new vehicle make"],
        "new_model": ["new vehicle model"],
        "new_trim": ["new vehicle trim"],
        "new_payment": ["new vehicle monthly payment"],
    })
    for required in ("customer", "vin", "assignee"):
        if required not in cols:
            raise ValueError(f"Mastermind export is missing '{required}'. Headers: {headers}")

    records = []
    for row in rows[h + 1:]:
        customer = clean(_cell(row, cols, "customer"))
        phones = [phone(_cell(row, cols, k)) for k in ("cell", "home", "office")]
        email = clean(_cell(row, cols, "email"))
        if not customer:
            if not (any(phones) or email):
                continue  # nobody to contact
            customer = f"(No name) {email}".strip()
        months_owned = to_float(_cell(row, cols, "months_owned"))
        records.append(MastermindRecord(
            customer=customer,
            cobuyer=clean(_cell(row, cols, "cobuyer")),
            phones=[p for p in dict.fromkeys(phones) if p],
            email=email,
            email_ok=_norm(_cell(row, cols, "email_flag")) != "email is disabled",
            household_demand=_norm(_cell(row, cols, "household")) == "true",
            vin=clean(_cell(row, cols, "vin")).upper(),
            year=_year(_cell(row, cols, "year")),
            make=clean(_cell(row, cols, "make")),
            model=clean(_cell(row, cols, "model")),
            trim=clean(_cell(row, cols, "trim")),
            lease_mileage_status=clean(_cell(row, cols, "lease_miles")),
            warranty_months_left=_months(_cell(row, cols, "warranty")),
            assignee=clean(_cell(row, cols, "assignee")),
            status=clean(_cell(row, cols, "status")),
            sub_status=clean(_cell(row, cols, "sub_status")),
            original_salesperson=clean(_cell(row, cols, "original")),
            vehicle_type=clean(_cell(row, cols, "vehicle_type")),
            contract_end=to_date(_cell(row, cols, "contract_end")),
            deal_type=clean(_cell(row, cols, "deal_type")),
            payment=to_float(_cell(row, cols, "payment")),
            payment_difference=to_float(_cell(row, cols, "payment_diff")),
            trade_equity=to_float(_cell(row, cols, "trade_equity")),
            months_owned=int(months_owned) if months_owned is not None else None,
            new_vehicle=" ".join(x for x in (
                _year(_cell(row, cols, "new_year")),
                clean(_cell(row, cols, "new_make")),
                clean(_cell(row, cols, "new_trim")) or clean(_cell(row, cols, "new_model")),
            ) if x),
            new_payment=to_float(_cell(row, cols, "new_payment")),
        ))
    if not records:
        raise ValueError("No customers found in the Mastermind export.")
    return records
