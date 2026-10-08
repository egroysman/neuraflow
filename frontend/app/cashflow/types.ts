// Mirrors backend/cashflow/models.py and the /cashflow/forecast response.

export type Scenario = "base" | "best" | "worst";
export type View = "monthly" | "weekly";

export type Bucket =
  | "current"
  | "d1_30"
  | "d31_60"
  | "d61_90"
  | "d91_180"
  | "d180_plus";

export type Adjustments = {
  collection_delay_days: number;
  extra_bad_debt_pct: number;
  revenue_change_pct: number;
  growth_change_pct_pts: number;
  cogs_change_pct_pts: number;
  opex_change_pct: number;
  dpo_change_days: number;
  capex_change_pct: number;
};

export type OpexLine = {
  name: string;
  kind: "fixed" | "pct_revenue";
  amount: number;
  growth_pct_monthly: number;
  start_month: number;
  end_month: number | null;
};

export type Loan = {
  name: string;
  balance: number;
  annual_rate_pct: number;
  monthly_payment: number;
  floating: boolean;
};

export type APSettings = {
  use_open_bills: boolean;
  payment_lag_days: number;
  overdue_catchup_days: number;
};

export type CapexCategory = "equipment" | "software" | "facilities" | "vehicles" | "other";
export type CapexItem = {
  name: string;
  category: CapexCategory;
  date: string;
  amount: number;
  kind: "maintenance" | "growth";
  funding: "cash" | "loan" | "lease";
  down_payment_pct: number;
  term_months: number;
  annual_rate_pct: number;
  useful_life_months: number;
};

export type CapexPlan = {
  maintenance_pct_revenue: number;
  maintenance_life_months: number;
  existing_depreciation_monthly: number;
  growth_revenue_link: number;
  items: CapexItem[];
};

export type MacroInputs = {
  apply: boolean;
  rate_change_pts: number;
  cost_inflation_pct: number;
  demand_growth_pct: number;
};

export type OneTimeItem = {
  name: string;
  date: string;
  amount: number;
  category: "operating" | "investing" | "financing";
};

export type Hire = { month: number; count: number };

export type Assumptions = {
  general: {
    as_of: string;
    horizon_months: number;
    starting_cash: number;
    min_cash: number;
    tax_rate_pct: number;
  };
  sales: {
    monthly_revenue: number;
    growth_pct_monthly: number;
    dso_days: number;
    bad_debt_pct: number;
  };
  costs: { cogs_pct: number; dpo_days: number; opening_ap: number };
  payroll: {
    headcount: number;
    avg_salary: number;
    burden_pct: number;
    salary_growth_pct_annual: number;
    hires: Hire[];
  };
  opex: OpexLine[];
  loans: Loan[];
  one_time: OneTimeItem[];
  collections: {
    collectability_pct: Record<Bucket, number>;
    overdue_lag_days: Record<Bucket, number>;
  };
  ap: APSettings;
  capex: CapexPlan;
  macro: MacroInputs;
};

export type Period = {
  index: number;
  label: string;
  start: string;
  end: string;
  categories: Record<string, number>;
  operating: number;
  investing: number;
  financing: number;
  net: number;
  begin_cash: number;
  end_cash: number;
  below_min: boolean;
};

export type Kpis = {
  starting_cash: number;
  ending_cash: number;
  net_cash_flow: number;
  cash_in: number;
  cash_out: number;
  lowest_balance: number;
  lowest_balance_date: string;
  first_below_min_date: string | null;
  first_negative_date: string | null;
  runway_months: number | null;
  avg_monthly_burn: number;
  funding_gap: number;
  operating_cash_flow: number;
  investing_cash_flow: number;
  financing_cash_flow: number;
};

export type Category = {
  key: string;
  label: string;
  section: "operating" | "investing" | "financing";
};

export type Alert = { level: "danger" | "warning" | "info"; message: string };

export type ScenarioSummary = {
  label: string;
  monthly_end_cash: number[];
  weekly_end_cash: number[];
  ending_cash: number;
  lowest_balance: number;
  first_negative_date: string | null;
};

export type AgingRow = {
  bucket: Bucket;
  label: string;
  open_amount: number;
  invoices: number;
};

export type CustomerRow = {
  customer_id: string;
  open_invoices: number;
  open_amount: number;
  expected_in_horizon: number;
  avg_days_to_pay: number | null;
  oldest_days_past_due: number;
  risk: "Low" | "Medium" | "High";
};

export type Forecast = {
  scenario: Scenario;
  scenario_label: string;
  effective_adjustments: Adjustments;
  as_of: string;
  horizon_end: string;
  categories: Category[];
  monthly: Period[];
  weekly: Period[];
  pnl: {
    label: string;
    revenue: number;
    cogs: number;
    gross_profit: number;
    payroll: number;
    opex: number;
    depreciation: number;
    interest: number;
    pretax_profit: number;
  }[];
  kpis: { monthly: Kpis; weekly: Kpis };
  alerts: Alert[];
  comparison: Record<Scenario, ScenarioSummary>;
  ar: {
    open_total: number;
    expected_total: number;
    expected_in_horizon: number;
    expected_haircut: number;
    aging: AgingRow[];
    customers: CustomerRow[];
  };
  ap: ApSummary;
  capex: CapexResult;
  macro: MacroEffect;
};

