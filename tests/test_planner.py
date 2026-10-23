"""Advisor planner: parsers on synthetic exports that mimic the real quirks,
and the planning rules end to end."""

from datetime import date, datetime

import openpyxl
import pytest

from advisor_planner.parsers import parse_infobahn, parse_mastermind, parse_vinsolutions
from advisor_planner.planner import Roster, build_plan, week_start_for
from advisor_planner.settings import PlanStore, SettingsStore, normalize_settings

WEEK = date(2026, 10, 26)


def _xlsx(path, rows):
    wb = openpyxl.Workbook()
    for row in rows:
        wb.active.append(row)
    wb.save(path)
    return path


@pytest.fixture
def vin_file(tmp_path):
    # Real export quirk: the three lead headers sit one column off their data.
    return _xlsx(tmp_path / "vin.xlsx", [
        ["Sales Rep", "Customer", "Lead Source", "Lead Type", "Lead Status", "Year", "Make",
         "Model", "Lead Origination Date", "Customer Note"],
        ["Gregg Lewis", None, None, None, None, None, None, None, None, None],
        [None, "Dina Valant", "Active", "Walk In", "Walk-in", 2027, "BMW", 540,
         datetime(2026, 10, 22), None],
        [None, "Mason Woyt", "Active", "Phone  Up", "Phone", None, None, None,
         datetime(2026, 10, 1), "prefers text"],
        ["Aleah Cimino", None, None, None, None, None, None, None, None, None],
        [None, "Old Lead", "Active", "Curator", "Internet", None, None, None,
         datetime(2026, 7, 1), None],
        [None, "Sold Guy", "Active", "Walk In", "Walk-in", None, None, None,
         datetime(2026, 10, 20), None],
    ])


@pytest.fixture
def infobahn_file(tmp_path):
    # Real export quirk: an HTML table saved with a .xls extension.
    head = ["Last/Company Name", "First Name", "Home Phone", "Work Phone", "Email",
            "In Market Tier", "Contract Date", "Maturity Date", "Contract Type",
            "Contract Miles", "Monthly Payment", "Estimated Equity", "VIN", "Year",
            "Make & Model", "Last Service Odometer", "Client Advisor", "Account Status",
            "Warranty Type", "Warranty Status", "Warranty Expiration Date", "Service Contract"]
    rows = [
        ["Woyt", "Mason", "(412) 400-6641", "(000) 000-0000", "mason@example.com", "N/A",
         "10/23/2023", "11/23/2026", "Lease", "36,000", "$1,044.30", "$10,718.52",
         "VIN0000000000000A", "2024", "BMW M340i", "28,536", "ED MATHIEU", "Active",
         "Factory", "Active", "10/23/2027", "No"],
        ["Penn", "Margot", "(202) 577-8049", "", "margot@example.com", "Tier 1",
         "10/27/2021", "10/27/2029", "Retail", "N/A", "$615.02", "$9,810.75",
         "VIN0000000000000B", "2021", "BMW X3", "34,014", "KENNETH WILSON", "Active",
         "", "", "", "No"],
    ]
    cells = lambda r, tag: "".join(f"<{tag}>{c}</{tag}>" for c in r)
    html = "<table><tr>" + cells(head, "th") + "</tr>" + "".join(
        "<tr>" + cells(r, "td") + "</tr>" for r in rows) + "</table>"
    path = tmp_path / "infobahn.xls"
    path.write_text(html)
    return path


