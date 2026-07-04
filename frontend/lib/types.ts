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
  // Seniority-mismatch flag from scoring -- doesn't affect rank, just a separate signal.
  // Set from GET /candidates and GET /candidates/{id}; other endpoints may omit it.
  is_overqualified?: boolean;
  overqualification_reason?: string | null;
  // Latest HR-screening session status (active | completed | expired), or null if none
  // triggered yet. Present on GET /candidates.
  screening_session_status?: string | null;
  // Plain-English pipeline status ("Not started" | "R1 completed" | "R2 pending" |
  // "All rounds completed") -- the exact same value the job page's Leaderboard shows,
  // computed the same way server-side. Present on GET /candidates.
  pipeline_status?: string | null;
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

export interface ResumeScreeningCriterionScore {
  criterion_id: string;
  name: string;
  weight: number | null;
  score: number;
  evidence: string;
  note: string;
}

export interface RoundResult {
  score: number | null;
  summary: string | null;
  key_highlights: string[];
  flags: RoundFlag[];
  updated_at: string;
  // Only present for the resume_screening round -- full per-criterion breakdown,
  // not just the extremes captured in `flags`. See GET /candidates/{id}.
  criteria?: ResumeScreeningCriterionScore[];
}

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

export interface CandidateRound {
  round_key: string;
  name: string;
  description: string;
  is_builtin: boolean;
  is_ai_based: boolean;
  result: RoundResult | null;
}

export interface CandidateDetail extends Candidate {
  rounds: CandidateRound[];
  screening_sessions: ScreeningSessionSummary[];
}

// ---------- round management ----------

export type RoundDifficulty = "easy" | "balanced" | "hard";

export interface RoundAIConfig {
  share_jd: boolean;
  share_profile: boolean;
  share_resume: boolean;
  share_previous_rounds: boolean;
  share_rubric: boolean;
  instructions: string;
  duration_minutes: number;
  difficulty: RoundDifficulty;
  focus_areas: string;
  allow_candidate_questions: boolean;
  store_transcript: boolean;
  store_recording: boolean;
  generate_scorecard: boolean;
  flag_inconsistencies: boolean;
}

export interface JobRound {
  id: number;
  job_id: number;
  round_key: string;
  name: string;
  description: string;
  order_index: number;
  is_builtin: boolean;
  is_ai_based: boolean;
  ai_config: RoundAIConfig | null;
  default_ai_config?: RoundAIConfig; // only present on the create-round response
}

export interface RoundTemplate {
  key: string;
  name: string;
  description: string;
}

// ---------- AI interview round ----------

export interface TriggerInterviewResponse {
  token: string;
  interview_url: string;
  expires_at: string;
}

export interface InterviewTurnMessage {
  role: "assistant" | "candidate";
  content: string;
  audio_b64: string | null;
}

export type InterviewStatus =
  | "invited"
  | "scheduled"
  | "in_progress"
  | "completed"
  | "expired";

export interface InterviewStatusResponse {
  status: InterviewStatus;
  phase: string;
  candidate_name: string;
  job_title: string;
  round_name: string;
  instructions: string;
  duration_minutes: number;
  store_recording: boolean;
  allow_candidate_questions: boolean;
  scheduled_at: string | null;
  expires_at: string;
  slots: string[];
  messages: InterviewTurnMessage[];
  remaining_seconds: number | null;
}

export interface InterviewTurnResponse {
  status: InterviewStatus;
  phase: string;
  messages: InterviewTurnMessage[];
  remaining_seconds: number | null;
  should_wrap_up: boolean;
}

export interface InterviewSessionSummary {
  id: number;
  token: string;
  round_key: string;
  status: InterviewStatus;
  phase: string;
  duration_minutes: number;
  scheduled_at: string | null;
  created_at: string;
  expires_at: string;
  started_at: string | null;
  completed_at: string | null;
  recording_path: string | null;
  summary: string | null;
  score: number | null;
}

export interface InterviewCompetency {
  name: string;
  rating: number;
  comment: string;
}

export interface InterviewScorecard {
  summary?: string;
  score?: number;
  recommendation?: string;
  competencies?: InterviewCompetency[];
  key_highlights?: string[];
  flags?: RoundFlag[];
}

export interface InterviewTranscriptTurn {
  role: "assistant" | "candidate";
  content: string;
  kind: string;
  created_at: string;
}

export interface InterviewEvent {
  type: string;
  detail: string;
  created_at: string;
}

export interface InterviewSessionDetail {
  id: number;
  round_key: string;
  status: InterviewStatus;
  phase: string;
  duration_minutes: number;
  scheduled_at: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  score: number | null;
  summary: string | null;
  scorecard: InterviewScorecard | null;
  plan: { competencies?: string[]; questions?: { topic: string; question: string }[] } | null;
  has_recording: boolean;
  transcript: InterviewTranscriptTurn[];
  events: InterviewEvent[];
}

// ---------- leaderboard ----------

export interface LeaderboardRound {
  round_key: string;
  name: string;
}

export interface LeaderboardRoundScore {
  round_key: string;
  score: number | null;
}

export interface LeaderboardCandidate {
  id: number;
  job_id: number;
  name: string;
  email: string;
  external_id: string | null;
  source_type: string | null;
  source_name: string | null;
  application_date: string | null;
  round_scores: LeaderboardRoundScore[];
  overall: number | null;
  status: string;
}

export interface FunnelStage {
  round_key: string;
  name: string;
  count: number;
}

export interface LeaderboardResponse {
  rounds: LeaderboardRound[];
  candidates: LeaderboardCandidate[];
  funnel: FunnelStage[];
  total_candidates: number;
}
