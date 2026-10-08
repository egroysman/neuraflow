"""Schema for the cash flow model.

Everything the user can edit lives in ``Assumptions``. Scenario presets and the
what-if sliders are expressed as ``Adjustments`` that are layered on top of the
assumptions, so the underlying assumptions are never mutated by a scenario.
"""
from __future__ import annotations

import datetime as dt
from typing import ClassVar, Dict, List, Literal, Optional

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


class Employee(BaseModel):
    id: str = Field(max_length=40)
    department: str = Field("General", max_length=60)
    title: str = Field("", max_length=80)
    pay_type: Literal["salary", "hourly"] = "salary"
    annual_salary: float = Field(0, ge=0, le=5e7)
    hourly_rate: float = Field(0, ge=0, le=5e4)
    hours_per_week: float = Field(40, ge=0, le=100)
    hire_date: dt.date
    term_date: Optional[dt.date] = None
    bonus_pct: float = Field(0, ge=0, le=500, description="Annual bonus as % of base pay")
    benefits_monthly: float = Field(0, ge=0, le=1e6, description="Employer benefits cost per month")

    def annual_base(self) -> float:
        if self.pay_type == "hourly":
            return self.hourly_rate * self.hours_per_week * 52.0
        return self.annual_salary


class Payroll(BaseModel):
    use_roster: bool = Field(False, description="Build payroll from the employee roster and pay runs")
    employees: List[Employee] = Field(default_factory=list, max_length=500)
    pay_frequency: Literal["biweekly", "semimonthly", "monthly"] = "biweekly"
    next_pay_date: Optional[dt.date] = Field(None, description="First pay run on or after the start date")
    employer_tax_pct: float = Field(8.5, ge=0, le=60, description="Employer payroll taxes on wages and bonuses (roster mode)")
    raise_month: int = Field(1, ge=1, le=12, description="Calendar month annual raises take effect")
    bonus_month: int = Field(12, ge=1, le=12, description="Calendar month bonuses are paid")
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
    floating: bool = Field(False, description="Rate floats with the macro rate overlay")


class AP(BaseModel):
    """How open vendor bills are turned into payments."""

    use_open_bills: bool = Field(True, description="Pay the open vendor bills one by one (falls back to a lump if no bills)")
    payment_lag_days: float = Field(0, ge=-30, le=120, description="Days after the due date you typically pay")
    overdue_catchup_days: int = Field(14, ge=0, le=120, description="Bills already past due are paid within this many days")


CapexCategory = Literal["equipment", "software", "facilities", "vehicles", "other"]


class CapexItem(BaseModel):
    name: str = Field(max_length=80)
    category: CapexCategory = "equipment"
    date: dt.date
    amount: float = Field(0, ge=0, le=1e10, description="Full purchase price")
    kind: Literal["maintenance", "growth"] = "growth"
    funding: Literal["cash", "loan", "lease"] = "cash"
    down_payment_pct: float = Field(20, ge=0, le=100, description="Paid in cash at purchase when financed")
    term_months: int = Field(36, ge=1, le=120)
    annual_rate_pct: float = Field(8, ge=0, le=60)
    useful_life_months: int = Field(60, ge=3, le=360, description="Straight-line depreciation period")


class Capex(BaseModel):
    maintenance_pct_revenue: float = Field(0, ge=0, le=50, description="Recurring maintenance capex as % of revenue")
    maintenance_life_months: int = Field(60, ge=6, le=360)
    existing_depreciation_monthly: float = Field(0, ge=0, le=1e9, description="Depreciation on assets you already own")
    opening_ppe_net: float = Field(0, ge=0, le=1e10, description="Net book value of property and equipment you own at the start date")
    growth_revenue_link: float = Field(0.5, ge=0, le=1, description="Share of a scenario revenue change that growth capex follows")
    items: List[CapexItem] = Field(default_factory=list, max_length=100)


