# AI-Powered Resume Screening & L1 Interview Agent — Architecture

**Seclore Hackathon · July 2026**

---

## 1. Design principles

1. **Mandatory conditions are a hard gate, not a score input.** Candidates failing any mandatory JD condition are rejected before fitment scoring, with cited evidence. This directly fixes the Darwinbox stack-ranking failure.
2. **No bare scores.** Every evaluation ships with strengths, gaps, and a recommendation (Advance / Reject / Needs review) plus a specific reason — eliminating the 3/4-rating dead zone that forces recruiters to re-screen.
3. **One rubric per JD, generated once, stored, reused.** All candidates for a job are scored against the same rubric, guaranteeing consistency.
4. **Human-in-the-loop checkpoints.** The recruiter approves before a candidate receives a screening link, and before L1. The AI recommends; the human decides.
5. **Standalone-first.** No Darwinbox integration for the hackathon. Push/pull sync with Darwinbox is documented as future scope.
6. **Everything is logged.** Every prompt, response, score, and rationale is persisted for auditability and explainability.

---

## 2. High-level flow

```
                ┌──────────────┐      ┌──────────────┐
                │  Ingestion   │─────▶│   Parsing    │
                │ resumes + JD │      │ PDF/DOCX→text│
                └──────────────┘      └──────┬───────┘
                                             │
                                             ▼
                                      ┌──────────────┐
                                      │   Rubric     │
                                      │  generator   │
                                      │ (1 per JD)   │
                                      └──────┬───────┘
                                             │
                ┌──────────────┐             │
                │ Mandatory    │◀────────────┘
                │ gate check   │──────▶ Rejected + cited reason
                └──────┬───────┘
                       │ pass
                       ▼
                ┌──────────────┐
                │   Fitment    │
                │   scoring    │
                └──────┬───────┘
                       ▼
        ┌─────────────────────────────┐
        │     Recruiter dashboard     │  ◀── human approval gate
        │ ranked list + evidence      │
        └──────────────┬──────────────┘
                       ▼
                ┌──────────────┐
                │ Screening    │  tokenized link, async chat
                │ chat agent   │
                └──────┬───────┘
                       ▼
                ┌──────────────┐
                │ L1 interview │  dynamic questions, transcript
                │    agent     │
                └──────┬───────┘
                       ▼
                ┌──────────────┐
                │ Scorecard +  │────▶ updates dashboard
                │recommendation│
                └──────────────┘

  Cross-cutting: audit log · SQLite store · (future) Darwinbox sync
```

---

## 3. Components

### 3.1 Ingestion & parsing
- Recruiter creates a job (paste JD) and uploads candidate resumes (PDF/DOCX).
- Parsing: `pdfplumber` / `PyMuPDF` for PDF, `python-docx` for Word.
- Keep parsing dumb — extract raw text; the LLM does the structuring.

### 3.2 Rubric generator
- Input: JD text.
- LLM extracts a structured rubric: criteria list with `{name, description, weight, mandatory: bool}`.
- Recruiter can review/edit the rubric before it is locked (optional UI, nice-to-have).
- Stored per job; every candidate for that job is evaluated against this exact rubric.

### 3.3 Mandatory gate check
- Input: parsed resume + mandatory criteria from the rubric.
- LLM performs pass/fail per mandatory condition **with a quoted evidence span** from the resume (or "not found").
- Any failure → candidate status `REJECTED_AT_GATE`, shown separately with reasons.
- Only passing candidates proceed to fitment scoring.

### 3.4 Fitment scoring
- Input: parsed resume + full rubric.
- Output (structured JSON): per-criterion scores, overall fitment score, strengths[], gaps[], recommendation ∈ {ADVANCE, REJECT, NEEDS_REVIEW} + reason.
- `NEEDS_REVIEW` must always carry the specific unresolved question — this is what the screening chat can later resolve.

### 3.5 Screening chat agent
- Triggered by recruiter approval on the dashboard.
- Candidate receives a unique tokenized link (no login) → async interactive chat.
- Agent asks JD-derived screening questions, prioritizing the candidate's identified gaps/unresolved questions.
- On completion: screening summary + updated score → dashboard.

### 3.6 L1 interview agent
- Same chat engine as 3.5 (same session/message infrastructure), different system prompt + rubric focus (technical depth, communication, behavioral).
- Dynamic follow-up questions based on responses.
- Output: transcript, scorecard, recommendation report.
- **Scope: chat only for the hackathon.** Voice/video is future scope.

