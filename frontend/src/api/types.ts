// Mirrors backend/app/schemas/*.py and backend/app/models/enums.py. Datetimes are ISO-8601 strings.

export type TriageStatus = "new" | "saved" | "dismissed";
export type AppStatus =
  | "saved"
  | "preparing"
  | "applied"
  | "interviewing"
  | "offer"
  | "rejected"
  | "withdrawn"
  | "accepted";
export type RunStatus = "running" | "ok" | "error" | "timeout";
export type RunTrigger = "manual" | "schedule";
export type AppointmentKind = "deadline" | "interview" | "other";
export type AttachmentKind = "cv" | "cover_letter" | "other";

export type FitRating = "good" | "moderate" | "poor";
export type FitStatus = "queued" | "running" | "done" | "error";
export type FitFilterValue = FitRating | "none";
export type FeedSort = "first_seen_at" | "published_at" | "fit";

export const TRIAGE_STATUSES: TriageStatus[] = ["new", "saved", "dismissed"];
export const APPOINTMENT_KINDS: AppointmentKind[] = ["deadline", "interview", "other"];
export const ATTACHMENT_KINDS: AttachmentKind[] = ["cv", "cover_letter", "other"];

// --- feed ---

export interface FeedFilter {
  triage?: TriageStatus[];
  source?: string[];
  profile_id?: number | null;
  q?: string | null;
  location?: string | null;
  radius_km?: number | null;
  found_after?: string | null;
  found_before?: string | null;
  published_after?: string | null;
  employment_type?: string | null;
  remote?: boolean | null;
  fit?: FitFilterValue[];
  sort?: FeedSort;
  offset?: number;
  limit?: number;
}

export interface PostingOut {
  id: number;
  source: string;
  external_id: string;
  url: string | null;
  title: string | null;
  company: string | null;
  location: string | null;
  lat: number | null;
  lon: number | null;
  description: string | null;
  published_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  employment_type: string | null;
  remote: boolean | null;
  contract_type: string | null;
  triage_status: TriageStatus;
  triaged_at: string | null;
  profile_ids: number[];
  application_id: number | null;
  fit: FitOut | null;
}

export interface FitOut {
  rating: FitRating | null;
  status: FitStatus;
  error: string | null;
  explanation: string | null;
  evaluated_at: string | null;
  outdated: boolean;
}

export interface FitItemOut {
  posting_id: number;
  fit: FitOut | null;
}

export interface CancelOut {
  cancelled: number;
}

export interface FitStatusOut {
  profile: boolean;
  configured: boolean;
  active: number;
}

export interface EnqueueOut {
  queued: number;
  limit_exceeded: boolean;
}

export interface CountOut {
  count: number;
}

export interface PostingDetail extends PostingOut {
  raw: Record<string, unknown> | null;
}

export interface FeedPage {
  items: PostingOut[];
  total: number;
}

export interface ManualPostingIn {
  title: string;
  company?: string | null;
  location?: string | null;
  url?: string | null;
  description?: string | null;
  published_at?: string | null;
  employment_type?: string | null;
  remote?: boolean | null;
  contract_type?: string | null;
}

export interface FromUrlIn {
  url: string;
}

// --- applications ---

export interface StatusChangeOut {
  id: number;
  application_id: number;
  from_status: AppStatus | null;
  to_status: AppStatus;
  changed_at: string;
  comment: string | null;
}

export interface AppointmentOut {
  id: number;
  application_id: number;
  kind: AppointmentKind;
  starts_at: string;
  note: string | null;
}

export interface AppointmentIn {
  kind?: AppointmentKind;
  starts_at: string;
  note?: string | null;
}

export interface AppointmentPatch {
  kind?: AppointmentKind;
  starts_at?: string;
  note?: string | null;
}

export interface ContactOut {
  id: number;
  application_id: number;
  name: string;
  role: string | null;
  email: string | null;
  phone: string | null;
}

export interface ContactIn {
  name: string;
  role?: string | null;
  email?: string | null;
  phone?: string | null;
}

export interface ContactPatch {
  name?: string;
  role?: string | null;
  email?: string | null;
  phone?: string | null;
}

