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
