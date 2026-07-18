"""Persistent pricing settings — the app's built-in 'Simple Calculator'.

The RateBook (model programs, discount chart, formula config) is stored as
JSON so admins can edit it in the web UI instead of maintaining the
spreadsheet. A bundled seed (default_settings.json, generated from the
dealership's Simple_Calculator_2026.xlsx) provides the starting values.

Storage location, in order of precedence:
    1. $SETTINGS_PATH if set (point it at a persistent disk when hosted)
    2. ./data/settings.json next to the working directory
"""

from __future__ import annotations

import json
import os
from dataclasses import fields
from datetime import date, datetime
from pathlib import Path

from .models import ModelProgram, RateBook

BUNDLED_DEFAULTS = Path(__file__).parent / "default_settings.json"

_SCALAR_FIELDS = [
    "dealership", "avp_min_miles", "program_mileage_limit", "invoice_markup",
    "acquisition_fee", "disposition_fee", "excess_mileage_rate",
    "annual_mileage_allowance", "invoice_pct_under_break",
    "invoice_pct_over_break", "invoice_mileage_break", "avp_base_deduction",
    "avp_pct", "avp_flat_credit", "residual_mile_charge", "residual_free_miles",
]


def ratebook_to_dict(rb: RateBook) -> dict:
    data = {name: getattr(rb, name) for name in _SCALAR_FIELDS}
    data["program_date"] = rb.program_date.isoformat() if rb.program_date else None
    data["discount_chart"] = [[m, a] for m, a in rb.discount_chart]
    data["programs"] = [
        {
            "model": p.model,
            "money_factor": p.money_factor,
            "residual_pct": p.residual_pct,
            "lease_incentive": p.lease_incentive,
            "lease_39_month": p.lease_39_month,
        }
        for p in rb.programs.values()
    ]
    return data


def ratebook_from_dict(data: dict) -> RateBook:
    programs = {}
    for p in data.get("programs", []):
        model = str(p["model"]).strip()
        if not model:
            continue
        programs[model] = ModelProgram(
            model=model,
            money_factor=float(p["money_factor"]),
            residual_pct=float(p["residual_pct"]),
            lease_incentive=float(p.get("lease_incentive") or 0.0),
            lease_39_month=bool(p.get("lease_39_month")),
        )
    chart = sorted((int(m), float(a)) for m, a in data.get("discount_chart", []))

    kwargs = {}
    valid = {f.name for f in fields(RateBook)}
    for name in _SCALAR_FIELDS:
        if name in data and data[name] is not None and name in valid:
            kwargs[name] = data[name]
    program_date = None
    if data.get("program_date"):
        program_date = datetime.strptime(str(data["program_date"])[:10], "%Y-%m-%d").date()
    return RateBook(programs=programs, discount_chart=chart,
                    program_date=program_date, **kwargs)


class ReportStore:
    """Persist the most recently generated sheet next to the settings file."""

    def __init__(self, base_dir: str | os.PathLike | None = None):
        if base_dir is None:
            settings_path = os.environ.get("SETTINGS_PATH", "data/settings.json")
            base_dir = Path(settings_path).parent
        base = Path(base_dir)
        self.html_path = base / "latest_sheet.html"
        self.meta_path = base / "latest_sheet.meta.json"

    def exists(self) -> bool:
        return self.html_path.is_file() and self.meta_path.is_file()

    def save(self, html: str, meta: dict) -> None:
        self.html_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.html_path.with_suffix(".tmp")
        tmp.write_text(html, encoding="utf-8")
        tmp.replace(self.html_path)
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta), encoding="utf-8")
        tmp.replace(self.meta_path)

    def load(self) -> tuple[str, dict] | None:
        if not self.exists():
            return None
        html = self.html_path.read_text(encoding="utf-8")
        meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        return html, meta


class SettingsStore:
    """Load/save the RateBook as JSON, falling back to the bundled seed."""

    def __init__(self, path: str | os.PathLike | None = None):
        env = os.environ.get("SETTINGS_PATH")
        self.path = Path(path or env or "data/settings.json")

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> RateBook:
        source = self.path if self.exists() else BUNDLED_DEFAULTS
        with open(source, encoding="utf-8") as fh:
            return ratebook_from_dict(json.load(fh))

    def load_dict(self) -> dict:
        source = self.path if self.exists() else BUNDLED_DEFAULTS
        with open(source, encoding="utf-8") as fh:
            return json.load(fh)

    def save(self, rb: RateBook) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(ratebook_to_dict(rb), indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def last_updated(self) -> date | None:
        if self.exists():
            return datetime.fromtimestamp(self.path.stat().st_mtime).date()
        return None
