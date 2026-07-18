# Loaner Pricing — chipboard-native service (Node/Express/MySQL)

The loaner payment sheet as a Node service built to bopchipboard's
conventions, so it can be developed and troubleshot standalone, then merged
into chipboard mechanically. The pricing engine is a verified port: the test
suite replays every row of the dealership's Simple_Calculator_2026.xlsx
(via the Python reference implementation in `../loaner_platform`) and the
payments must match exactly — currently 95/95 rows + 7 edge cases.

## Endpoints

Mounted at `/api/loaner-pricing`. All require a chipboard JWT
(`Authorization: Bearer <token>`); settings writes require `role === 'Admin'`.

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/sheet` | any user | Latest sheet `{ html, meta, staleRates }`; 404 until first generate |
| POST | `/generate` | any user | Multipart `inventory` + `vauto` files → regenerate & persist |
| GET | `/settings` | any user | Current ratebook settings |
| PUT | `/settings` | Admin | Replace settings (validated) |
| POST | `/settings/import` | Admin | Multipart `workbook` = Simple Calculator .xlsx |
| GET | `/settings/export` | Admin | Settings JSON download (backup) |

Standalone-only extras: `POST /api/auth/login` (a copy of chipboard's login
against the same users table — delete at merge) and `GET /healthz`.

## Environment

Same names as bopchipboard: `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`,
`MYSQL_DATABASE`, `JWT_SECRET`, `PORT`. With MySQL configured, settings live
in `loaner_settings` and generated sheets (with history, last 90) in
`loaner_sheets` — both tables auto-created. Without `MYSQL_HOST`, files under
`data/` are used (local dev only). The app boots seeded with the rates from
`seed/default_settings.json`.

## Run / test

```bash
npm install
npm test        # engine verification against the Python-generated vectors
npm start       # standalone server on :5000
```

## Merging into bopchipboard

1. Copy `routes/loanerPricing.js`, `lib/`, and `seed/` into bopchipboard.
2. In its `server.js`: `app.use('/api/loaner-pricing', require('./routes/loanerPricing'));`
3. Point `lib/settings.js` and the route's auth import at chipboard's own
   `db.js` and `middleware/auth.js` (drop this folder's copies — they are
   interface-identical; `requireAdmin` moves into chipboard's middleware).
4. Add `xlsx` is already a chipboard dependency; `multer` too. No new deps.
5. Delete `routes/auth.js`, `server.js`, `db.js` here — chipboard's take over.
6. Frontend: add the loaner pages to bopchipboardfront calling these endpoints.
