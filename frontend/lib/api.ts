import { getToken } from "./auth";
import type {
  ApplyRubricResult,
  CandidateDetail,
  ChatTurnResponse,
  CvUploadResult,
  FilterFacets,
  FilterSet,
  HealthResponse,
  InterviewSessionDetail,
  InterviewSessionSummary,
  InterviewStatusResponse,
  InterviewTurnResponse,
  Job,
  JobQuestion,
  JobRound,
  LeaderboardResponse,
  RankedCandidatesResponse,
  RoundAIConfig,
  RoundTemplate,
  Rubric,
  RubricChatResponse,
  ScanResponse,
  ScreeningAnswer,
  SessionStatusResponse,
  TrackerUploadResult,
  TriggerInterviewResponse,
  TriggerScreeningResponse,
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function toErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail || JSON.stringify(body);
  } catch {
    return response.statusText;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    throw new ApiError(response.status, await toErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

function authHeaders(): HeadersInit {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function authFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...init?.headers },
  });
  if (!response.ok) {
    throw new ApiError(response.status, await toErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}

export interface SearchResult {
  jobs: { id: number; title: string }[];
  candidates: { id: number; job_id: number; name: string; external_id: string | null }[];
}

export function search(q: string): Promise<SearchResult> {
  return authFetch<SearchResult>(`/api/search?q=${encodeURIComponent(q)}`);
}

export function login(email: string, password: string): Promise<{ token: string; expires_at: string }> {
  return apiFetch("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
}

export function listJobs(): Promise<Job[]> {
  return authFetch<Job[]>("/api/jobs");
}

export function getJob(jobId: number | string): Promise<Job> {
  return authFetch<Job>(`/api/jobs/${jobId}`);
}

export function archiveJob(jobId: number | string): Promise<Job> {
  return authFetch<Job>(`/api/jobs/${jobId}/archive`, { method: "POST" });
}

export function unarchiveJob(jobId: number | string): Promise<Job> {
  return authFetch<Job>(`/api/jobs/${jobId}/unarchive`, { method: "POST" });
}

export async function deleteJob(jobId: number | string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/jobs/${jobId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await toErrorMessage(response));
  }
}

export function createJob(title: string, description: string): Promise<Job> {
  const form = new FormData();
  form.append("title", title);
  form.append("description", description);
  return authFetch<Job>("/api/jobs", { method: "POST", body: form });
}

export function uploadJD(jobId: number | string, file: File): Promise<{ jd_filename: string }> {
  const form = new FormData();
  form.append("file", file);
  return authFetch(`/api/jobs/${jobId}/jd`, { method: "POST", body: form });
}

// Returns null while generation is still running (or hasn't started — no JD
// uploaded yet), rather than treating "not found yet" as an error.
export async function getRubric(jobId: number | string): Promise<Rubric | null> {
  try {
    return await authFetch<Rubric>(`/api/jobs/${jobId}/rubric`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return null;
    }
    throw err;
  }
}

export function uploadTracker(jobId: number | string, file: File): Promise<TrackerUploadResult> {
  const form = new FormData();
  form.append("file", file);
  return authFetch(`/api/jobs/${jobId}/tracker`, { method: "POST", body: form });
}

export function uploadCvs(jobId: number | string, file: File): Promise<CvUploadResult> {
  const form = new FormData();
  form.append("file", file);
  return authFetch(`/api/jobs/${jobId}/cvs`, { method: "POST", body: form });
}

// `filter` should be a JSON-stringified FilterSet (see filters/parse). Ranked/scored
// against the given rubric `version`, or the latest one if omitted.
export function listCandidates(
  jobId: number | string,
  options?: { filter?: string; version?: number },
): Promise<RankedCandidatesResponse> {
  const params = new URLSearchParams();
  if (options?.filter) params.set("filter", options.filter);
  if (options?.version) params.set("version", String(options.version));
  const qs = params.toString();
  return authFetch<RankedCandidatesResponse>(`/api/jobs/${jobId}/candidates${qs ? `?${qs}` : ""}`);
}

export function rejectCandidate(
  jobId: number | string,
  candidateId: number,
): Promise<{ candidate_id: number; screening_decision: string | null }> {
  return authFetch(`/api/jobs/${jobId}/candidates/${candidateId}/reject`, { method: "POST" });
}

export function unrejectCandidate(
  jobId: number | string,
  candidateId: number,
): Promise<{ candidate_id: number; screening_decision: string | null }> {
  return authFetch(`/api/jobs/${jobId}/candidates/${candidateId}/unreject`, { method: "POST" });
}

export function shortlistCandidate(
  jobId: number | string,
  candidateId: number,
): Promise<{ candidate_id: number; screening_decision: string | null }> {
  return authFetch(`/api/jobs/${jobId}/candidates/${candidateId}/shortlist`, { method: "POST" });
}

export function unshortlistCandidate(
  jobId: number | string,
  candidateId: number,
): Promise<{ candidate_id: number; screening_decision: string | null }> {
  return authFetch(`/api/jobs/${jobId}/candidates/${candidateId}/unshortlist`, { method: "POST" });
}

export function scanCandidates(jobId: number | string): Promise<ScanResponse> {
  return authFetch(`/api/jobs/${jobId}/scan`, { method: "POST" });
}

export function applyRubric(jobId: number | string, proposed: Rubric): Promise<ApplyRubricResult> {
  return authFetch(`/api/jobs/${jobId}/rubric/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(proposed),
  });
}

export function rubricChat(
  jobId: number | string,
  message: string,
  proposedRubric?: Rubric,
): Promise<RubricChatResponse> {
  return authFetch(`/api/jobs/${jobId}/rubric/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, proposed_rubric: proposedRubric ?? null }),
  });
}

