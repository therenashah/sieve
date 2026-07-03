"""Demo data so the HR screening chat can be exercised end-to-end without a
real resume-parsing/scoring pipeline in place yet. Only runs if the `jobs`
table is empty — safe to call on every startup.

Candidates are seeded in the states the resume-screening pipeline (see
docs/architecture-v2.md §3.3-3.4) is expected to produce: mandatory-gate
pass/fail plus a fitment recommendation. Only gate-`PASSED` candidates are
eligible for a screening link — `engine.create_session` enforces this, and
candidate 3 below exists specifically to demonstrate that block.
"""

import json

from app.db import get_db

DEMO_JOB = {
    "title": "Backend Engineer — Platform Team",
    "description": (
        "We're hiring a backend engineer to build and scale the services behind "
        "Seclore's data classification and rights-management products. Strong "
        "Python experience, comfort with distributed systems, and a bias for "
        "shipping are a must."
    ),
}

DEMO_MANDATORY_QUESTIONS = [
    "What is your current notice period?",
    "What are your current and expected CTC?",
    "Are you open to working out of our Pune office, or would this be a remote role for you?",
    "Do you have any active offers or interview processes elsewhere right now?",
]

DEMO_CANDIDATES = [
    {
        # NEEDS_REVIEW: passed the gate, but resume screening flagged an
        # unresolved employment gap — exactly the kind of thing the
        # PROFILE_FOLLOWUP phase should surface and the screening chat should
        # help resolve before the recruiter sees it.
        "name": "Priya Nair",
        "email": "priya.nair@example.com",
        "phone": "+91-98765-43210",
        "profile": {
            "current_company": "CloudScape Technologies",
            "current_role": "Senior Software Engineer",
            "total_experience_years": 5.5,
            "skills": ["Python", "FastAPI", "PostgreSQL", "AWS", "Docker", "Kafka"],
            "education": [
                {"degree": "B.Tech, Computer Science", "institute": "NIT Trichy", "year": 2018}
            ],
            "employment_history": [
                {"company": "CloudScape Technologies", "role": "Senior Software Engineer", "start": "2021-06", "end": "present"},
                {"company": "Freelance / unspecified", "role": "", "start": "2020-03", "end": "2021-05"},
                {"company": "Innotech Solutions", "role": "Software Engineer", "start": "2018-07", "end": "2020-02"},
            ],
            "location": "Bengaluru",
        },
        "screening_result": {
            "mandatory_gate": "PASSED",
            "fitment_score": 78,
            "recommendation": "NEEDS_REVIEW",
            "strengths": [
                "5.5 years of directly relevant backend experience (Python/FastAPI)",
                "Hands-on with Kafka and distributed systems, matching the role's core requirement",
            ],
            "gaps": [
                "~13-month unexplained gap between Innotech and CloudScape (2020-03 to 2021-05)",
            ],
            "unresolved_questions": [
                "What was Priya doing during the 2020-03 to 2021-05 gap between Innotech and CloudScape?",
            ],
        },
    },
    {
        # ADVANCE: clean profile, strong fitment score, no flags — should
        # sail through mandatory + profile-followup phases with the LLM
        # deciding there's nothing further worth asking.
        "name": "Rahul Verma",
        "email": "rahul.verma@example.com",
        "phone": "+91-99887-65432",
        "profile": {
            "current_company": "Zorbit Systems",
            "current_role": "Backend Engineer II",
            "total_experience_years": 4.0,
            "skills": ["Python", "Django", "FastAPI", "PostgreSQL", "Redis", "AWS", "Kubernetes"],
            "education": [
                {"degree": "B.E., Information Technology", "institute": "VJTI Mumbai", "year": 2020}
            ],
            "employment_history": [
                {"company": "Zorbit Systems", "role": "Backend Engineer II", "start": "2020-07", "end": "present"},
            ],
            "location": "Pune",
        },
        "screening_result": {
            "mandatory_gate": "PASSED",
            "fitment_score": 91,
            "recommendation": "ADVANCE",
            "strengths": [
                "4 continuous years at one company shipping backend services in the JD's exact stack",
                "Already based in Pune — no relocation friction for this role",
            ],
            "gaps": [],
            "unresolved_questions": [],
        },
    },
    {
        # REJECTED_AT_GATE: fails a mandatory condition outright (per
        # architecture principle #1, this is a hard gate — never reaches
        # fitment scoring). Demonstrates engine.create_session refusing to
        # issue a screening link for this candidate.
        "name": "Karan Mehta",
        "email": "karan.mehta@example.com",
        "phone": "+91-91234-56789",
        "profile": {
            "current_company": "Freelance",
            "current_role": "Junior Developer",
            "total_experience_years": 0.8,
            "skills": ["Python", "Flask"],
            "education": [
                {"degree": "B.Sc., Computer Science", "institute": "Delhi University", "year": 2025}
            ],
            "employment_history": [
                {"company": "Freelance", "role": "Junior Developer", "start": "2025-02", "end": "present"},
            ],
            "location": "Delhi",
        },
        "screening_result": {
            "mandatory_gate": "REJECTED",
            "gate_failure_reason": (
                "JD requires a minimum of 3 years of professional backend experience; "
                "candidate has 0.8 years."
            ),
            "fitment_score": None,
            "recommendation": "REJECT",
            "strengths": [],
            "gaps": [],
            "unresolved_questions": [],
        },
    },
]


def seed_demo_data() -> None:
    with get_db() as conn:
        existing = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
        if existing:
            return

        cur = conn.execute(
            "INSERT INTO jobs (title, description) VALUES (?, ?)",
            (DEMO_JOB["title"], DEMO_JOB["description"]),
        )
        job_id = cur.lastrowid

        for index, question in enumerate(DEMO_MANDATORY_QUESTIONS):
            conn.execute(
                """INSERT INTO job_questions (job_id, question_text, order_index, is_mandatory)
                   VALUES (?, ?, ?, 1)""",
                (job_id, question, index),
            )

        for candidate in DEMO_CANDIDATES:
            conn.execute(
                """INSERT INTO candidates (job_id, name, email, phone, profile_json, screening_result_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    candidate["name"],
                    candidate["email"],
                    candidate["phone"],
                    json.dumps(candidate["profile"]),
                    json.dumps(candidate["screening_result"]),
                ),
            )

        conn.commit()
