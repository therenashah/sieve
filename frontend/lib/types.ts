// TS mirrors of Pydantic response shapes in backend/app/models.py

export interface HealthResponse {
  status: string;
  app_env: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export type SessionStatus = "active" | "completed" | "expired";

export interface ChatTurnResponse {
  session_status: SessionStatus;
  phase: string;
  messages: ChatMessage[];
}

export interface SessionStatusResponse {
  session_status: SessionStatus;
  phase: string;
  candidate_name: string;
  job_title: string;
  messages: ChatMessage[];
}

export interface Job {
  id: number;
  title: string;
  description: string;
  status: string;
  jd_filename: string | null;
  created_at: string;
  candidate_count?: number;
  cvs_matched?: number;
}

export interface Criterion {
  id: string;
  name: string;
  description: string;
  weight: number;
}

export interface Rubric {
  version: number;
  criteria: Criterion[];
}

export interface RubricDiff {
  weight_changes: [string, number, number][]; // [criterion_id, old, new]
  added: Criterion[];
  removed: string[];
  edited_descriptions: string[];
}

export interface ApplyRubricResult {
  new_version: number;
  rescore_criterion_ids: string[];
  rescoring: boolean;
}

export interface RubricChatResponse {
  reply: string;
  proposed_rubric: Rubric;
  diff: RubricDiff;
}

export type FilterOp = "eq" | "neq" | "gte" | "lte" | "contains" | "in" | "exists";

export interface Filter {
  field: string;
  op: FilterOp;
  value: string | number | boolean | (string | number)[];
  criterion_id: string | null;
}

export interface FilterSet {
  filters: Filter[];
  unparsed: string[];
}

export interface ScanResponse {
  status: string;
  rubric_id: number;
}

export interface TriggerScreeningResponse {
  token: string;
  chat_url: string;
  expires_at: string;
}

export interface CandidateCriterionScore {
  criterion_id: string;
  score: number;
  evidence: string;
}

export interface Candidate {
  id: number;
  job_id: number;
  name: string;
  email: string;
  phone: string;
  status: string; // PARSING | SCORING | SCORED | ERROR
  error_reason: string | null;
  external_id: string | null;
  match_score: number | null;
  overall_status: string | null;
  recruiter: string | null;
  tags: string | null;
  application_date: string | null;
  source_type: string | null;
  source_name: string | null;
  ownership_status: string | null;
  shortlisting_status: string | null;
  resume_screening_status: string | null;
  l1_status: string | null;
  l2_status: string | null;
  l3_status: string | null;
  pre_offer_status: string | null;
  resume_path: string | null;
  screening_decision: string | null; // null | "rejected" -- HR's resume-screening decision, reversible
  created_at: string;
  profile?: Record<string, unknown>;
  screening_result?: Record<string, unknown> | null;
  // Only present on GET /candidates responses (rank-derived) -- absent from
  // tracker/CV upload responses, which return raw candidate rows.
  overall?: number | null;
  scores?: CandidateCriterionScore[];
}

export interface RankedCandidatesResponse {
  rubric_version: number | null;
  candidates: Candidate[];
  unparsed: string[];
}

export interface RowError {
  row: number;
  reason: string;
}

export interface TrackerUploadResult {
  candidates: Candidate[];
  row_errors: RowError[];
  count: number;
}

export interface CvMatch {
  candidate_id: number;
  external_id: string | null;
  name: string;
  file: string;
  source_filename: string;
}

export interface UnmatchedCandidate {
  id: number;
  external_id: string | null;
  name: string;
}

export interface CvUploadResult {
  matched: CvMatch[];
  unmatched_files: string[];
  unmatched_candidates: UnmatchedCandidate[];
  skipped_non_resume_files: string[];
  total_files_in_zip: number;
  total_candidates: number;
}

export type QuestionSource = "default" | "ai" | "custom";

export interface JobQuestion {
  id: number;
  job_id: number;
  question_text: string;
  order_index: number;
  is_mandatory: number;
  source: QuestionSource;
}

export interface RoundFlag {
  type: "red" | "green";
  detail: string;
}

export interface RoundResult {
  score: number | null;
  summary: string | null;
  key_highlights: string[];
  flags: RoundFlag[];
  updated_at: string;
}

export type RoundName = "resume_screening" | "hr_screening" | "l1" | "l2" | "l3" | "pre_offer";

export interface ScreeningSessionSummary {
  id: number;
  token: string;
  status: string;
  phase: string;
  created_at: string;
  expires_at: string;
  completed_at: string | null;
  summary: string | null;
  key_highlights: { key_highlights: string[] } | null;
}

export interface ScreeningAnswer {
  question_text: string;
  question_type: string; // mandatory | profile_followup
  answer_text: string;
  created_at: string;
}

export interface CandidateDetail extends Candidate {
  rounds: Record<RoundName, RoundResult | null>;
  screening_sessions: ScreeningSessionSummary[];
}
