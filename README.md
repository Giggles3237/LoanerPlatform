# LoanerPlatform

Turns the three files you already produce every day into a ready-to-send
**HTML loaner payment sheet** — with current miles, updated pricing, and
available lease payments for the whole loaner fleet.

## The three inputs

| File | Source | What it provides |
|---|---|---|
| **Full Inventory Report** (`.xlsx`) | Loaner fleet software (TSD) | Current miles for every active unit — the source of truth for mileage |
| **Payment Calculator export** (`.xls`/`.xlsx`) | vAuto | Every loaner (including retired): stock #, model, color, odometer, list price, sales cost, MSRP |
| **Simple Calculator** (`.xlsx`) | Your rates workbook | `Rates and Residuals` sheet: money factors, residuals, lease incentives, 39-month flags, the mileage discount chart, and program limits |

Rates are read from the Simple Calculator **every run**, so updating money
factors/residuals/incentives in that workbook is all you need to do when
programs change — no code changes.

## Quick start

```bash
pip install -r requirements.txt

python -m loaner_platform \
    --inventory Full_Inventory_Report.xlsx \
    --vauto Payment_Calculator.xls \
    --calculator Simple_Calculator_2026.xlsx \
    --out loaner_sheet.html
```

`loaner_sheet.html` is an email-client-safe body (inline CSS, table layout —
renders in Outlook/Gmail). Paste it into an email or send it with your mail
tool of choice. Add `--disclosures` to append the full per-unit legal
disclosure paragraphs, and `--date 2026-07-18` to override the report date.

### Web UI

```bash
python -m loaner_platform.webapp   # then open http://localhost:5000
```

Drag in the three files, click **Generate payment sheet**, and the rendered
email opens in the browser.

## What the email contains

1. **Payment sheet** — every priced loaner: Stock #, Model, Color, Miles,
   MSRP, Sale Price, Term, and monthly Lease payment (the same columns as the
   printed loaner sheet). A ▲ next to the mileage means the fleet report
   showed more miles than vAuto and the higher reading was used.
2. **Mileage updates needed in vAuto** — units where the fleet report miles
   exceed the vAuto odometer, with the difference, so vAuto can be corrected.
3. **Not priced — needs attention** — units that are over the program mileage
   limit, have no rate program for their model on the Rates sheet, or are
   missing an MSRP.
4. **In the fleet report but not in vAuto** — active loaners with no matching
   vAuto stock number.
5. The standard lease disclosure footer.

## Pricing model

A faithful port of the Simple Calculator `Primary` sheet, verified cell-for-cell
against its cached values (93/95 rows exact; the other 2 rows contain manual
overrides pasted over the Invoice formula in the workbook itself):

```
Invoice     = MSRP × 0.96 (under 1,000 mi) or × 0.94
AVP         = (MSRP − 995) × 5% − 300              (per the AVP mileage setting)
Mileage Adj = discount chart lookup on miles       ('Rates and Residuals' J12:K19)
Sale Price  = min(1,000 + Invoice − AVP − Mileage Adj, List Price)
Term        = 39 if the model is flagged '39 month lease', else 36
Residual $  = MSRP × Residual% − (miles − 500) × $0.25
Deprec      = Sale Price − Residual $ − Lease Incentive (if under mileage limit)
Rent        = (Sale Price + Residual $) × Money Factor × Term
Lease       = ROUND((Deprec + Rent) / Term)
```

Pricing miles are the **greater of** the vAuto odometer and the fleet-report
miles (matching the workbook's `Mileage Calc` sheet). Units at or above the
program mileage limit (default 15,500, read from the Rates sheet) are not
priced. Duplicate stock numbers in the vAuto export are collapsed, keeping the
higher odometer. Stock numbers with letter suffixes (`PB3626R`) match their
base fleet unit.

One intentional fix vs. the spreadsheet: the disclosure text now states the
actual lease term ("for 39 months"); the workbook's Disclosure1 formula pulled
a model name from a misaligned cell.

## Development

```bash
pip install -r requirements.txt pytest
pytest
```

- `loaner_platform/parsers.py` — the three file readers (header-name based,
  resilient to column reordering)
- `loaner_platform/pricing.py` — the pricing engine and disclosure builder
- `loaner_platform/fleet.py` — merge/dedupe/sort orchestration
- `loaner_platform/report.py` — HTML email rendering
- `tests/` — engine pinned to known values from the Simple Calculator