@pytest.fixture
def mastermind_file(tmp_path):
    head = ["Customer Name", "Customer Email", "Phone Office", "Phone Home", "Cell Phone",
            "Do Not Email Until Date", "Household Demand Indicator", "Vin",
            "Current Vehicle Year", "Current Make", "Current Vehicle Model",
            "Current Vehicle Trim", "Lease Mileage Status", "Warranty Status", "Assignee",
            "Sales Status", "Sub Status", "Original Sales Person", "Current Contract End Date",
            "Current Deal Type", "Current Vehicle Monthly Payment", "Payment Difference",
            "Trade Equity", "Months Of Ownership", "New Vehicle Year", "New Vehicle Make",
            "New Vehicle Model", "New Vehicle Trim", "New Vehicle Monthly Payment"]
    base = dict(zip(head, [""] * len(head)))

    def row(**kw):
        r = dict(base, **kw)
        return [r[h] for h in head]

    return _xlsx(tmp_path / "mm.xlsx", [
        head,
        # Same VIN as Margot's Infobahn account -> one merged task.
        row(**{"Customer Name": "Margot Penn", "Vin": "VIN0000000000000B",
               "Cell Phone": "2025778049", "Assignee": "Orphan Mastermind",
               "Sales Status": "NotContacted", "Sub Status": "Unknown",
               "Original Sales Person": "Scott Stiller", "Payment Difference": "-20",
               "Months Of Ownership": "60", "Current Vehicle Year": "2021",
               "Current Make": "BMW", "Current Vehicle Model": "X3",
               "Do Not Email Until Date": "Email is disabled"}),
        # Orphan whose original salesperson is on the roster (alias spelling).
        row(**{"Customer Name": "Pat Orphan", "Vin": "VIN0000000000000C",
               "Cell Phone": "4125550100", "Assignee": "Orphan Mastermind",
               "Sales Status": "NotContacted", "Sub Status": "Unknown",
               "Original Sales Person": "Edward J Mathieu", "Payment Difference": "50",
               "Months Of Ownership": "40"}),
        # Payment jump too large and no hot sub-status -> not targeted.
        row(**{"Customer Name": "Too Pricey", "Vin": "VIN0000000000000D",
               "Assignee": "Gregg Lewis", "Sales Status": "NotContacted",
               "Sub Status": "Unknown", "Payment Difference": "400",
               "Months Of Ownership": "40"}),
        # Sold in Mastermind -> suppresses the VinSolutions lead of the same name.
        row(**{"Customer Name": "Sold Guy", "Vin": "VIN0000000000000E",
               "Assignee": "Aleah Cimino", "Sales Status": "Sold"}),
        # Nameless row with contact info is kept.
        row(**{"Customer Name": None, "Customer Email": "anon@example.com",
               "Vin": "VIN0000000000000F", "Assignee": "Conquest Mastermind",
               "Sales Status": "Attempted", "Sub Status": "ReadySoon",
               "Months Of Ownership": "20"}),
    ])


@pytest.fixture
def data(vin_file, infobahn_file, mastermind_file):
    return (parse_vinsolutions(vin_file), parse_infobahn(infobahn_file),
            parse_mastermind(mastermind_file))


def test_vinsolutions_columns_detected_by_content(vin_file):
    leads = parse_vinsolutions(vin_file)
    assert [l.rep for l in leads] == ["Gregg Lewis", "Gregg Lewis", "Aleah Cimino", "Aleah Cimino"]
    dina = leads[0]
    assert (dina.status, dina.source, dina.lead_type) == ("Active", "Walk In", "Walk-in")
    assert dina.model == "540"  # numeric cell, not "540.0"
    assert dina.created == date(2026, 10, 22)


def test_infobahn_html_and_phone_cleanup(infobahn_file):
    accts = parse_infobahn(infobahn_file)
    assert accts[0].customer == "Mason Woyt"
    assert accts[0].phones == ["(412) 400-6641"]  # (000) 000-0000 dropped
    assert accts[0].is_lease and not accts[1].is_lease
    assert accts[0].payment == pytest.approx(1044.30)


def test_mastermind_nameless_rows_kept(mastermind_file):
    recs = parse_mastermind(mastermind_file)
    assert recs[-1].customer == "(No name) anon@example.com"
    assert recs[0].email_ok is False


def test_roster_aliases_and_case():
    roster = Roster(normalize_settings({})["advisors"])
    assert roster.resolve("ED MATHIEU") == "Ed Mathieu"
    assert roster.resolve("Edward J Mathieu") == "Ed Mathieu"
    assert roster.resolve("gregory riley") == "Greg Riley"
    assert roster.resolve("Morgan Mclane") == "Morgan McLane"
    assert roster.resolve("Chris Lasko") == ""