### 3.7 Recruiter dashboard
- Job list → ranked candidates with pipeline status:
  `Applied → Gate passed / Rejected at gate → Scored → Screening sent → Screened → L1 sent → L1 done → Recommended`
- Candidate detail: evidence-backed scores, strengths/gaps, chat transcripts, scorecards.
- Actions: send screening link, send L1 link, override recommendation.

---

## 4. Data model (SQLite)

```
jobs            (id, title, jd_text, status, created_at)
rubrics         (id, job_id, criteria_json, version, created_at)
candidates      (id, job_id, name, email, resume_path, resume_text, status)
evaluations     (id, candidate_id, rubric_id, stage,          -- GATE | FITMENT | SCREENING | L1
                 result_json, score, recommendation, reason, created_at)
chat_sessions   (id, candidate_id, stage,                     -- SCREENING | L1
                 token, status, started_at, completed_at)
messages        (id, session_id, role, content, created_at)
audit_log       (id, entity, entity_id, action, payload_json, created_at)
```

---

## 5. API contract (FastAPI)

```
POST  /jobs                        create job with JD → triggers rubric generation
GET   /jobs/{id}/rubric            view generated rubric
POST  /jobs/{id}/candidates        upload resume(s) → parse → gate → score
GET   /jobs/{id}/candidates        ranked list with statuses
GET   /candidates/{id}             full detail: evaluations, transcripts
POST  /candidates/{id}/screening   generate screening session + tokenized link
POST  /candidates/{id}/l1          generate L1 session + tokenized link

GET   /chat/{token}                candidate-facing: session state + history
POST  /chat/{token}/message        candidate sends message → agent reply
POST  /chat/{token}/complete       finalize → summary + score → dashboard
```

**Evaluation object shape (agree on this before splitting work):**

```json
{
  "gate": {
    "passed": false,
    "checks": [
      {"condition": "5+ years C++", "passed": false,
       "evidence": "Resume shows 2 years C++ (2023–2025)"}
    ]
  },
  "fitment": {
    "score": 78,
    "strengths": ["Strong AWS/backend depth", "Relevant domain experience"],
    "gaps": ["No team-lead experience mentioned"],
    "recommendation": "NEEDS_REVIEW",
    "reason": "Leadership requirement ambiguous — resolve in screening chat"
  }
}
```

---

## 6. Tech stack

| Layer          | Choice                          | Why |
|----------------|---------------------------------|-----|
| Backend        | Python + FastAPI                | Team familiarity, fast to build |
| Resume parsing | pdfplumber / PyMuPDF, python-docx | Reliable text extraction |
| LLM            | Claude / GPT API (structured JSON output) | Rubric gen, gate, scoring, both agents |
| Storage        | SQLite                          | Zero setup, demo-adequate |
| Frontend       | Streamlit (speed) or React (polish) | Recruiter dashboard + candidate chat page |
| Auth (candidate) | Tokenized links (UUID)        | No login needed for demo |

---

## 7. Task split (2 people)

**Person A — Pipeline & agents (backend)**
- Parsing, rubric generation, gate check, fitment scoring
- Chat engine (shared by screening + L1; different prompts)
- FastAPI endpoints per contract above

**Person B — Product surface**
- Recruiter dashboard (ranked list → candidate detail)
- Candidate-facing chat page
- Demo dataset: 2–3 JDs, 20–30 resumes (include deliberate gate-failures and keyword-stuffed weak fits)
- Builds against mocked endpoints matching the agreed JSON shapes

**Sync points:** 30 min upfront (schema + contract + demo script) · post-lunch integration · feature freeze 2 hours before deadline, then demo rehearsal only.

---

## 8. Build order

1. Prompts in a plain script: rubric gen → gate → scoring on 1 JD + 3 resumes (highest risk, do first)
2. Wrap in FastAPI endpoints + SQLite persistence
3. Dashboard with ranked list + evidence
4. Screening chat (tokenized link, async)
5. L1 agent (reuse chat engine)
6. Polish: pipeline statuses, audit view, demo rehearsal

If time runs short: cut L1 before cutting anything else — gate + explainable scoring alone solves both stated pain points.

---

## 9. Future scope (mention in pitch, don't build)

- Darwinbox push/pull sync (applications remain in Darwinbox for onboarding)
- LinkedIn ingestion
- Voice/video L1 interviews
- Recruiter analytics (funnel metrics, TAT tracking)
- Bias monitoring dashboards on top of the audit log
