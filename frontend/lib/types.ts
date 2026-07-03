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

export interface Candidate {
  id: number;
  job_id: number;
  name: string;
  email: string;
  phone: string;
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
  created_at: string;
  profile?: Record<string, unknown>;
  screening_result?: Record<string, unknown> | null;
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