export interface AttachmentOut {
  id: number;
  application_id: number;
  filename: string;
  display_name: string;
  stored_path: string;
  kind: AttachmentKind;
  created_at: string;
}

export interface ApplicationOut {
  id: number;
  status: AppStatus;
  created_at: string;
  updated_at: string;
  salary_expectation: string | null;
  channel: string | null;
  notes: string | null;
  posting: PostingOut;
  last_status_change_at: string | null;
}

export interface ApplicationDetailOut extends ApplicationOut {
  status_changes: StatusChangeOut[];
  appointments: AppointmentOut[];
  contacts: ContactOut[];
  attachments: AttachmentOut[];
}

export interface ApplicationPatch {
  salary_expectation?: string | null;
  channel?: string | null;
  notes?: string | null;
}

export interface StatusChangeIn {
  to: AppStatus;
  comment?: string | null;
}

// --- profiles ---

export interface ProfileIn {
  name: string;
  keywords: string[];
  locations?: string[];
  radius_km?: number | null;
  employment_type?: string | null;
  remote?: boolean | null;
  enabled?: boolean;
  schedule_hours?: number | null;
  plugins?: string[];
}

export interface ProfileOut extends ProfileIn {
  id: number;
  enabled: boolean;
  plugins: string[];
  last_run_at: string | null;
}

// --- runs ---

export interface RunOut {
  id: number;
  profile_id: number | null;
  profile_name: string | null;
  plugin: string;
  trigger: RunTrigger;
  started_at: string;
  finished_at: string | null;
  status: RunStatus;
  new_count: number;
  total_count: number;
  invalid_count: number;
  error: string | null;
}

export interface RunStartOut {
  run_ids: number[];
  already_running: boolean;
}

// --- plugins ---

export interface PluginOut {
  name: string;
  display_name: string;
  capabilities: string[];
  url_patterns: string[];
  enabled: boolean;
  settings: Record<string, unknown>;
  settings_schema: Record<string, unknown> | null;
  error: string | null;
  notice?: Record<string, string> | null;
}

export interface PluginUpdate {
  enabled: boolean;
  settings?: Record<string, unknown>;
}

// --- dashboard ---

export interface UpcomingOut {
  appointment: AppointmentOut;
  application_id: number;
  title: string;
  company: string | null;
}

export interface DashboardOut {
  new_count: number;
  upcoming: UpcomingOut[];
  stale: ApplicationOut[];
  recent_runs: RunOut[];
  older_failed_count: number;
}

// --- LLM / AI settings ---

export type LlmProvider = "anthropic" | "openai" | "openai_compatible";
export type ThinkingLevel = "off" | "low" | "medium" | "high" | "max";

export interface LlmConfigOut {
  id: number;
  name: string;
  provider: LlmProvider;
  base_url: string | null;
  api_key: string | null; // masked: "…" + last 4 characters
  has_api_key: boolean;
  model: string;
  thinking: ThinkingLevel;
  supports_images: boolean;
  extra_body: Record<string, unknown>;
  extra_headers: Record<string, string>;
  price_in: number | null;
  price_out: number | null;
  daily_limit_kind: DailyLimitKind;
  daily_limit_value: number | null;
  is_default: boolean;
}

/** Body of POST/PUT /llm/configs. `api_key`: omitted keeps the stored key, "" clears it. */
export interface LlmConfigIn {
  name: string;
  provider: LlmProvider;
  base_url: string | null;
  api_key?: string;
  model: string;
  thinking: ThinkingLevel;
  supports_images: boolean;
  extra_body: Record<string, unknown>;
  extra_headers: Record<string, string>;
  price_in: number | null;
  price_out: number | null;
  /** Always sent with both fields; the value is null for `none`. */
  daily_limit_kind: DailyLimitKind;
  daily_limit_value: number | null;
}

export interface LlmPurposes {
  profile: number | null;
  fit: number | null;
  extraction: number | null;
  cover_letter: number | null;
}

export interface LlmModelsIn {
  config_id?: number;
  provider: LlmProvider;
  base_url?: string | null;
  api_key?: string;
  extra_body?: Record<string, unknown>;
  extra_headers?: Record<string, string>;
}

