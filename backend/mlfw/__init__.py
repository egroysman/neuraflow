"""A small, auditable ML framework for structured business data.

It sits behind the cash flow model. Structured tables (invoices, vendor bills,
the ledger) become point-in-time datasets, models are validated by walking
forward through time, results are compared with simple baselines, and every
trained model is recorded in a registry. Models run in shadow mode: they are
measured against today's methods and do not change the forecast.
"""
