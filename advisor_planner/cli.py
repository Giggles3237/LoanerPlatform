"""Command-line entry point: build a week's plans without the web app.

    python -m advisor_planner --vinsolutions VinSolution_Export.xlsx \\
        --infobahn Infobahn_Export.xls --mastermind Mastermind.xlsx \\
        --xlsx plans.xlsx --html plans.html

Uses (and records history in) the same data folder as the web app, so the
cooldown works the same way. Pass --no-save for a dry run.
"""

from __future__ import annotations

import argparse
from datetime import date

from .export import plan_workbook
from .parsers import parse_infobahn, parse_mastermind, parse_vinsolutions
from .planner import build_plan, week_start_for
from .settings import PlanStore, SettingsStore


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build weekly client-advisor task plans.")
    ap.add_argument("--vinsolutions", required=True)
    ap.add_argument("--infobahn", required=True)
    ap.add_argument("--mastermind", required=True)
    ap.add_argument("--week", help="plan week start, YYYY-MM-DD (default: next Monday)")
    ap.add_argument("--xlsx", help="write the Excel workbook here")
    ap.add_argument("--html", help="write the printable plans here")
    ap.add_argument("--no-save", action="store_true", help="don't save to plan history")
    args = ap.parse_args(argv)

    week = date.fromisoformat(args.week) if args.week else week_start_for(date.today())
    settings = SettingsStore().load()
    store = PlanStore()
    plan = build_plan(parse_vinsolutions(args.vinsolutions), parse_infobahn(args.infobahn),
                      parse_mastermind(args.mastermind), settings, week,
                      store.recent_keys(week, settings["cooldown_weeks"]))
    if not args.no_save:
        store.save(plan)
    if args.xlsx:
        with open(args.xlsx, "wb") as fh:
            fh.write(plan_workbook(plan))
    if args.html:
        from .webapp import _render_plan, app

        with app.test_request_context():
            html = _render_plan(plan, [a["name"] for a in plan["advisors"]], "Advisor plans")
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(html)

    print(f"Week of {plan['week_start']}: {plan['stats']['scheduled']} tasks scheduled "
          f"from {plan['stats']['qualified_customers']} matching customers")
    for a in plan["advisors"]:
        print(f"  {a['name']:<22} {a['tasks']:>3} / {a['capacity']:<3} "
              f"({a['reassigned']} reassigned)")
