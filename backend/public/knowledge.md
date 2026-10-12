# NeuraFlow: what it is (the only source the public assistant may use)

NeuraFlow is a finance application for private companies. It does two main things from a company's own accounting data:
1. Cash flow forecasting: an event-based forecast of cash, profit and loss and the balance sheet, month by month, with about 30 "what-if" controls (for example slower customer payments, a delayed hire, a bigger purchase) and scenario presets. It also has standard projections.
2. Payment-behavior credit scoring: a score and risk band for each of the company's customers, based on how that customer has actually paid invoices (days to pay, lateness, trend), with plain-language reasons for each score. A back-test replays the score at past dates and compares it with what customers did next, and the underlying rows can be downloaded to audit the numbers.

## Screens
Cash Flow (forecast, receivables, payroll, payables, capital purchases, balance sheet, general ledger, credit score, trends), Models, and Data. Each tab has its own what-ifs and its own assistant that answers questions from the numbers on that tab.

## Using your own data
- Upload a CSV or Excel file, or connect Snowflake or Databricks, or point NeuraFlow at an SFTP folder where files are dropped; it can load the newest file on a schedule.
- It suggests how your columns match its fields and you confirm. It checks the data (dates, amounts, duplicates, missing values) and refuses to load data that fails the checks. A refresh never replaces good data with bad or much smaller data.
- Datasets: customer invoices, vendor bills, chart of accounts, journal lines, payroll.
- Connections are read-only. For Snowflake and Databricks the app includes a setup guide that writes the steps for your administrator to create a read-only account.
- The Snowflake, Databricks and SFTP connectors are built and tested with simulated systems; they are being proven on real customer accounts with early customers.

## Customer workspaces and security
- Each customer gets a private workspace with its own data, connections and models. Customers sign in with an access key (admin or viewer). Viewers can look but not change anything. Keys can be revoked at any time.
- Saved connection passwords and tokens are encrypted, each workspace with its own key, and are never shown again.
- Assistant questions are sent to an AI provider (OpenAI) together with the numbers needed to answer them.
- NeuraFlow does not currently hold a SOC 2 or similar certification. Do not claim any.

## Machine learning
NeuraFlow includes machine-learning models that run quietly in "shadow mode" beside simple rules. A model is only trusted if it clearly beats the simple rule on held-out data. On the built-in sample data the models do not beat the simple rules, and the app says so. The credit score on real data should be treated as a decision aid and checked with the back-test on the customer's own history.

## Limits and honesty
- The credit score is about business customers' payment behavior. It is not a consumer credit report and is not a lending decision.
- Results depend on the data connected. Small or short histories give less reliable scores.
- NeuraFlow is an early product. Pricing is not published; a demo request is the way to discuss it.
- The built-in demo uses sample data, clearly labelled.
