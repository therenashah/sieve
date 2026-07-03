# Sieve — Recruitment Agent

AI-powered resume screening and L1 interview agent. See [docs/architecture-v2.md](docs/architecture-v2.md) for the full design.

## Stack

- **Backend**: Python + FastAPI, `pdfplumber`/`PyMuPDF` + `python-docx` for parsing, LLM (Claude/GPT) for structured JSON outputs.
- **Storage**: SQLite, volume-mounted in Docker.
- **Frontend**: Next.js (rubric panel, chat widget, filter chips, ranked table).
- **Candidate auth**: tokenized links with server-side 15-min expiry.
- **Deploy**: Docker Compose (targets EC2).

## Setup

1. Copy `.env.example` to `.env` and fill in your LLM API key(s):

   ```bash
   cp .env.example .env
   ```

2. Start both services:

   ```bash
   docker compose up --build
   ```

3. Open:
   - Frontend: http://localhost:3000
   - Backend health check: http://localhost:8000/health
   - API docs (Swagger): http://localhost:8000/docs

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
