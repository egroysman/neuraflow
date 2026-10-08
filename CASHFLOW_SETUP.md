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
