"""Schema for the cash flow model.

Everything the user can edit lives in ``Assumptions``. Scenario presets and the
what-if sliders are expressed as ``Adjustments`` that are layered on top of the
assumptions, so the underlying assumptions are never mutated by a scenario.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Assumption building blocks
# --------------------------------------------------------------------------- #


class General(BaseModel):
    as_of: dt.date = Field(description="Forecast start date (day 0)")
    horizon_months: int = Field(12, ge=3, le=24)
    starting_cash: float = Field(0, ge=-1e10, le=1e10)
    min_cash: float = Field(0, ge=0, le=1e10, description="Minimum cash the business wants to hold")
    tax_rate_pct: float = Field(25, ge=0, le=60, description="Paid quarterly on positive pre-tax profit")


class Sales(BaseModel):
    monthly_revenue: float = Field(0, ge=0, le=1e10, description="New invoicing per month at month 0")
    growth_pct_monthly: float = Field(0, ge=-20, le=30)
    dso_days: float = Field(45, ge=0, le=240, description="Days from invoice to cash on new sales")
    bad_debt_pct: float = Field(1, ge=0, le=100, description="Share of new sales never collected")


class Costs(BaseModel):
    cogs_pct: float = Field(40, ge=0, le=100, description="Cost of sales as % of revenue")
    dpo_days: float = Field(30, ge=0, le=240, description="Days from cost incurred to vendor payment")
    opening_ap: float = Field(0, ge=0, le=1e10, description="Vendor payables owed at the start date")


class Hire(BaseModel):
    month: int = Field(ge=0, le=60)
    count: int = Field(ge=1, le=500)


class Payroll(BaseModel):
    headcount: int = Field(0, ge=0, le=5000)
    avg_salary: float = Field(0, ge=0, le=5e6, description="Average annual salary per head")
    burden_pct: float = Field(20, ge=0, le=100, description="Taxes and benefits on top of salary")
    salary_growth_pct_annual: float = Field(3, ge=-20, le=50)
    hires: List[Hire] = Field(default_factory=list)


class OpexLine(BaseModel):
    name: str = Field(max_length=80)
    kind: Literal["fixed", "pct_revenue"] = "fixed"
    amount: float = Field(0, ge=0, le=1e10, description="$/month if fixed, % of revenue if pct_revenue")
    growth_pct_monthly: float = Field(0, ge=-20, le=20, description="Only applies to fixed lines")
    start_month: int = Field(0, ge=0, le=60)
    end_month: Optional[int] = Field(None, ge=0, le=60)


class Loan(BaseModel):
    name: str = Field(max_length=80)
    balance: float = Field(0, ge=0, le=1e10)
    annual_rate_pct: float = Field(0, ge=0, le=60)
    monthly_payment: float = Field(0, ge=0, le=1e10)


class OneTimeItem(BaseModel):
    name: str = Field(max_length=80)
    date: dt.date
    amount: float = Field(description="Positive = cash in, negative = cash out")
    category: Literal["operating", "investing", "financing"] = "operating"


class Collectability(BaseModel):
    """Percent of open receivables expected to be collected, by days past due."""

    current: float = Field(98, ge=0, le=100)
    d1_30: float = Field(95, ge=0, le=100)
    d31_60: float = Field(88, ge=0, le=100)
    d61_90: float = Field(78, ge=0, le=100)
    d91_180: float = Field(60, ge=0, le=100)
    d180_plus: float = Field(40, ge=0, le=100)


class OverdueLag(BaseModel):
    """Days from the start date until an invoice already past its usual
    payment pattern is expected to be paid, by days past due."""

    current: float = Field(7, ge=0, le=365)
    d1_30: float = Field(14, ge=0, le=365)
    d31_60: float = Field(28, ge=0, le=365)
    d61_90: float = Field(42, ge=0, le=365)
    d91_180: float = Field(70, ge=0, le=365)
    d180_plus: float = Field(120, ge=0, le=365)


class Collections(BaseModel):
    collectability_pct: Collectability = Field(default_factory=Collectability)
    overdue_lag_days: OverdueLag = Field(default_factory=OverdueLag)


class Assumptions(BaseModel):
    general: General
    sales: Sales = Field(default_factory=Sales)
    costs: Costs = Field(default_factory=Costs)
    payroll: Payroll = Field(default_factory=Payroll)
    opex: List[OpexLine] = Field(default_factory=list, max_length=60)
    loans: List[Loan] = Field(default_factory=list, max_length=20)
    one_time: List[OneTimeItem] = Field(default_factory=list, max_length=100)
    collections: Collections = Field(default_factory=Collections)


# --------------------------------------------------------------------------- #
# Scenarios and what-if adjustments
# --------------------------------------------------------------------------- #


class Adjustments(BaseModel):
    collection_delay_days: int = Field(0, ge=-60, le=120)
    extra_bad_debt_pct: float = Field(0, ge=0, le=50)
    revenue_change_pct: float = Field(0, ge=-80, le=100)
    growth_change_pct_pts: float = Field(0, ge=-10, le=10)
    cogs_change_pct_pts: float = Field(0, ge=-30, le=30)
    opex_change_pct: float = Field(0, ge=-50, le=100)
    dpo_change_days: int = Field(0, ge=-60, le=120)

    def plus(self, other: "Adjustments") -> "Adjustments":
        return Adjustments(
            **{
                name: getattr(self, name) + getattr(other, name)
                for name in type(self).model_fields
            }
        )


Scenario = Literal["base", "best", "worst"]

SCENARIO_PRESETS: Dict[str, Adjustments] = {
    "base": Adjustments(),
    "best": Adjustments(
        collection_delay_days=-7,
        extra_bad_debt_pct=0,
        revenue_change_pct=5,
        growth_change_pct_pts=0.5,
        cogs_change_pct_pts=-1,
        opex_change_pct=-3,
        dpo_change_days=5,
    ),
    "worst": Adjustments(
        collection_delay_days=21,
        extra_bad_debt_pct=5,
        revenue_change_pct=-10,
        growth_change_pct_pts=-1,
        cogs_change_pct_pts=2,
        opex_change_pct=3,
        dpo_change_days=-10,
    ),
}

SCENARIO_LABELS = {"base": "Base case", "best": "Best case", "worst": "Worst case"}


class ForecastRequest(BaseModel):
    assumptions: Assumptions
    scenario: Scenario = "base"
    adjustments: Adjustments = Field(default_factory=Adjustments)
