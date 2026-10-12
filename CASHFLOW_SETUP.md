# Cash Flow Model — setup

Backend (new endpoints: GET /cashflow/defaults, POST /cashflow/forecast, POST /cashflow/export):
    cd backend && pip install -r requirements.txt   # adds openpyxl
    uvicorn main:app --reload
    pytest                                          # 42 tests

Frontend (new page at /cashflow, link added on the home page):
    cd frontend && npm install && npm run dev
    The page uses the Railway API by default; set NEXT_PUBLIC_API_BASE=http://localhost:8000 for a local backend.

Notes
- Receivables assumptions are calibrated from your invoice data; payroll, opex, debt,
  one-offs and starting cash are illustrative placeholders - edit them in the Assumptions panel.
- Default start date = newest invoice date in the data.
- The deployed (Railway) backend must be redeployed for the new endpoints.

Payables, capex and trends
- Payables use the bundled sample dataset `backend/neuraflow_bills.csv` (regenerate with `python generate_sample_bills.py`).
  Point `DEFAULT_BILLS_CSV_PATH` at your own bills file (columns: BillID, VendorID, VendorName, Category, BillDate,
  DueDate, BillAmount, PaymentDate, Status, OpenAmount, TermsDays).
- Capex plan: dated purchases, cash / loan / lease funding, maintenance vs growth, straight-line depreciation.
- Micro trends come from the invoice and bill history. Macro trends are fetched live from FRED
  (https://fred.stlouisfed.org, no API key) and cached for 6 hours; the backend host needs outbound HTTPS.
  If FRED can't be reached the page says so and shows no numbers. The macro overlay is off by default.

## Payroll, general ledger and balance sheet

- **Payroll roster** (`backend/neuraflow_payroll.csv`, columns EmployeeID, Department, Title, PayType, AnnualSalary, HourlyRate, HoursPerWeek, HireDate, TermDate, BonusPct, BenefitsMonthly). Roles and IDs only, no names. Cash goes out on pay runs (biweekly, semimonthly or monthly); the P&L accrues the same cost by month. Override the path with `DEFAULT_PAYROLL_CSV_PATH`.
- **General ledger** (`backend/neuraflow_gl_accounts.csv` + `neuraflow_gl_journal.csv`; override with `DEFAULT_GL_ACCOUNTS_CSV_PATH` / `DEFAULT_GL_JOURNAL_CSV_PATH`). Each account has a `ModelLine` (revenue, cogs, payroll, `opex:<line>`, depreciation, interest, cash, ar, ap, ppe, debt, equity). The sample is generated from the invoices, bills and roster by `python generate_sample_gl.py` and ties to them exactly.
- Forecast defaults (starting cash, revenue, cost of sales %, operating expense lines, term loan, depreciation, opening PP&E) come from the ledger's last three complete months and balances. "Apply ledger baselines" in the GL & Actuals tab re-applies them.
- **Balance sheet** rolls forward from the same events and P&L, with equity as the balancing figure; the check row stays at zero.
- Extra API: `GET /cashflow/gl`. The forecast response now includes `payroll`, `balance_sheet` and `gl`; the Excel export adds Payroll, Balance Sheet and GL vs Forecast sheets.

## Receivables tab and tab-aware what-ifs

The Receivables (AR) tab holds the aging, customer table, customer-cash charts and the AR assistant. Each tab has its own what-if levers, and no lever appears on two tabs:

| Tab | Levers |
|---|---|
| Forecast | sales level, growth, overhead |
| Receivables | pay speed, past-due invoices, largest customer, collectability, bad debt |
| Payroll | base pay, raises, extra hires, bonuses, benefits, employer taxes |
| Payables | days to pay, overdue-bill catch-up, largest vendor, cost of goods |
| Capex | size, delay, maintenance, down payment |
| Balance Sheet | interest rate, tax rate, extra loan payment, owner cash |
| GL & Actuals | starting cash vs ledger, other monthly cash, one-off item |
| Trends | seasonality, losing part of the largest customer, new-sale payment timing |

Every lever stays applied when you switch tabs, and the panel lists any that are active elsewhere. The forecast response includes `whatif_impact`: the effect of each group of levers on ending cash and the lowest balance.

### Assistants on every tab
Each tab has its own assistant at the bottom of the tab (`POST /cashflow/assistant` with a `tab` field). It answers only from the numbers on screen and the data loaded behind that tab: invoices (Receivables), vendor bills (Payables), the payroll roster (Payroll), purchases and financing (Capex), the balance sheet, the general ledger and its tie-outs (GL & Actuals), and the history behind Trends. The Forecast assistant sees the cash, P&L and scenario comparison. Click a customer (Receivables) or vendor (Payables) to focus the question on them. Each assistant may only suggest settings for its own tab's what-if sliders; the browser shows them with an Apply button, and the server drops any unknown or out-of-range value. Each tab keeps its own conversation while you switch around. `/cashflow/ar-assistant` still works and is the Receivables assistant. It needs `OPENAI_API_KEY` on the backend (model via `AR_ASSISTANT_MODEL`, default `gpt-4.1-mini`). The earlier standalone assistant page is still available at `/classic` but is no longer in the top navigation; `/` redirects to `/cashflow`.

## Standard projections
The Forecast tab has a "Standard projections" table with cash after 30, 60, 90 and 180 days and 1 year: ending cash, change, cash in and out, operating / investing / financing, lowest balance and date, and whether you stay above your minimum. It also shows ending cash for the best, base and worst cases at each checkpoint. The numbers come from the same dated cash events as the weekly and monthly views, so they respond to every what-if. A window that runs past the plan horizon shows "n/a" (raise Horizon in General settings; 1 year needs 12 months). The Excel export has a Projections sheet, the forecast response includes `projections`, and the Forecast assistant can answer questions about them.

## Credit Score tab
Every customer gets a payment-behavior score from 0 to 100 (higher is safer), built only from the invoice history: how late they pay (40%), how often they pay late (30%), what is past due now (15%), how predictable they are (5%) and whether they are getting faster or slower (10%). Customers with few payments are pulled toward a neutral 50 and flagged low confidence. Bands: Low risk 70+, Watch 40 to 69, High risk under 40. The Receivables table shows the score, the Excel export has a Credit Scores sheet, and the Credit Score tab shows the reasons behind each score. API: `GET /cashflow/credit`.

**Back-test** (`GET /cashflow/credit/validation`): the score is replayed at past dates every 14 days, using only what was known at each date, and compared with what happened to invoices due in the next 30 to 120 days (late = paid more than N days after due, or still unpaid). It reports ranking accuracy (AUC) with a 95% range from re-sampling whole customers, late rates by band, five equal-sized groups, what each ingredient adds on its own, comparison with simple rules, and plain-language findings generated from the numbers. `GET /cashflow/credit/validation/export` downloads every scored invoice as CSV.

Read the results with care: the bundled sample has two very different kinds of payer, so it shows the method works, not how it performs on real businesses. The ingredient weights were set by judgment and two were lowered after the first back-test, so the numbers are not fully out-of-sample. A pilot on real customer data is the real test. Industry volatility and supply-chain links are not part of the score yet.

## Models (ML framework, shadow mode)

A small ML framework runs behind the scenes on the structured data (`backend/mlfw/`). Open **Models** in the top nav to see it.

**Models.** Will this invoice be paid late (probability), how many days late (regression), learned credit-score weights, vendor-bill timing, and next month's revenue and costs from the ledger.

**Shadow mode.** Nothing here changes the cash flow forecast. Each model is scored against the rule NeuraFlow uses today (customer's average days late, the fixed-weight credit score, trailing 3-month average and so on). A model is only said to "beat" its rule when the 95% bootstrap range of the difference excludes zero. Switching a model into the forecast is a later step, behind a toggle.

**Validation.** Walk-forward: each 30-day test block is scored by a model trained only on rows whose outcome was already known before the block began. Features are point-in-time, so nothing from the future leaks into a prediction.

**Registry.** Every trained model gets a version (`task.model.vN`), the data fingerprint, row count and training window. Files go to `backend/models_store/` (override with `MODEL_STORE_DIR`, gitignored). On Railway the disk is ephemeral, so the registry resets on redeploy; the saving is best-effort and never blocks a request. Mount a volume and point `MODEL_STORE_DIR` at it to keep history.

**Endpoints.** `GET /cashflow/ml/overview`, `POST /cashflow/ml/retrain`, `GET /cashflow/ml/predictions/open-invoices?limit=`.

**Reading the results.** On the bundled sample data no model beats its simple rule (the sample is synthetic with two payer types, and some tests have few rows). That is shown on the page as is. Real data is where this gets decided.

## Sample data dates

The bundled sample was cut on 2026-04-09. So the forecast does not start in the past, the sample's invoices, bills, ledger and payroll dates are moved forward by whole calendar months until they end in the current month. Gaps inside each record stay exact, so payment behavior is unchanged. Only the bundled sample moves; uploads, `DEFAULT_*_CSV_PATH` files and databases never do. Set `SAMPLE_REBASE=off` to use the dates as cut.

## Bring your own data (Data page)

Open **Data** in the top nav. Until you connect something, the whole app runs on the built-in sample, and a "Sample data" pill in the nav says so. Each of the five datasets (invoices, vendor bills, ledger accounts, ledger journal lines, payroll roster) can come from its own source or all from the same one.

**Sources.** CSV and Excel uploads (title rows above the headers are skipped, a sheet can be chosen), Snowflake and Databricks (pick a table or view, or write one read-only `SELECT`), and SFTP (a file name or a pattern such as `invoices*.csv`; the newest match is used).

**Flow.** Choose the source, read the data, confirm the column matching (suggested from names and from what is in the columns; dates in US, day-first, `09-Apr-2026`, Excel serial and `20260409` forms and amounts like `$1,234.50` or `(500)` are understood), review the checks, load. Nothing loads while a check marked "Must fix" is open. Ledger accounts that have no NeuraFlow line are classified from their type and name, and each can be changed before loading.

**Sample vs yours.** After the first dataset is connected, a dataset with no source is empty. It is never filled with sample data. The ledger is used only when both the chart of accounts and the journal are loaded.

**Loaded data is a snapshot.** The forecast reads the last good snapshot, so a slow or down warehouse never blocks a page. A refresh that fails its checks, or comes back with less than half the previous rows, keeps the previous data and shows why on the Data page.

### Server settings

| Setting | What it does |
|---|---|
| `ADMIN_TOKEN` | Required to change anything on the Data page (sent as `X-Admin-Token`, kept in the browser tab only). Without it, changes are refused. There is no other sign-in in the app. Ten wrong tries in ten minutes are blocked for a while. |
| `ALLOW_OPEN_DATA_ADMIN=1` | Local development only: allow changes with no token. |
| `CONNECTION_ENCRYPTION_KEY` | Needed to save a connection from the page. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Passwords, tokens and keys are encrypted with it and never returned. If the key changes, saved credentials must be re-entered. |
| `INGEST_DIR` | Where uploads, saved connections and loaded snapshots live. Default `backend/ingest_store` (gitignored). On Railway the disk is temporary, so mount a volume and point this at it, or it resets on each deploy. |
| `MAX_UPLOAD_MB`, `INGEST_ROW_LIMIT` | Upload size (default 25) and rows read per dataset (default 250,000). |
| `INGEST_SCHEDULER=off` | Turn the background refresher off. |

Connections can also come from server settings instead of being saved: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD` (or `SNOWFLAKE_PRIVATE_KEY`), `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`, `SNOWFLAKE_ROLE`; `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_TOKEN`, `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA`; `SFTP_HOST`, `SFTP_PORT`, `SFTP_USERNAME`, `SFTP_PASSWORD` (or `SFTP_PRIVATE_KEY`), `SFTP_DIRECTORY`, `SFTP_HOST_KEY_SHA256`. These show on the Data page as "Server setting", are read-only there, and need no encryption key.

### Refreshing on a schedule

For connection sources, choose "Only when I ask", every N minutes (15 minimum) or once a day at a time in a time zone. A background thread in the server process runs the refreshes, so it only runs while the service is up and only once per running instance.

### Auto-load from SFTP ("ghost" mode)

With no clicking at all: set the `SFTP_*` settings above plus a pattern per dataset and a schedule.

```
SFTP_PATTERN_INVOICES=invoices*.csv
SFTP_PATTERN_BILLS=bills*.csv
SFTP_PATTERN_GL_ACCOUNTS=gl_accounts*.csv
SFTP_PATTERN_GL_JOURNAL=gl_journal*.csv
SFTP_PATTERN_PAYROLL=payroll*.csv
SFTP_SCHEDULE=daily@06:00        # or: every 60m   (time zone: INGEST_TIMEZONE, default UTC)
```

A dataset loads itself only when every required column is matched, the checks pass and it has no source yet. Otherwise the Data page shows what to review and nothing is loaded. A dataset you connected by hand is never overridden.

### Security notes

- SFTP needs the server's host key fingerprint pinned (`SFTP_HOST_KEY_SHA256` or "Look up fingerprint" on the connection). Credentials are not sent to a server whose key does not match.
- NeuraFlow only ever issues `SELECT`, with a row limit, and custom queries must be a single read-only statement. That filter is a safety net, not a security boundary: give the connection a read-only role that can see only the tables it needs.
- There is one workspace. Whatever is loaded is what every viewer of the deployment sees; there are no per-user accounts or separate customers yet.
- Uploaded files stay on the server's disk until replaced or disconnected.

## Customer workspaces

Each customer gets a private workspace: its own data, saved connections, uploads, models, schedules and activity log. Nothing is shared, and a request that is not tied to a workspace is refused rather than falling back to anyone's data.

**Turning it on.** Set these on the backend (Railway):

| Variable | Purpose |
| --- | --- |
| `WORKSPACE_MODE=required` | Every request needs a workspace key. Leave unset (or `open`) to keep today's single-workspace behaviour. |
| `PLATFORM_ADMIN_TOKEN` | Lets you, the platform operator, open `/platform` to create workspaces. Keep it secret; it is separate from customer keys. |
| `WORKSPACES_DIR` | Where workspace folders live. **Mount a persistent volume and point this at it**, otherwise workspaces are lost on redeploy. |
| `CONNECTION_ENCRYPTION_KEY` | Master key for saved credentials. Each workspace gets its own key derived from it, so one workspace's saved credentials cannot be opened from another. Back it up: losing it means re-entering every connection. |
| `ASSISTANT_DAILY_LIMIT` | Assistant questions per workspace per day (default 200). |

**Daily use.**
1. Open `/platform`, enter the platform token, and create a workspace. Choose **Empty** (the customer connects their own data) or **Demo** (clearly labelled sample data, for demos only).
2. The first admin key is shown **once**. Copy it, or copy the private sign-in link, and send it to the customer privately.
3. The customer signs in at `/signin` (or opens the link). Admin keys connect and change data; viewer keys can only look. Issue more keys, or revoke one, from the same page. Revoking works immediately; the last admin key cannot be revoked, so nobody is locked out.
4. Suspend a workspace to lock everyone out without deleting anything. Delete removes the data, connections, models and keys for good.

**What is different inside a workspace.**
- It starts empty and shows a "Connect your data" screen until something is loaded. It never shows sample numbers.
- The operator's own server connections (`SNOWFLAKE_*`, `DATABRICKS_*`, `SFTP_*`) are not visible to customers. Customers add their own on the Data page, and their saved credentials are encrypted per workspace.
- SFTP auto-load is set per workspace on the Data page (connection, file patterns, schedule).
- The Data page shows a short activity log (who changed what, never secrets or values).

**Rolling it out on an existing deployment.**
1. Add a volume and set `WORKSPACES_DIR`, `PLATFORM_ADMIN_TOKEN` and `CONNECTION_ENCRYPTION_KEY`.
2. Deploy with `WORKSPACE_MODE` still unset. Nothing changes for current users.
3. Create the customers' workspaces and check them.
4. Set `WORKSPACE_MODE=required`.

Notes: the original `/chat`, `/chat-upload`, `/traceability` endpoints and the `/classic` page use one global data source, so they are switched off in required mode. The in-app scheduler runs once per backend instance; run a single instance, or refreshes will repeat.

## Guided warehouse setup (Snowflake and Databricks)

On the Data page, **Add connection** now has a **Setup guide** for Snowflake and Databricks. The customer's administrator answers a few questions (database or catalog, schemas, role names) and gets copy-paste steps: a read-only role, a small auto-suspending warehouse (Snowflake), a service user or service principal, and the exact `USAGE` / `SELECT` grants. Every grant is read-only. NeuraFlow never runs these steps itself; they are templates for the customer's administrator to review. Names are validated so they can't carry SQL.

- **Plain-language errors.** Common warehouse failures (wrong password or role, no warehouse, missing grants, blocked IP, bad HTTP path, warehouse starting) are explained with what to change. The database's own message is always shown too.
- **Connection check.** After connecting, NeuraFlow says how many tables and views the account can see, and warns when it connects but sees none (usually missing grants).
- **`NEURAFLOW_EGRESS_IPS`** (optional): comma-separated outbound IPs NeuraFlow connects from. When set, the guide includes the exact network-policy / IP-access-list statement. Leave it unset if your host has no fixed outbound address; the guide then tells the customer to ask you for one.

The scripts have been tested for safety and shape, but not run against a real Snowflake or Databricks account yet. Run them with the first pilot customer before relying on them.

## Public site (`/welcome`)

`/welcome` is a public page for visitors: what NeuraFlow does, how it works, an honest "where it is today" section, a question assistant, and a demo request form. In required workspace mode, visitors who open `/` land here; signed-in people go straight to the app. In the original single-workspace mode, `/` still opens the app.

- **Question assistant.** Answers only from `backend/public/knowledge.md`, a written product description. **Edit that file to change what it can say**, and keep it accurate: it must not claim features, prices, customers or certifications you don't have. It sees no customer data and has no tools. It uses `OPENAI_API_KEY`, so questions go to OpenAI, which the page says. Limits: 15 questions per visitor per hour and `PUBLIC_ASK_DAILY_LIMIT` (default 300) per day in total.
- **Demo requests.** Stored on the server (in `WORKSPACES_DIR`, so it needs the same persistent volume) and listed on `/platform` under Demo requests, where you can mark them handled or delete them. There is no email sending: check `/platform`. Limits: 5 per visitor per hour, plus a hidden spam trap field. The form tells people their details are used only to reply.
- **Live demo (optional).** Create a workspace that starts with **Demo** data, issue it a **viewer** key, and set that key as `PUBLIC_DEMO_KEY`. A "Try the live demo" button then appears and signs visitors in read-only on the sample data. An admin key, or a key for a workspace with real data, is refused. Revoke the key to turn the demo off.
- Don't point `PUBLIC_DEMO_KEY` at anything you wouldn't want the whole internet to read.

### Getting demo requests by email

Set `LEAD_NOTIFY_EMAIL` to where requests should arrive, plus one way to send:

- **Resend (simplest, works on Railway):** create a free account at resend.com using the same email as `LEAD_NOTIFY_EMAIL`, create an API key, and set `RESEND_API_KEY`. With no other setting it sends from `onboarding@resend.dev`, which Resend allows to the account owner's own address. The email's Reply-To is the visitor, so you answer by replying.
- **SMTP (for example Gmail with an app password):** set `SMTP_HOST` (smtp.gmail.com), `SMTP_USERNAME`, `SMTP_PASSWORD` (an app password, not your login password), and optionally `SMTP_PORT` (587 default, 465 for SSL) and `LEAD_FROM_EMAIL`. Some hosts, including Railway on lower plans, block outgoing SMTP; if emails don't arrive, use Resend.

A failed email never loses the request: it is still stored, and `/platform` shows "Email not sent" on it. Requests are only accepted when they can't silently vanish, meaning an email destination is configured or `WORKSPACES_DIR` is set; otherwise the form says requests aren't open yet.

## Putting a password in front of the app (`APP_PASSWORD`)

The quickest way to stop strangers opening the app. Set `APP_PASSWORD` on the backend (Railway) to any long phrase.
Then every page and API call, including the original chat and traceability endpoints, needs it, and the site header
shows **Log in** instead of **Open your workspace** until someone has entered it.

- People with the password can **look**. Changing data still needs `ADMIN_TOKEN`, so set that too.
- It is one shared password for the one original workspace. For separate customers with their own data and their own
  keys, use `WORKSPACE_MODE=required` instead (see Customer workspaces above); it needs a persistent volume.
- Wrong guesses are throttled (20 per 10 minutes per IP). Changing the password logs everyone out.
- Leave `APP_PASSWORD` unset and nothing changes.
