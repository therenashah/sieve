import { getToken } from "./auth";
import type {
  Candidate,
  ChatTurnResponse,
  CvUploadResult,
  HealthResponse,
  Job,
  SessionStatusResponse,
  TrackerUploadResult,
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

export function login(email: string, password: string): Promise<{ token: string; expires_at: string }> {
  return apiFetch("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
}

export function listJobs(): Promise<Job[]> {
  return authFetch<Job[]>("/api/jobs");
}

export function getJob(jobId: number | string): Promise<Job> {
  return authFetch<Job>(`/api/jobs/${jobId}`);
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

export function listCandidates(jobId: number | string): Promise<Candidate[]> {
  return authFetch<Candidate[]>(`/api/jobs/${jobId}/candidates`);
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
