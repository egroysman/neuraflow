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
  collectability_change_pts: number;
  past_due_delay_days: number;
  top_customer_delay_days: number;
  raise_change_pct_pts: number;
  extra_hires: number;
  bonus_change_pct: number;
  salary_change_pct: number;
  capex_delay_months: number;
  rate_change_pts: number;
  tax_rate_change_pts: number;
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
  opening_ppe_net: number;
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

export type Employee = {
  id: string;
  department: string;
  title: string;
  pay_type: "salary" | "hourly";
  annual_salary: number;
  hourly_rate: number;
  hours_per_week: number;
  hire_date: string;
  term_date: string | null;
  bonus_pct: number;
  benefits_monthly: number;
};

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
    use_roster: boolean;
    employees: Employee[];
    pay_frequency: "biweekly" | "semimonthly" | "monthly";
    next_pay_date: string | null;
    employer_tax_pct: number;
    raise_month: number;
    bonus_month: number;
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
  whatif_impact: Record<WhatIfGroup, { active: boolean; ending_cash_impact: number; lowest_balance_impact: number }>;
  payroll: PayrollResult | null;
  balance_sheet: BalanceSheet;
  gl: GlCompare | null;
  macro: MacroEffect;
};

export type WhatIfGroup = "ar" | "payroll" | "payables" | "capex" | "financing" | "operations";

export type PayrollResult = {
  employees: {
    id: string;
    department: string;
    title: string;
    pay_type: "salary" | "hourly";
    annual_base: number;
    hire_date: string;
    term_date: string | null;
    bonus_pct: number;
    benefits_monthly: number;
    status: "active" | "planned" | "terminated";
  }[];
  active_headcount: number;
  annual_base_active: number;
  monthly: number[];
  headcount: number[];
  by_department: Record<string, number[]>;
  bonus: number[];
  benefits: number[];
  runs: { date: string; gross: number; employer_tax: number; total: number; employees: number }[];
  pay_frequency: "biweekly" | "semimonthly" | "monthly";
  total_cost: number;
  total_cash: number;
};

export type BalanceRow = {
  label: string;
  cash: number;
  receivables: number;
  ppe_net: number;
  total_assets: number;
  payables: number;
  accrued_payroll: number;
  taxes_payable: number;
  debt: number;
  total_liabilities: number;
  equity: number;
  total_liabilities_equity: number;
  check: number;
  working_capital: number;
  net_debt: number;
  net_income?: number;
};

export type BalanceSheet = {
  opening: BalanceRow;
  months: BalanceRow[];
  max_abs_check: number;
  memo: { existing_ar_expected_uncollectible: number; new_sales_expected_uncollectible: number; ar_ending: number };
};

export type GlCompare = {
  timeline: {
    label: string;
    actual_revenue: number | null;
    actual_costs: number | null;
    actual_pretax: number | null;
    forecast_revenue: number | null;
    forecast_costs: number | null;
    forecast_pretax: number | null;
  }[];
  baseline_check: { label: string; actual_avg: number; forecast_first_month: number; difference: number; difference_pct: number | null }[];
  variance: { label: string; approximate: boolean; lines: { label: string; actual: number; forecast: number; variance: number }[] }[];
  baseline_window: string[];
  history_months: number;
};

export type GlBaselines = {
  window_months: string[];
  monthly_revenue: number;
  cogs_pct: number;
  payroll_monthly: number;
  opex_monthly: Record<string, number>;
  depreciation_monthly: number;
  starting_cash: number;
  receivables: number;
  payables: number;
  ppe_net: number;
  loan: { balance: number; monthly_payment: number; annual_rate_pct: number } | null;
};

export type GlOverview =
  | { available: false }
  | {
      available?: undefined;
      as_of: string;
      first_date: string;
      last_date: string;
      entry_count: number;
      line_count: number;
      accounts: { account_id: string; name: string; type: string; subtype: string; model_line: string }[];
      trial_balance: {
        rows: { account_id: string; name: string; type: string; subtype: string; debit_balance: number; credit_balance: number; balance: number }[];
        total_debit: number;
        total_credit: number;
        balanced: boolean;
      };
      monthly: {
        month: string;
        label: string;
        partial: boolean;
        revenue: number;
        cogs: number;
        payroll: number;
        opex: number;
        depreciation: number;
        interest: number;
        pretax_profit: number;
      }[];
      baselines: GlBaselines | null;
      tie_out: { label: string; ledger: number; source: number; difference: number; ok: boolean }[];
      recent_entries: { entry: string; date: string; account: string; debit: number; credit: number; memo: string; source: string }[];
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
    planned_date: string;
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
    driven_by_gl?: string[];
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
  collectability_change_pts: 0,
  past_due_delay_days: 0,
  top_customer_delay_days: 0,
  raise_change_pct_pts: 0,
  extra_hires: 0,
  bonus_change_pct: 0,
  salary_change_pct: 0,
  capex_delay_months: 0,
  rate_change_pts: 0,
  tax_rate_change_pts: 0,
};

export type TabId = "forecast" | "receivables" | "payroll" | "balance" | "gl" | "payables" | "capex" | "trends";
