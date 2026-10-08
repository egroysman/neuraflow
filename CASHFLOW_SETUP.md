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
