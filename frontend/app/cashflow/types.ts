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
};