def test_plan_end_to_end(data):
    plan = build_plan(*data, normalize_settings({}), WEEK)
    tasks = {t["customer"]: t for t in plan["tasks"]}

    # Recent walk-in kept, 117-day-old lead dropped, Sold-in-Mastermind lead suppressed.
    assert "Dina Valant" in tasks and "Old Lead" not in tasks and "Sold Guy" not in tasks
    assert plan["stats"]["suppressed"]["sold_or_not_interested"] == 1

    # Mason: VinSolutions lead (Gregg) + Infobahn lease merged by name. Lease
    # routing outranks the showroom rep: Ed originated it (Infobahn, no MM match).
    mason = tasks["Mason Woyt"]
    assert {r["rule"] for r in mason["reasons"]} == {"showroom", "lease_maturity"}
    assert mason["owner"] == "Ed Mathieu" and mason["phones"] == ["(412) 400-6641"]

    # Margot: Infobahn + Mastermind merged by VIN; departed advisor -> unowned, reassigned.
    margot = tasks["Margot Penn"]
    assert {r["rule"] for r in margot["reasons"]} == {"retail_payoff", "mastermind"}
    assert margot["owner"] == "" and margot["reassigned"] and margot["advisor"]
    assert margot["previous_owner"] == "KENNETH WILSON" and margot["do_not_email"]

    # Orphan handed back to the original salesperson on the roster.
    assert tasks["Pat Orphan"]["owner"] == "Ed Mathieu"
    assert "Too Pricey" not in tasks
    assert all(t["day"] in plan["work_days"] for t in plan["tasks"] if t["advisor"])


def test_capacity_and_mix_limits(data):
    s = normalize_settings({"default_weekly_capacity": 1})
    plan = build_plan(*data, s, WEEK)
    for a in plan["advisors"]:
        assert a["tasks"] <= 1
    ed = next(a for a in plan["advisors"] if a["name"] == "Ed Mathieu")
    assert ed["own_not_scheduled"] == 1  # Mason's lease + Pat Orphan, room for one


def test_disabled_rule_and_no_distribution(data):
    s = normalize_settings({"rules": {"mastermind": {"enabled": False}},
                            "unowned": {"distribute": False}})
    plan = build_plan(*data, s, WEEK)
    assert all(r["rule"] != "mastermind" for t in plan["tasks"] for r in t["reasons"])
    assert not any(t["reassigned"] for t in plan["tasks"])


def test_cooldown_history(tmp_path, data):
    plans = PlanStore(tmp_path / "plans")
    s = normalize_settings({})
    plans.save(build_plan(*data, s, WEEK))
    nxt = date(2026, 11, 2)
    history = plans.recent_keys(nxt, s["cooldown_weeks"])
    plan2 = build_plan(*data, s, nxt, history)
    assert plan2["stats"]["suppressed"]["cooldown"] > 0
    assert plans.recent_keys(date(2026, 11, 30), s["cooldown_weeks"]) == {}


def test_settings_round_trip(tmp_path):
    store = SettingsStore(tmp_path / "s.json")
    s = store.load()
    s["advisors"].append({"name": " New  Person ", "aliases": ["NP"], "active": False})
    s["rules"]["showroom"]["max_days"] = "30"
    store.save(s)
    again = store.load()
    assert again["advisors"][-1]["name"] == "New Person"
    assert again["rules"]["showroom"]["max_days"] == 30


def test_week_start():
    assert week_start_for(date(2026, 10, 23)) == date(2026, 10, 26)  # Friday -> next Monday
    assert week_start_for(date(2026, 10, 26)) == date(2026, 10, 26)  # Monday -> today


