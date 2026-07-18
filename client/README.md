# Loaner pricing — React components for bopchipboardfront

Three drop-in components built to bopchipboardfront's conventions
(axios + the AuthContext request interceptor, `API_BASE_URL` from
`src/config`, `PrivateRoute` with `roles`, component + `.css` pairs,
date-fns). They talk to the `/api/loaner-pricing` endpoints served by
`../node`.

| Component | Route | Who | Purpose |
|---|---|---|---|
| `LoanerSheet` | `/loaners` | any user | Latest sheet (sortable, BMW/MINI filter) with last-uploaded banner |
| `LoanerUpload` | `/loaners/upload` | any user | Upload the two daily exports, regenerate |
| `LoanerSettings` | `/loaners/settings` | Admin | Rates/residuals/incentives, discount chart, formula settings, workbook import, backups |

## Installing into bopchipboardfront

1. Copy `src/components/Loaner*.{js,css}` into `bopchipboardfront/src/components/`.
2. In `src/App.js`, add the routes:

```jsx
import LoanerSheet from './components/LoanerSheet';
import LoanerUpload from './components/LoanerUpload';
import LoanerSettings from './components/LoanerSettings';

<Route path="/loaners" element={
  <PrivateRoute><LoanerSheet /></PrivateRoute>
} />
<Route path="/loaners/upload" element={
  <PrivateRoute><LoanerUpload /></PrivateRoute>
} />
<Route path="/loaners/settings" element={
  <PrivateRoute roles={['Admin']}><LoanerSettings /></PrivateRoute>
} />
```

3. In `src/components/Navbar.js`, add a link:

```jsx
{auth?.user && <Nav.Link as={Link} to="/loaners">Loaners</Nav.Link>}
```

No new npm dependencies — everything used (axios, react-router-dom,
date-fns) is already in bopchipboardfront's package.json.

While the service runs standalone (before the backend merge), point the
frontend at it with `REACT_APP_API_BASE_URL=https://<standalone-host>/api`;
after the merge no configuration changes are needed.
