"""Cash flow modeling package for NeuraFlow.

Layout
------
models.py  - request/response schema (assumptions, scenarios, adjustments)
ar.py      - receivables projection and data-derived defaults
engine.py  - event-based forecast engine (weekly + monthly roll-ups, KPIs, scenarios)
export.py  - Excel / CSV export
router.py  - FastAPI endpoints mounted under /cashflow
"""