def test_webapp_flow(tmp_path, monkeypatch, vin_file, infobahn_file, mastermind_file):
    import advisor_planner.webapp as web

    monkeypatch.setattr(web, "store", SettingsStore(tmp_path / "settings.json"))
    monkeypatch.setattr(web, "plans", PlanStore(tmp_path / "plans"))
    monkeypatch.setattr(web, "uploads", web.UploadStore(tmp_path / "uploads"))
    c = web.app.test_client()
    r = c.post("/generate", data={
        "vinsolutions": (open(vin_file, "rb"), "v.xlsx"),
        "infobahn": (open(infobahn_file, "rb"), "i.xls"),
        "mastermind": (open(mastermind_file, "rb"), "m.xlsx"),
        "week_start": "2026-10-26"}, content_type="multipart/form-data")
    assert r.status_code == 302 and r.location.endswith("/plan/2026-10-26")
    assert b"Gregg Lewis" in c.get("/plan/2026-10-26").data
    assert b"Dina Valant" in c.get("/plan/2026-10-26/advisor/Gregg Lewis").data
    assert c.get("/plan/2026-10-26/plans.xlsx").data[:2] == b"PK"
    assert c.post("/regenerate", data={"week_start": "2026-10-26"}).status_code == 302
    assert c.get("/plan/../../etc").status_code == 404


def test_roster_employee_code_spelling():
    roster = Roster(normalize_settings({})["advisors"])
    assert roster.resolve("Lewis - 90290") == "Gregg Lewis"
    assert roster.resolve("Mathieu - 90015") == "Ed Mathieu"
    assert roster.resolve("Lasko - 54195") == ""


NAMES = {"L1": "Adams", "L2": "Baker", "L3": "Clark", "L4": "Davis"}


def _lease(vin, advisor, maturity="11/23/2026"):
    from advisor_planner.models import FSAccount
    return FSAccount(customer=f"Lessee {NAMES[vin]}", cosigner="", phones=["(412) 555-0101"],
                     email="", in_market_tier="", contract_date=date(2023, 10, 1),
                     maturity=datetime.strptime(maturity, "%m/%d/%Y").date(),
                     contract_type="Lease", contract_miles=36000, payment=900, equity=1000,
                     vin=vin, year="2024", vehicle="BMW X5", odometer=20000,
                     last_service=None, advisor=advisor, warranty_type="",
                     warranty_status="", warranty_expires=None, service_contract="No")


def test_lease_routing(data):
    leads, _, records = data
    from advisor_planner.models import MastermindRecord
    accounts = [
        _lease("L1", "CHRIS LASKO"),       # MM says Gregg originated -> Gregg
        _lease("L2", "GREGG LEWIS"),       # MM says departed rep originated -> Ed
        _lease("L3", "River Riffey"),      # no MM match -> Infobahn advisor originated
        _lease("L4", "KENNETH WILSON"),    # departed, no MM -> Ed
    ]
    mm = lambda vin, orig: MastermindRecord(
        customer=f"Lessee {NAMES[vin]}", cobuyer="", phones=[], email="", email_ok=True,
        household_demand=False, vin=vin, year="", make="", model="", trim="",
        lease_mileage_status="", warranty_months_left=None, assignee="Orphan Mastermind",
        status="Presented", sub_status="NotReady", original_salesperson=orig,
        vehicle_type="", contract_end=None, deal_type="Lease", payment=None,
        payment_difference=None, trade_equity=None, months_owned=None, new_vehicle="",
        new_payment=None)
    records = records + [mm("L1", "Lewis - 90290"), mm("L2", "Laurene Willis")]
    plan = build_plan(leads, accounts, records, normalize_settings({}), WEEK)
    owners = {t["key"]: (t["owner"], t["owner_basis"]) for t in plan["tasks"]}
    assert owners["vin:L1"] == ("Gregg Lewis", "Lease originated by this advisor")
    assert owners["vin:L2"] == ("Ed Mathieu", "Lease maturity owner (sold by Laurene Willis)")
    assert owners["vin:L3"][0] == "River Riffey"
    assert owners["vin:L4"][0] == "Ed Mathieu"

    off = normalize_settings({"rules": {"lease_maturity": {"originator_keeps": False}}})
    plan = build_plan(leads, accounts, records, off, WEEK)
    assert {t["owner"] for t in plan["tasks"] if t["key"].startswith("vin:L")} == {"Ed Mathieu"}
