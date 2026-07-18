# LoanerPlatform

The living loaner payment sheet. Team members upload the two daily exports
and get a ready-to-send **HTML payment sheet** — current miles, updated
pricing, and available lease payments for the whole loaner fleet. Rates,
residuals, incentives, and every discount rule live **inside the app**,
editable by admins at `/admin` — the Simple Calculator spreadsheet's whole
job, absorbed.

## The two daily inputs

| File | Source | What it provides |
|---|---|---|
| **Full Inventory Report** (`.xlsx`) | Loaner fleet software (TSD) | Current miles for every active unit — the source of truth for mileage |
| **Payment Calculator export** (`.xls`/`.xlsx`) | vAuto | Every loaner (including retired): stock #, model, color, odometer, list price, sales cost, MSRP |

## The built-in rate sheet (admin only)

Everything that used to live in the Simple Calculator workbook is stored in
the app and edited at **`/admin`** (requires the `ADMIN_PASSWORD`):

- **Rates, residuals & incentives** — money factor, residual %, lease
  incentive, and the 39-month flag per model; add or remove models
- **Mileage discount chart** — the miles-to-discount breakpoints
- **Formula settings** — invoice % of MSRP (low/high mileage), sale-price
  markup, AVP calculation (deduction, percent, credit, mileage threshold),
  residual per-mile charge and free miles, program mileage limit, fees,
  dealership name, and the programs-valid-through date
- **Import / backup** — bulk-import a Simple Calculator `.xlsx` (the old
  workbook still works as a loading dock), and export/restore settings as
  JSON backups

Settings persist to `data/settings.json` (override with the
`SETTINGS_PATH` env var). The app ships seeded with the dealership's
current rates, so it works out of the box.

## Quick start

```bash
pip install -r requirements.txt

python -m loaner_platform \
    --inventory Full_Inventory_Report.xlsx \
    --vauto Payment_Calculator.xls \
    --out loaner_sheet.html
```

The CLI uses the app's stored settings by default; pass
`--calculator Simple_Calculator.xlsx` or `--settings backup.json` to price
with a specific rate source instead.

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

## Deploying it as an application

### Option A — run it on one PC (simplest)

Install [Python](https://www.python.org/downloads/) (check "Add python.exe to
PATH" during install), download this repo (green **Code** button → Download
ZIP, or `git clone`), and double-click **`run_windows.bat`**. It installs the
dependencies, starts the app, and opens http://localhost:5000 in your browser.
Pin that page or the .bat file to your taskbar and it behaves like a desktop
app. On Mac/Linux: `pip install -r requirements.txt && python -m
loaner_platform.webapp`.

### Option B — host it so the whole store can use it

The repo includes a `Dockerfile` and a `render.yaml` blueprint:

1. Create a free account at [render.com](https://render.com) and connect your
   GitHub.
2. **New + → Blueprint**, pick this repository.
3. When prompted, set **APP_PASSWORD** (every visitor needs it — the sheet
   shows cost data) and **ADMIN_PASSWORD** (required to open `/admin` and
   change rates or settings). Use different values so the team can generate
   sheets without being able to edit pricing.
4. Render builds the Docker image and gives you a permanent URL
   (e.g. `https://loanerplatform.onrender.com`) anyone at the store can open,
   drop the three files into, and get the sheet.

The same Dockerfile works on Railway, Fly.io, Azure App Service, or any
machine with Docker (`docker build -t loanerplatform . && docker run -p
8000:8000 -e APP_PASSWORD=yourpassword loanerplatform`).

Note the free Render tier sleeps after inactivity — the first visit of the
day takes ~30 seconds to wake. Paid tiers ($7/mo) stay warm.

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