export function parseFilters(jobId: number | string, text: string): Promise<FilterSet> {
  return authFetch(`/api/jobs/${jobId}/filters/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

export function getFilterFacets(jobId: number | string): Promise<FilterFacets> {
  return authFetch(`/api/jobs/${jobId}/filters/facets`);
}

export function getCandidateDetail(
  jobId: number | string,
  candidateId: number | string
): Promise<CandidateDetail> {
  return authFetch<CandidateDetail>(`/api/jobs/${jobId}/candidates/${candidateId}`);
}

export function listQuestions(jobId: number | string): Promise<JobQuestion[]> {
  return authFetch<JobQuestion[]>(`/api/jobs/${jobId}/questions`);
}

export function addQuestion(jobId: number | string, questionText: string): Promise<JobQuestion> {
  return authFetch<JobQuestion>(`/api/jobs/${jobId}/questions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question_text: questionText }),
  });
}

export async function deleteQuestion(jobId: number | string, questionId: number): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/jobs/${jobId}/questions/${questionId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await toErrorMessage(response));
  }
}

// Synchronously (re)generates AI questions from the job's stored JD text — mainly for
// jobs whose JD predates AI question generation, or if the background pass silently
// failed. Returns the full refreshed pool.
export function generateQuestions(jobId: number | string): Promise<JobQuestion[]> {
  return authFetch<JobQuestion[]>(`/api/jobs/${jobId}/questions/generate`, { method: "POST" });
}

export function getScreeningAnswers(
  jobId: number | string,
  candidateId: number | string,
  sessionId: number | string
): Promise<ScreeningAnswer[]> {
  return authFetch<ScreeningAnswer[]>(
    `/api/jobs/${jobId}/candidates/${candidateId}/screening-sessions/${sessionId}/answers`
  );
}