class Macro(BaseModel):
    """Macro overlay: layered on top of the other assumptions when ``apply`` is on."""

    apply: bool = False
    rate_change_pts: float = Field(0, ge=-10, le=10, description="Change in benchmark rates, applied to floating loans and new financed capex")
    cost_inflation_pct: float = Field(0, ge=-10, le=30, description="Extra annual inflation on fixed opex and salaries")
    demand_growth_pct: float = Field(0, ge=-30, le=30, description="Extra annual demand growth on new sales")


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
    ap: AP = Field(default_factory=AP)
    capex: Capex = Field(default_factory=Capex)
    macro: Macro = Field(default_factory=Macro)


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
    capex_change_pct: float = Field(0, ge=-100, le=200, description="Growth capex up/down")
    # receivables
    collectability_change_pts: float = Field(0, ge=-50, le=20, description="Points added to the collectability of existing receivables")
    past_due_delay_days: int = Field(0, ge=0, le=120, description="Extra days before already-late invoices are paid")
    top_customer_delay_days: int = Field(0, ge=0, le=120, description="Extra days before the customer owing the most pays")
    # payroll
    raise_change_pct_pts: float = Field(0, ge=-10, le=20, description="Added to the annual raise")
    extra_hires: int = Field(0, ge=0, le=50, description="Additional hires starting next month at the average base pay")
    bonus_change_pct: float = Field(0, ge=-100, le=200, description="Scales bonuses")
    salary_change_pct: float = Field(0, ge=-30, le=50, description="Across-the-board change to base pay")
    # capex, financing, tax
    capex_delay_months: int = Field(0, ge=0, le=24, description="Push growth capex later")
    rate_change_pts: float = Field(0, ge=-10, le=10, description="Change in rates on floating loans and new financed capex")
    tax_rate_change_pts: float = Field(0, ge=-30, le=30, description="Added to the income tax rate")
    # payables
    bill_catchup_extra_days: int = Field(0, ge=0, le=120, description="Extra days to clear bills that are already past due")
    top_vendor_delay_days: int = Field(0, ge=0, le=120, description="Extra days before the vendor you owe most is paid")
    # payroll extras
    benefits_change_pct: float = Field(0, ge=-50, le=100, description="Scales employee benefits cost")
    employer_tax_change_pts: float = Field(0, ge=-5, le=10, description="Added to employer payroll taxes")
    # capex extras
    maintenance_capex_change_pct: float = Field(0, ge=-100, le=300, description="Scales maintenance capex")
    down_payment_change_pts: float = Field(0, ge=-20, le=60, description="Added to the down payment on financed purchases")
    # balance sheet
    extra_loan_payment: float = Field(0, ge=0, le=1e6, description="Extra principal paid each month on the first loan")
    equity_injection: float = Field(0, ge=-1e7, le=1e7, description="Cash put in (+) or taken out (-) by owners at the start")
    # ledger / other cash
    starting_cash_change: float = Field(0, ge=-1e7, le=1e7, description="Starting cash is higher or lower than the ledger says")
    other_monthly_cash: float = Field(0, ge=-1e6, le=1e6, description="Other operating cash in (+) or out (-) each month")
    one_time_cash_item: float = Field(0, ge=-1e7, le=1e7, description="A one-off cash item in month 3")
    # trends
    seasonal_swing_pct: float = Field(0, ge=0, le=60, description="Sales swing seasonally: peak in December, low in June")
    top_customer_loss_pct: float = Field(0, ge=0, le=100, description="Share of the largest customer's sales that goes away")
    new_sales_dso_change_days: int = Field(0, ge=-30, le=90, description="Change in days-to-pay on new sales only")

    GROUPS: ClassVar[Dict[str, List[str]]] = {
        "ar": ["collection_delay_days", "extra_bad_debt_pct", "collectability_change_pts", "past_due_delay_days", "top_customer_delay_days"],
        "payroll": ["raise_change_pct_pts", "extra_hires", "bonus_change_pct", "salary_change_pct", "benefits_change_pct", "employer_tax_change_pts"],
        "payables": ["dpo_change_days", "cogs_change_pct_pts", "bill_catchup_extra_days", "top_vendor_delay_days"],
        "capex": ["capex_change_pct", "capex_delay_months", "maintenance_capex_change_pct", "down_payment_change_pts"],
        "financing": ["rate_change_pts", "tax_rate_change_pts", "extra_loan_payment", "equity_injection"],
        "ledger": ["starting_cash_change", "other_monthly_cash", "one_time_cash_item"],
        "trends": ["seasonal_swing_pct", "top_customer_loss_pct", "new_sales_dso_change_days"],
        "operations": ["revenue_change_pct", "growth_change_pct_pts", "opex_change_pct"],
    }

    def without(self, group: str) -> "Adjustments":
        data = self.model_dump()
        for name in self.GROUPS[group]:
            data[name] = 0
        return Adjustments(**data)

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
