# Advisor Task Planner

Weekly task plans for client advisors. Upload three exports, get a
prioritized, day-by-day call list for every advisor: printable, viewable in
the browser, or as an Excel workbook (one sheet per advisor). Who gets
targeted is set in the admin page at `/admin`.

## The three weekly inputs

| File | Source | What it provides |
|---|---|---|
| **Lead report** (`.xlsx`) | VinSolutions | Last 60 days of walk-ins, phone-ups and internet leads, grouped by sales rep |
| **Portfolio export** (`.xls`) | Infobahn (BMW FS) | Lease/retail contracts: maturity, payment, equity, in-market tier, warranty, client advisor |
| **Equity mining export** (`.xlsx`) | Mastermind | Upgrade proposals: payment difference, sales status, assignee, original salesperson |

The readers find columns by header name and sniff the real file type (the
Infobahn ".xls" is really an HTML table). The VinSolutions export's
Lead Source / Lead Type / Lead Status headers sit one column off their
data, so those three columns are identified by their contents.

## How a plan is built

1. **Targeting rules** (all editable in `/admin`) flag customers:
   - **Showroom & lead follow-up**: VinSolutions leads 1–60 days old; walk-ins get extra priority.
   - **Lease maturity**: BMW FS leases maturing in the next 180 days, or matured in the last 45.
   - **Retail payoff & equity**: retail contracts ending within 120 days, BMW FS in-market
     Tier 1–3, or $15k+ equity 30+ months into the contract.
   - **Mastermind upgrade**: Not Contacted / Attempted / Presented, with the proposed payment
     no more than $100/mo above the current one (Ready Now / Ready Soon always qualify).
   - **Warranty expiring**: within 3 months (Infobahn or Mastermind).
2. **One task per customer.** Infobahn and Mastermind rows merge by VIN.
   VinSolutions leads merge by name, but only when exactly one match exists
   and the contact details don't conflict. A customer flagged by several
   rules ranks higher, and the task shows every reason.
3. **Ownership.** Lease maturities belong to the salesperson who originated the
   lease (Mastermind's original salesperson, matched by VIN; otherwise the
   Infobahn client advisor) when they're an active advisor, and to the lease
   owner (Ed Mathieu) otherwise. This outranks every other ownership source,
   and the lease owner isn't held to the lease mix limit. For everything
   else, the VinSolutions rep comes first, then the Infobahn client advisor,
   then the Mastermind assignee. An orphan goes to its original salesperson
   when that person is on the roster. Name spellings are matched through
   the roster's aliases, ignoring case and middle names/initials;
   Mastermind's "Lewis - 90290" form matches on a unique last name.
4. **Left out:** customers marked Sold / Not Interested in Mastermind, and anyone
   already given to an advisor in the last 2 weeks. The exception is a
   customer with a new VinSolutions lead since then, who is brought back.
5. **Assignment.** Each advisor gets their own customers first, up to their weekly
   capacity (default 50). A per-rule weekly limit keeps every plan mixed
   (default: 30 follow-ups, 15 lease, 10 retail, 15 Mastermind, 5 warranty);
   leftover capacity is then backfilled by priority. Unowned customers
   (Orphan/Conquest Mastermind, departed or inactive advisors) fill spare
   capacity, going to whichever advisor has the most room.
6. **Scheduling.** Each list is split across the work days (Mon–Sat by default),
   most urgent first.

Plans are saved per week. The overview shows counts per advisor and rule,
own customers that didn't fit this week, and owner names that aren't on the
roster (add those as aliases if they're really an advisor). After changing
rules, **Rebuild plans** re-runs from the last uploaded files.

## Running it

```bash
pip install -r requirements.txt
python -m advisor_planner.webapp          # http://localhost:5001
```

Or from the command line:

```bash
python -m advisor_planner --vinsolutions VinSolution_Export.xlsx \
    --infobahn Infobahn_Export.xls --mastermind Mastermind.xlsx \
    --week 2026-10-26 --xlsx plans.xlsx --html plans.html
```

## Hosting (Railway)

The plans contain customer names, phone numbers and emails, so the site
**must** be password-protected.

1. In the Railway project, choose **New → GitHub Repo**, pick this repository, and set the
   variable `RAILWAY_DOCKERFILE_PATH=Dockerfile.planner`.
2. Set these variables:
   - `APP_PASSWORD`: everyone needs it to see plans or upload.
   - `ADMIN_PASSWORD`: needed for `/admin` (roster and targeting).
   - `PLANNER_DATA_DIR=/data/planner`
3. Attach a volume mounted at `/data`. It keeps settings, the plan history
   (which the 2-week no-repeat rule depends on) and the last uploads.
4. Under **Settings → Networking**, choose **Generate Domain**.

## Files

- `parsers.py`: the three export readers
- `planner.py`: targeting rules, merging, ownership, assignment, scheduling
- `settings.py`: defaults, the admin-form spec, and the JSON stores
- `export.py`: Excel workbook
- `webapp.py`: Flask app (upload, overview, printable plans, admin)
- `../tests/test_planner.py`: tests against synthetic exports