// `questionIds` is the recruiter's confirmed selection from the trigger modal — omit it
// (or pass an empty array) to fall back to every mandatory question on the job.
export function triggerScreening(
  jobId: number | string,
  candidateId: number | string,
  questionIds: number[] = []
): Promise<TriggerScreeningResponse> {
  return authFetch(`/api/jobs/${jobId}/candidates/${candidateId}/screening-link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question_ids: questionIds }),
  });
}

export function getLeaderboard(jobId: number | string): Promise<LeaderboardResponse> {
  return authFetch<LeaderboardResponse>(`/api/jobs/${jobId}/leaderboard`);
}

export function listRounds(jobId: number | string): Promise<JobRound[]> {
  return authFetch<JobRound[]>(`/api/jobs/${jobId}/rounds`);
}

export function listRoundTemplates(jobId: number | string): Promise<RoundTemplate[]> {
  return authFetch<RoundTemplate[]>(`/api/jobs/${jobId}/rounds/templates`);
}

export function addRound(
  jobId: number | string,
  templateKey: string,
  name?: string,
  description?: string
): Promise<JobRound> {
  return authFetch<JobRound>(`/api/jobs/${jobId}/rounds`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template_key: templateKey, name, description }),
  });
}

export function updateRound(
  jobId: number | string,
  roundId: number,
  body: { name: string; description: string; is_ai_based: boolean; ai_config: RoundAIConfig | null }
): Promise<JobRound> {
  return authFetch<JobRound>(`/api/jobs/${jobId}/rounds/${roundId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteRound(jobId: number | string, roundId: number): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/jobs/${jobId}/rounds/${roundId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await toErrorMessage(response));
  }
}

// ---------- AI interview round ----------

// Recruiter: generate a tokenized invite link for an AI interview round.
export function triggerInterview(
  jobId: number | string,
  candidateId: number | string,
  roundKey: string
): Promise<TriggerInterviewResponse> {
  return authFetch(`/api/jobs/${jobId}/candidates/${candidateId}/interview-link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ round_key: roundKey }),
  });
}

export function listInterviewSessions(
  jobId: number | string,
  candidateId: number | string,
  roundKey?: string
): Promise<InterviewSessionSummary[]> {
  const qs = roundKey ? `?round_key=${encodeURIComponent(roundKey)}` : "";
  return authFetch<InterviewSessionSummary[]>(
    `/api/jobs/${jobId}/candidates/${candidateId}/interview-sessions${qs}`
  );
}

export function getInterviewSessionDetail(
  jobId: number | string,
  candidateId: number | string,
  sessionId: number | string
): Promise<InterviewSessionDetail> {
  return authFetch<InterviewSessionDetail>(
    `/api/jobs/${jobId}/candidates/${candidateId}/interview-sessions/${sessionId}`
  );
}

// All /api/jobs routes require a bearer token, so the resume can't be a plain <a href> --
// (unlike a same-origin unauthenticated download) it has to be fetched with the auth
// header and opened as a blob URL.
export async function getCandidateResume(
  jobId: number | string,
  candidateId: number | string,
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE_URL}/api/jobs/${jobId}/candidates/${candidateId}/resume`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await toErrorMessage(response));
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : "resume";
  const blob = await response.blob();
  return { blob, filename };
}

export async function exportCandidates(
  jobId: number | string,
  candidateIds: number[],
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE_URL}/api/jobs/${jobId}/candidates/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ candidate_ids: candidateIds }),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await toErrorMessage(response));
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : "candidates.xlsx";
  const blob = await response.blob();
  return { blob, filename };
}

export function interviewRecordingUrl(
  jobId: number | string,
  candidateId: number | string,
  sessionId: number | string
): string {
  return `${API_BASE_URL}/api/jobs/${jobId}/candidates/${candidateId}/interview-sessions/${sessionId}/recording`;
}

// Candidate-facing (token only, no auth):
export function getInterview(token: string): Promise<InterviewStatusResponse> {
  return apiFetch<InterviewStatusResponse>(`/api/interview/${token}`);
}

export function scheduleInterview(token: string, slot: string): Promise<{ scheduled_at: string }> {
  return apiFetch(`/api/interview/${token}/schedule`, {
    method: "POST",
    body: JSON.stringify({ slot }),
  });
}

export function startInterview(token: string): Promise<InterviewTurnResponse> {
  return apiFetch<InterviewTurnResponse>(`/api/interview/${token}/start`, { method: "POST" });
}

export function sendInterviewMessage(token: string, message: string): Promise<InterviewTurnResponse> {
  return apiFetch<InterviewTurnResponse>(`/api/interview/${token}/message`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function endInterview(token: string): Promise<InterviewTurnResponse> {
  return apiFetch<InterviewTurnResponse>(`/api/interview/${token}/end`, { method: "POST" });
}

export function logInterviewEvent(token: string, type: string, detail = ""): Promise<{ ok: boolean }> {
  return apiFetch(`/api/interview/${token}/event`, {
    method: "POST",
    body: JSON.stringify({ type, detail }),
  });
}

export async function uploadInterviewRecording(token: string, blob: Blob): Promise<void> {
  const form = new FormData();
  form.append("file", blob, "interview.webm");
  const response = await fetch(`${API_BASE_URL}/api/interview/${token}/recording`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    throw new ApiError(response.status, await toErrorMessage(response));
  }
}

export function getChatSession(token: string): Promise<SessionStatusResponse> {
  return apiFetch<SessionStatusResponse>(`/api/chat/${token}`);
}

export function startChat(token: string): Promise<ChatTurnResponse> {
  return apiFetch<ChatTurnResponse>(`/api/chat/${token}/start`, { method: "POST" });
}

export function sendChatMessage(token: string, message: string): Promise<ChatTurnResponse> {
  return apiFetch<ChatTurnResponse>(`/api/chat/${token}/message`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}
