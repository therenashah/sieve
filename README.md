# Sieve — Recruitment Agent

AI-powered resume screening and L1 interview agent. See [docs/architecture-v2.md](docs/architecture-v2.md) for the full design.

## Stack

- **Backend**: Python + FastAPI, `pdfplumber`/`PyMuPDF` + `python-docx` for parsing, LLM via **AWS Bedrock** (Claude Haiku 4.5) for structured JSON outputs.
- **Storage**: SQLite, volume-mounted in Docker.
- **Frontend**: Next.js (rubric panel, chat widget, filter chips, ranked table).
- **Candidate auth**: tokenized links with server-side 15-min expiry.
- **Deploy**: Docker Compose (targets EC2 — including the hackathon instance, which already has Bedrock access via its IAM role).

## Setup

1. Copy `.env.example` to `.env`:

   ```bash
   cp .env.example .env
   ```

   If you're running this **on the hackathon EC2 instance** (`i-0615e0a1eec5fe5be`), leave `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` blank — the instance's IAM role already grants Bedrock access and boto3 picks it up automatically. Only fill those in if running elsewhere (see [Using Bedrock from elsewhere](#using-bedrock-from-elsewhere) below). Set `AWS_REGION` to whichever region that role's Bedrock access is enabled in.

2. Start both services:

   ```bash
   docker compose up --build
   ```

3. Open:
   - Frontend: http://localhost:3000
   - Backend health check: http://localhost:8000/health
   - API docs (Swagger): http://localhost:8000/docs

## Using Bedrock from elsewhere

If you're not running on the hackathon instance itself, you need temporary
AWS credentials from it:

1. SSH (or SSM) into `i-0615e0a1eec5fe5be` (`13.235.241.190`).
2. Pull the instance role's temporary session credentials:
   ```bash
   ROLE=$(curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/)
   curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/$ROLE
   ```
3. Copy the `AccessKeyId` / `SecretAccessKey` / `Token` fields into `.env` as
   `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN`. These
   expire in a few hours — re-pull if requests start failing with an auth error.
4. Confirm the exact Bedrock model ID: `BEDROCK_MODEL_ID` in `.env.example`
   defaults to `us.anthropic.claude-haiku-4-5-20251001-v1:0` (the standard
   cross-region inference profile ID). Verify it matches what's actually
   enabled for this account/region — Bedrock model access is granted
   per-model in the console, separate from IAM permissions:
   ```bash
   aws bedrock list-foundation-models --region <region> \
     --query "modelSummaries[?contains(modelId,'haiku')].modelId" --output table
   ```

## HR screening chatbot

On first startup, the backend seeds a demo job (with 4 mandatory screening
questions) and three demo candidates in different post-resume-screening
states — see `backend/app/seed.py` and the [Demo data](#demo-data--post-resume-screening-states)
section below. This lets you exercise the full HR-chat flow without a real
resume-parsing/scoring pipeline in place yet.

**1. Index the Seclore knowledge base (RAG)**

Drop `.md`/`.txt` docs into `data/knowledge_base/` (two placeholder docs —
`culture.md`, `policies.md` — are already there; replace them with the real
thing). Then index them (pure lexical term-frequency indexing — no API key
needed for this step):

```bash
docker compose exec api python scripts/ingest_kb.py
# or locally: cd backend && python scripts/ingest_kb.py
```

This also runs automatically on every backend startup for any new/unindexed
files.

**2. Trigger a screening link (the HR action)**

```bash
curl -X POST http://localhost:8000/api/jobs/1/candidates/1/screening-link
```

Returns `{"token": "...", "chat_url": "http://localhost:3000/chat/<token>", "expires_at": "..."}`.
The link is single-use and expires `SCREENING_LINK_TTL_MINUTES` (default 15)
after creation.

**3. Have the candidate chat**

- In a browser: open the returned `chat_url`.
- Or from the CLI, which triggers the link itself and drives the chat over HTTP:

  ```bash
  python backend/scripts/test_chat_cli.py --job-id 1 --candidate-id 1
  ```

The bot asks the job's mandatory questions one at a time, may ask a couple of
profile-driven follow-ups (e.g. an employment gap), then offers to answer
questions about Seclore (RAG-backed) before closing the chat. Once closed, the
session is marked `completed` (the token can't be reused), and a recruiter
summary + key highlights are generated and stored — see:

```bash
curl http://localhost:8000/api/jobs/1/candidates/1/screening-sessions
```

## Demo data — post-resume-screening states

The seed data (`backend/app/seed.py`) models three candidates for the demo
job, each in a state the (not-yet-built) resume-screening pipeline is
expected to produce — see `docs/architecture-v2.md` §3.3–3.4:

| Candidate ID | Name | Mandatory gate | Recommendation | What it tests |
|---|---|---|---|---|
| 1 | Priya Nair | PASSED | NEEDS_REVIEW | Has a flagged ~13-month employment gap → the PROFILE_FOLLOWUP phase should surface and ask about it |
| 2 | Rahul Verma | PASSED | ADVANCE | Clean profile, no flags → LLM should decide there's nothing to follow up on and move straight to the Seclore Q&A phase |
| 3 | Karan Mehta | **REJECTED** | REJECT | Fails a mandatory JD condition (min. experience) → `POST .../screening-link` should return **400**, since a gate-rejected candidate must never reach a screening chat |

Try candidate 3 explicitly to confirm the gate blocks it:

```bash
curl -i -X POST http://localhost:8000/api/jobs/1/candidates/3/screening-link
# expect: HTTP/1.1 400 Bad Request
```

## Local development (without Docker)

**Backend**

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

## Tests

```bash
cd backend
pytest
```

## Project layout

```
recruitment-agent/
├── docker-compose.yml
├── .env                  # gitignored
├── backend/              # FastAPI app: pipeline (parsing→ranking), conversations (screening/L1), api
├── frontend/             # Next.js app: job dashboard, rubric panel, chat UI
├── docs/                 # architecture, HLD, LLD
└── data/                 # sample JDs + resumes (gitignore real PII)
```