export interface LlmTestOut {
  ok: boolean;
  model: string;
  latency_ms: number;
}

export type DailyLimitKind = "none" | "tokens" | "eur";

export interface AppSettings {
  fit_auto: boolean;
  fit_concurrency: number;
  fit_language: "en" | "de";
  daily_limit_kind: DailyLimitKind;
  daily_limit_value: number | null;
  update_check: boolean;
}

export interface VersionInfo {
  current: string;
  latest: string | null;
  update_available: boolean;
  release_url: string | null;
  published_at: string | null;
  checked_at: string | null;
  /** `network`, `rate_limited`, `invalid_response` or `http_<status>`; null when the last check worked. */
  error: string | null;
  /** The check runs automatically (app setting on and not disabled by the server). */
  enabled: boolean;
  disabled_by_env: boolean;
  /** Tectonic is installed, so PDF cover letters work. Absent on older servers. */
  pdf_available?: boolean;
}

export interface UsageTotals {
  input_tokens: number;
  output_tokens: number;
  eur: number | null;
}

export interface ConfigUsageOut {
  /** null for the aggregated row of deleted configurations (`deleted: true`, always last). */
  config_id: number | null;
  name: string | null;
  deleted: boolean;
  today: UsageTotals;
  month: UsageTotals;
  limit: { kind: DailyLimitKind; value: number | null };
  limit_exceeded: boolean;
}

export interface LlmUsageOut {
  today: UsageTotals;
  month: UsageTotals;
  limit: { kind: DailyLimitKind; value: number | null };
  limit_exceeded: boolean;
  per_config: ConfigUsageOut[];
}

// --- errors ---

// --- my profile ---

export type DocumentKind = "text" | "pdf_text" | "pdf_scan" | "image";
export type TextSource = "extracted" | "llm" | "manual";

export interface ProfileDocumentOut {
  id: number;
  filename: string;
  display_name: string;
  mime: string;
  kind: DocumentKind;
  description: string | null;
  text: string | null;
  text_source: TextSource | null;
  created_at: string;
  updated_at: string;
  usable: boolean;
}

/** Body of PATCH /me/documents/{id}: a given `text` becomes the manual text; empty or null clears it. */
export interface DocumentPatch {
  description?: string | null;
  text?: string | null;
}

export interface UserProfileOut {
  free_text: string | null;
  profile_markdown: string | null;
  generated_at: string | null;
  edited_since_generation: boolean;
  inputs_changed_since_generation: boolean;
  version: number;
  documents_used: number;
  documents_unused: number;
}

export const FREE_TEXT_MAX = 20_000;

export interface ErrorBody {
  code?: string;
  params?: Record<string, unknown>;
  detail?: unknown;
}

export type PromptPurpose = "fit" | "profile" | "extraction" | "cover_letter";

export interface PromptOut {
  purpose: PromptPurpose;
  text: string;
  default_text: string;
  fixed_text: string;
  customized: boolean;
}

export type CoverLetterFormat = "latex" | "text";
export type CoverLetterLanguage = "posting" | "de" | "en";
/** Phase of a running cover letter job, as reported by the stream endpoint. */
export type StreamPhase = "generate" | "revise" | "repair";
export type CoverLetterStatus = "idle" | "generating" | "compiling";

export interface CoverLetterContext {
  profile: boolean;
  document_ids: number[];
  notes: string;
}

export interface CoverLetterIn {
  format: CoverLetterFormat;
  template_id: number | null;
  language: CoverLetterLanguage;
  context: CoverLetterContext;
}

export interface CoverLetterMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  created_at: string;
}

export interface CoverLetterOut {
  id: number;
  application_id: number;
  format: CoverLetterFormat;
  template_id: number | null;
  template_name: string | null;
  language: CoverLetterLanguage;
  context: Record<string, unknown>;
  content: string;
  status: CoverLetterStatus;
  error: ErrorBody | Record<string, unknown> | null;
  compile_log: string | null;
  pdf_available: boolean;
  compiler_available: boolean;
  compiled_at: string | null;
  updated_at: string;
  messages: CoverLetterMessage[];
}

export interface CoverLetterTemplate {
  id: number;
  name: string;
  builtin: boolean;
  created_at: string;
}
