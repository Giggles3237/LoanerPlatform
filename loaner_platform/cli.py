"""Command-line entry point.

Usage:
    python -m loaner_platform \
        --inventory Full_Inventory_Report.xlsx \
        --vauto Payment_Calculator.xls \
        --calculator Simple_Calculator_2026.xlsx \
        --out loaner_sheet.html
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .fleet import process_fleet
from .parsers import parse_inventory, parse_ratebook, parse_vauto
from .report import render_email


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loaner_platform",
        description="Generate the loaner fleet payment sheet as an HTML email.",
    )
    parser.add_argument("--inventory", required=True,
                        help="Full Inventory Report (.xlsx) from the fleet software")
    parser.add_argument("--vauto", required=True,
                        help="Payment Calculator export (.xls/.xlsx) from vAuto")
    parser.add_argument("--calculator", default=None,
                        help="Optional Simple Calculator workbook (.xlsx); "
                             "defaults to the app's stored settings")
    parser.add_argument("--settings", default=None,
                        help="Optional settings.json (an admin-panel export)")
    parser.add_argument("--out", default="loaner_sheet.html",
                        help="Output HTML file (default: loaner_sheet.html)")
    parser.add_argument("--date", default=None,
                        help="Report date as YYYY-MM-DD (default: today)")
    parser.add_argument("--disclosures", action="store_true",
                        help="Append the full per-unit legal disclosures")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report_date = date.fromisoformat(args.date) if args.date else date.today()

    inventory = parse_inventory(args.inventory)
    vauto = parse_vauto(args.vauto)
    if args.calculator:
        ratebook = parse_ratebook(args.calculator)
    elif args.settings:
        import json

        from .settings import ratebook_from_dict
        with open(args.settings, encoding="utf-8") as fh:
            ratebook = ratebook_from_dict(json.load(fh))
    else:
        from .settings import SettingsStore
        ratebook = SettingsStore().load()
    report = process_fleet(inventory, vauto, ratebook)

    html_body = render_email(report, report_date=report_date,
                             include_disclosures=args.disclosures)
    out = Path(args.out)
    out.write_text(html_body, encoding="utf-8")

    print(f"Loaner sheet written to {out}")
    print(f"  Fleet report units:   {len(inventory)}")
    print(f"  vAuto rows:           {len(vauto)}"
          + (f" ({report.duplicates_removed} duplicate stock #s collapsed)"
             if report.duplicates_removed else ""))
    print(f"  Priced:               {len(report.priced)}")
    print(f"  Mileage updates:      {len(report.mileage_updates)}")
    print(f"  Need attention:       {len(report.needs_attention)}")
    for u in report.needs_attention:
        print(f"    - {u.stock_number}: {'; '.join(u.warnings)}")
    if report.missing_from_vauto:
        print(f"  In fleet, not vAuto:  {len(report.missing_from_vauto)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
