export type DatasetKey = "invoices" | "bills" | "gl_accounts" | "gl_journal" | "payroll";

export type Schedule = { mode: "off" | "interval" | "daily"; every_minutes?: number; at?: string; timezone?: string };
export type LastRun = { at: number; ok: boolean; rows_in: number; rows_out: number; message: string; trigger: string };

export type DatasetStatus = {
  key: DatasetKey;
  label: string;
  description: string;
  configured: boolean;
  source?: string;
  rows?: number;
  last_run?: LastRun;
  schedule?: Schedule;
  next_run?: number | null;
  stats?: { date_range?: string[] | null; customers?: number; vendors?: number; employees?: number } | null;
  version?: number;
  source_kind?: "upload" | "connection";
  connection_id?: string;
  ghost?: { pattern: string; state?: { at: number; ok: boolean; message: string } };
};

export type DataStatus = {
  mode: "sample" | "custom";
  empty?: boolean;
  datasets: DatasetStatus[];
  warnings: string[];
  admin: { enabled: boolean; token_required: boolean };
  encryption_ready: boolean;
  storage: { path_set: boolean; note: string | null };
  ghost: { enabled: boolean; schedule?: Schedule | null; connection_id?: string | null; patterns?: Record<string, string>; source?: "workspace" | "server" | null };
  limits: { max_upload_mb: number; row_limit: number };
};

export type ConnType = "snowflake" | "databricks" | "sftp";
export type Connection = { id: string; name: string; type: ConnType; env: boolean; params: Record<string, string | number | boolean>; secrets_set: string[] };

export type Source = { kind: "upload" | "connection"; upload_id?: string; connection_id?: string; object?: string; sheet?: string; header_row?: number };
export type SourceObject = { name: string; kind: string; detail: string };

export type FieldSpec = { name: string; label: string; kind: string; required: boolean; help: string };
export type Issue = { level: "error" | "warning" | "info"; message: string };
export type Analysis = {
  dataset: DatasetKey;
  columns: string[];
  row_count: number;
  truncated: boolean;
  raw_sample: Record<string, string | number | boolean | null>[];
  fields: FieldSpec[];
  at_least_one_of: string[][];
  suggestions: Record<string, { column: string; confidence: number; reason: string; samples: string[] }>;
  mapping: Record<string, string | null>;
  options: Record<string, unknown>;
  mapped_sample: Record<string, string | number>[];
  report: { rows_in: number; rows_out: number; dropped: Record<string, number>; notes: string[]; ambiguous_dates?: boolean };
  classified: { AccountID: string; AccountName: string; AccountType: string; ModelLine: string; inferred: boolean }[] | null;
  validation: { ok: boolean; issues: Issue[]; stats: Record<string, unknown> };
};

export type ActivityEvent = { at: number; actor: string; action: string; detail: string };
export type SetupStep = { title: string; text: string; sql?: string; optional?: boolean };
export type SetupGuide = { type: ConnType; steps: SetupStep[]; fill: Record<string, string>; then: string; egress_ips: string[] };
export type Hint = { code: string; title: string; fix: string };
export type TestResult = { ok: boolean; message: string; warning?: string; tables?: number; needs_host_key?: boolean; host_key_sha256?: string };