export type ApBucket = "current" | "d1_30" | "d31_60" | "d61_90" | "d90_plus";
export type ApSummary = {
  bill_count: number;
  vendor_count: number;
  open_total: number;
  open_bills: number;
  overdue_total: number;
  overdue_pct: number;
  actual_dpo_days: number | null;
  typical_lag_days: number;
  aging: { bucket: ApBucket; label: string; open_amount: number; bills: number }[];
  vendors: {
    vendor_id: string;
    vendor_name: string;
    category: string;
    open_amount: number;
    bills: number;
    oldest_days_past_due: number;
    avg_days_to_pay: number | null;
    avg_days_vs_due: number | null;
    share_pct: number;
  }[];
  top3_share_pct: number;
  by_category: { category: string; open_amount: number }[];
  due_by_month: { month: string; amount: number }[];
  upcoming: {
    bill_id: string;
    vendor_name: string;
    category: string;
    due_date: string;
    expected_date: string;
    days_past_due: number;
    open_amount: number;
  }[];
  monthly_spend: { month: string; amount: number }[];
  using_bills: boolean;
  opening_ap_lump: number;
};

export type CapexResult = {
  items: (CapexItem & {
    planned_amount: number;
    in_horizon: boolean;
    cash_at_purchase: number;
    financed: number;
    monthly_payment: number;
    payments_in_horizon: number;
    depreciation_monthly: number;
  })[];
  monthly: {
    index: number;
    label: string;
    maintenance: number;
    growth: number;
    cash_capex: number;
    financed_payments: number;
    interest: number;
    additions: number;
    depreciation: number;
    net_additions_cum: number;
  }[];
  totals: {
    cash_capex: number;
    maintenance: number;
    growth: number;
    financed_payments: number;
    interest: number;
    depreciation: number;
    total_additions: number;
    financed_amount: number;
    growth_scale: number;
  };
};

export type MacroEffect = {
  applied: boolean;
  rate_change_pts: number;
  cost_inflation_pct: number;
  demand_growth_pct: number;
  ending_cash_impact: number;
  lowest_balance_impact: number;
};

export type TrendSignal = {
  key: string;
  label: string;
  current: number;
  previous: number;
  change: number;
  change_unit: string;
  unit: string;
  tone: "good" | "bad" | "neutral";
  note: string;
  window_months: number;
};

export type TrendMonth = {
  month: string;
  label: string;
  partial: boolean;
  partial_reason: "start" | "end" | null;
  invoiced: number;
  collected: number;
  avg_days_to_pay: number | null;
  on_time_pct: number | null;
  open_ar: number;
  past_due_pct: number | null;
  vendor_billed: number;
  vendor_days_to_pay: number | null;
};

export type Trends = {
  as_of: string;
  caveats: string[];
  months: TrendMonth[];
  signals: TrendSignal[];
  implied: { growth: { monthly_growth_pct: number; months_used: number } | null; days_to_pay: number | null };
  concentration: {
    window_months: number;
    customers: number;
    top1_pct: number;
    top5_pct: number;
    top_customers: { customer_id: string; amount: number; share_pct: number }[];
  };
  seasonality: { index: { month: number; index: number }[] } | null;
  seasonality_note: string | null;
};

export type MacroSeries = {
  key: string;
  fred_id: string;
  label: string;
  unit: string;
  latest: number;
  latest_date: string;
  year_ago: number | null;
  change_12m: number | null;
  history: { date: string; value: number }[];
};

export type MacroData = {
  status: "live" | "partial" | "stale" | "unavailable";
  source: string;
  fetched_at: string | null;
  series: MacroSeries[];
  suggestions: Partial<Record<"rate_change_pts" | "cost_inflation_pct" | "demand_growth_pct", { value: number; basis: string }>>;
  errors: string[];
  norm_pct: number;
};

export type Defaults = {
  assumptions: Assumptions;
  data_summary: {
    invoice_count: number;
    customer_count: number;
    as_of: string;
    first_invoice_date: string | null;
    last_invoice_date: string | null;
    monthly_revenue: number;
    dso_days: number;
    open_ar: number;
    open_invoice_count: number;
    collections_calibration: {
      calibrated: boolean;
      follow_days: number;
      snapshots: number;
    };
    ap: {
      bill_count: number;
      vendor_count: number;
      open_ap: number;
      open_bill_count: number;
      typical_lag_days: number;
      actual_dpo_days: number | null;
      last_bill_date: string | null;
    } | null;
  };
  scenarios: Record<Scenario, { label: string; adjustments: Adjustments }>;
  note: string;
};

export const NO_ADJUSTMENTS: Adjustments = {
  collection_delay_days: 0,
  extra_bad_debt_pct: 0,
  revenue_change_pct: 0,
  growth_change_pct_pts: 0,
  cogs_change_pct_pts: 0,
  opex_change_pct: 0,
  dpo_change_days: 0,
  capex_change_pct: 0,
};

export type TabId = "forecast" | "payables" | "capex" | "trends";
