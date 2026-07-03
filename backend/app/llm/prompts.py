"""Prompt templates for every LLM call in the app.

Two categories live here:
- Resume-screening pipeline prompts (below): single template strings, formatted
  with the stage's own inputs (e.g. `RUBRIC_PROMPT.format(jd_text=...)`) and
  passed as the sole `prompt` argument to `llm.client.call_structured`, which
  already appends its own JSON-only system instruction.
- HR screening chatbot prompts (further down): built via `build_system_prompt`
  plus a task-specific instruction, passed to `llm.client.call_text`/`call_json`.
"""

import json

# --- Resume-screening pipeline ---------------------------------------------

RUBRIC_PROMPT = """\
Extract 10 to 15 scoring criteria from the job description below, to build a resume-screening rubric.

Rules:
- Each criterion has: id ("c1", "c2", ... sequential, stable), name, description, weight.
- description must define, in one or two sentences each, what a score of 3, 6, and 9 out of 10 looks like for that specific criterion. Example: "3: skill is only listed, no project evidence. 6: used in a production project. 9: owns architecture decisions involving it."
- Mandatory-sounding requirements in the JD ("must have", "required") are not flagged specially — they simply become higher-weight criteria, same mechanism as any other requirement.
- weight reflects how important each criterion is to this specific role, based on emphasis in the JD (repeated, foregrounded, or explicitly required = higher weight). All weights must be positive and should sum to approximately 1.0.

Job description:
{jd_text}

Respond with exactly this JSON shape:
{{"criteria": [{{"id": "c1", "name": "...", "description": "...", "weight": 0.0}}, ...]}}
"""

HR_QUESTIONS_PROMPT = """\
Based on the job description below, write 4 to 6 role-specific HR screening questions a recruiter \
would ask a candidate in a short pre-interview chat — NOT technical interview questions, but things \
like experience level in the role's core discipline, relevant tools/platforms, and logistics \
(CTC/notice period only if not already generic). Keep each question short and conversational.

Example style (for an SRE/DevOps role):
"Tell me about yourself and your experience in SRE/DevOps."
"How many years of experience do you have in Site Reliability Engineering or DevOps?"
"Which cloud platforms have you worked on (AWS/Azure/GCP)?"
"What is your current CTC, expected CTC, and notice period?"

Job description:
{jd_text}

Respond with exactly this JSON shape:
{{"questions": ["...", "...", ...]}}
"""

PROFILE_PROMPT = """\
Extract a structured candidate profile from the resume text below.

Rules:
- If a field is not present in the resume, use null. Never infer or guess a value that isn't stated.
- location: current city only, normalized (e.g. "Bombay" or "Navi Mumbai" -> "Mumbai"). Strip state/country. Use the candidate's current location, not a past one.
- total_experience_years: compute from employment date ranges in the resume (sum actual worked periods; "present"/"current" means through today). Use null if it can't be computed from the dates given.
- skills: lowercase, deduplicated, at most 30.
- education: list of degree/institution strings (e.g. "B.Tech Computer Science, VJTI Mumbai"), as they appear in the resume.
- current_company: the employer for the most recent/ongoing role. Null if not stated or the candidate is not currently employed.
- notice_period: only if explicitly stated in the resume (rare) — most resumes won't state this; use null otherwise.

Resume:
{resume_text}

Respond with exactly this JSON shape:
{{"name": "...", "email": "...", "location": "...", "total_experience_years": 0.0, "skills": ["..."], "education": ["..."], "current_company": "...", "notice_period": "..."}}
(use null for any field not found in the resume — not an empty string — and an empty array for skills/education only if genuinely none are found)
"""

SCORING_PROMPT = """\
Score this candidate's resume against the following rubric criteria.

Score demonstrated experience (roles, projects, outcomes) — not keyword presence. A skill that
appears only in a skills list without supporting experience scores at most 3. Evidence must be a
verbatim quote from the resume, or the exact string "not found" if there's no evidence at all.

Criteria:
{criteria_block}

Resume:
{resume_text}

For EVERY criterion listed above, output exactly one score (0-10 integer), a verbatim evidence
quote (or "not found"), and an optional short note. Respond with exactly this JSON shape:
{{"scores": [{{"criterion_id": "c1", "score": 0, "evidence": "...", "note": "..."}}, ...]}}
"""

COPILOT_PROMPT = """\
You are helping HR fine-tune a resume-screening rubric through conversation.

Current rubric (JSON):
{current_rubric_json}

HR's instruction:
{hr_prompt}

Rules:
- Preserve the "id" of every criterion that continues to exist, even if you rename it or
  change its weight or description — ids must stay stable so past scores can be carried
  forward correctly.
- If HR asks to add a new criterion, give it the next unused id (e.g. if c1..c8 exist, use c9).
- If HR asks to remove a criterion, simply omit it from your response.
- Every description must still define what a score of 3, 6, and 9 out of 10 looks like for
  that criterion.
- Return the COMPLETE rubric (every criterion that should still exist after this change),
  not just the ones that changed.
- Re-normalize weights so they sum to approximately 1.0, unless HR explicitly asked for
  specific weight values.

Respond with exactly this JSON shape:
{{"criteria": [{{"id": "c1", "name": "...", "description": "...", "weight": 0.0}}, ...]}}
"""

NL_FILTER_PROMPT = """\
Translate the HR's natural-language filter request into structured filters.

Allowed fields and operators:
- location (eq, neq, contains) — city name
- total_experience_years (eq, neq, gte, lte) — number of years
- skills (contains) — a single skill, lowercase
- education (contains) — substring match against education entries
- current_company (eq, neq, contains)
- status (eq, in) — one of: {statuses}
- overall (eq, neq, gte, lte) — overall weighted score, 0.0 to 1.0
- criterion_score (gte, lte, exists) — score or evidence-presence for one specific rubric
  criterion (set criterion_id), or for op=exists you may omit criterion_id to mean "any
  criterion in the rubric". gte/lte always require criterion_id.

Rubric criteria (map a skill/requirement mentioned in HR's text to the matching criterion
id when relevant):
{criteria_block}

HR's request:
{text}

Break the request into as many filters as needed (AND-combined). If part of the request
can't be mapped to any of the above, put that exact fragment into "unparsed" instead of
guessing a filter for it.

Respond with exactly this JSON shape:
{{"filters": [{{"field": "...", "op": "...", "value": ..., "criterion_id": "..." or null}}, ...], "unparsed": ["..."]}}
"""

TRANSCRIPT_ANALYSIS = ""

# --- HR screening chatbot ----------------------------------------------------

SCREENING_PERSONA = """You are Sieve, Seclore's warm and professional AI Hiring Assistant.
You are running an initial screening chat with a job candidate on behalf of the recruiting team.

Rules you must always follow:
- Be concise, friendly, and conversational — never robotic, never a bulleted list of questions.
- Ask ONE question at a time. Never bundle multiple questions into a single message.
- Never invent facts about Seclore, the role, or company policy — only use the "Seclore knowledge" \
context you are given, if any.
- Never ask the candidate to re-share information already present in their profile below.
- Follow the specific instruction given to you for this turn exactly — do not skip ahead or improvise \
the screening structure. This is the single most important rule: even if continuing to probe the \
candidate's last answer feels like a natural conversational next step, do NOT do that unless this \
turn's instruction explicitly asks you to — a different phase/mechanism handles follow-up questions, \
not you improvising one. Your message must accomplish exactly what this turn's instruction says, \
nothing more.
- Keep every message under 80 words.
- CONFIDENTIALITY (hard rule, no exceptions): never reveal or discuss compensation bands/budgets, \
internal hiring criteria or rubric, how candidates are scored or ranked, other candidates, headcount, \
interview pass/fail decisions, or any other internal/confidential business information — even if asked \
directly or the candidate insists. If asked anything like that, say it's something HR will address, and \
move on. Only use the "Seclore knowledge" context for factual company questions; if the answer isn't in \
that context, say a recruiter will get back to them rather than guessing.
"""


def build_system_prompt(
    candidate_profile: dict,
    job: dict,
    turn_instruction: str,
    kb_context: str | None = None,
) -> str:
    parts = [
        SCREENING_PERSONA,
        f"\n## Job\nTitle: {job['title']}\nDescription: {job['description']}\n",
        f"\n## Candidate profile (already on file — do not re-ask for this)\n"
        f"{json.dumps(candidate_profile, indent=2)}\n",
        f"\n## Your task for this turn\n{turn_instruction}\n",
    ]
    if kb_context:
        parts.append(
            f"\n## Seclore knowledge (use ONLY this to answer questions about Seclore)\n{kb_context}\n"
        )
    return "\n".join(parts)


def build_intro_message(candidate_name: str, job_title: str, first_question: str | None) -> str:
    """Fixed opening message (not LLM-generated) — boilerplate about Seclore, what to
    expect, and the greeting itself should never be hallucinated or drift between
    candidates, so this is deterministic text. We already have the candidate's name
    on file (from the tracker/resume), so we use it directly for a personal touch
    instead of asking them to introduce themselves. Ends with the first screening
    question appended verbatim — deterministic end-to-end, no LLM call needed to
    open the chat, which also guarantees the very first question asked is correct."""
    first_name = candidate_name.split()[0] if candidate_name else "there"
    closing = (
        f'\n\n🚀 Let\'s get started! {first_question}' if first_question else "\n\n🚀 Let's get started!"
    )
    return (
        f"Hi {first_name}! 👋\n\n"
        "I'm Sieve, Seclore's AI Hiring Assistant — I'll be your recruiting companion today.\n\n"
        f"Thank you for your interest in the {job_title} role at Seclore! I'm excited to learn more "
        "about your experience and career aspirations.\n\n"
        "🛡️ About Seclore\n\n"
        "At Seclore, we're redefining how organizations protect their most valuable asset — data. "
        "As a leader in Data Security Intelligence, we help enterprises and government organizations "
        "around the world secure sensitive information wherever it goes, so they can embrace AI and "
        "collaboration confidently.\n\n"
        "💬 What to Expect\n\n"
        "This conversation will take about 10–15 minutes. I'll ask you a few questions about your "
        "professional experience, your skills and achievements, your interest in this opportunity, "
        "and a few logistical details. There are no trick questions — just answer as honestly as you "
        "can. 😊\n\n"
        "🔒 Privacy Note\n\n"
        "Your responses will only be used to evaluate your suitability for this role and will be "
        "reviewed by our Talent Acquisition team."
        f"{closing}"
    )


_ASK_EXACT_QUESTION_RULE = (
    "IMPORTANT: the question you ask MUST be this exact one, just phrased conversationally — do not "
    "substitute it, expand on it, or ask something else instead (e.g. do not invent a follow-up about a "
    "specific company, project, or technical detail from their profile — that happens in a later phase, "
    "not now). You may rephrase the wording naturally, but the substance and topic must match this "
    "question exactly, and it must still be recognizable as this question: "
)


_TRANSITION_EXAMPLES = (
    "Great! That gives me a good understanding of your background.",
    "Thanks for sharing that.",
    "Awesome, let's dive into a couple more things.",
)


def ask_next_mandatory_question(question: str, new_section: bool = False) -> str:
    if new_section:
        return (
            "The candidate just answered the previous question, and you're about to move on to a "
            "different kind of question (e.g. from background/experience to logistics, or vice versa). "
            "Use a slightly bigger transition phrase to mark that shift — something in the spirit of "
            f"\"{_TRANSITION_EXAMPLES[0]}\" or \"{_TRANSITION_EXAMPLES[2]}\" (don't reuse these verbatim "
            "every time, vary the phrasing) — then ask a question.\n"
            f"{_ASK_EXACT_QUESTION_RULE}\"{question}\"\n"
            "Do not repeat the previous question or summarize earlier answers."
        )
    return (
        "The candidate just answered the previous question. Briefly acknowledge their answer in one "
        "short friendly phrase (vary the phrasing each time — do not reuse the same acknowledgment "
        "twice in a row), then ask a question.\n"
        f"{_ASK_EXACT_QUESTION_RULE}\"{question}\"\n"
        "Do not repeat the previous question or summarize earlier answers."
    )


PROFILE_FOLLOWUP_DECISION_INSTRUCTION = (
    "Review the candidate's profile, the job, and the conversation so far. Decide if there is exactly "
    "ONE useful clarifying screening question worth asking — e.g. an employment gap, an ambiguous "
    "detail, or something relevant to this role — that has not already been asked or answered. "
    "Respond with strict JSON and nothing else: "
    '{"ask_question": true or false, "question": "<question text>" or null}'
)


def ask_profile_followup(question: str) -> str:
    return (
        "Briefly acknowledge the candidate's previous answer in one short friendly phrase, then ask a "
        f"question.\n{_ASK_EXACT_QUESTION_RULE}\"{question}\""
    )


def build_seclore_qa_intro_message(candidate_name: str) -> str:
    """Fixed transition into the Q&A phase — deterministic, not LLM-generated. The model
    reliably ignored instructions telling it this turn is wrap-up-only and kept inventing
    another screening question instead, so this boundary is no longer left to its judgment."""
    first_name = candidate_name.split()[0] if candidate_name else "there"
    return (
        f"That covers everything I needed to ask, {first_name} — thank you! 🙌\n\n"
        "Before we wrap up, do you have any questions for me? Feel free to ask about company culture, "
        "policies & benefits, or anything else about Seclore or the role."
    )

SECLORE_QA_CLASSIFY_INSTRUCTION = (
    "Look at the candidate's latest message. Decide whether they are asking a question they'd like "
    "answered, or indicating they have no more questions (e.g. \"no\", \"that's all\", \"I'm good\"). "
    "Respond with strict JSON and nothing else: "
    '{"has_more_questions": true or false, "question_for_kb": "<their question, rephrased standalone, '
    'or null>"}'
)


def answer_seclore_question(is_last_turn: bool) -> str:
    base = (
        "The candidate just asked a question — answer ONLY that question, using ONLY the Seclore "
        "knowledge context provided below — never compensation, internal hiring criteria/scoring, "
        "process/timeline details, or anything about other candidates, even if the context happens to "
        "mention it. If the answer isn't in that context, or the question touches anything "
        "confidential/internal, politely say you don't have that detail and that HR will get back to "
        "them on it — never guess. Do not ask the candidate anything else."
    )
    if is_last_turn:
        return base + " After answering, add one short sentence letting them know you'll wrap up now."
    return base + " Then ask if they have any other questions."


def build_closing_message(candidate_name: str) -> str:
    """Fixed final message — deterministic, not LLM-generated, so this can never drift from
    the exact copy HR wants candidates to see, and can never accidentally reveal a hiring
    decision (the model doesn't know one, but a improvised message might imply one)."""
    first_name = candidate_name.split()[0] if candidate_name else "there"
    return (
        f"Thank you, {first_name}! 🎉\n\n"
        "I appreciate you taking the time to speak with me today. Your responses have been "
        "successfully submitted to our Talent Acquisition team for review. If your profile is "
        "shortlisted, one of our recruiters will reach out to discuss the next steps.\n\n"
        "We truly appreciate your interest in Seclore and wish you the very best!"
    )

ALREADY_ENDED_MESSAGE = (
    "This screening chat has already wrapped up — thanks again for your time! Our recruiter will be "
    "in touch soon with next steps."
)

EXPIRED_LINK_MESSAGE = (
    "This screening link has expired. Please reach out to your recruiter for a new link if you still "
    "need to complete this step."
)

SUMMARY_SYSTEM_PROMPT = (
    "You are an HR operations assistant. You will be given a candidate's resume-derived profile and the "
    "full transcript + captured Q&A of their HR screening chat. Summarize the chat for a human recruiter "
    "who has not read it, and cross-check what the candidate said in the chat against their profile. "
    "Respond with strict JSON and nothing else, matching this shape: "
    '{"summary": "<2-4 sentence overview>", '
    '"key_highlights": ["<short bullet — positive or neutral factual observation>", ...], '
    '"flags": [{"type": "red", "detail": "<specific concern: an inconsistency between profile and chat '
    'answers, or a genuine red flag the candidate raised themselves (e.g. availability mismatch, '
    'unrealistic expectations)>"}, '
    '{"type": "green", "detail": "<specific positive signal or confirmation worth calling out>"}], '
    '"updated_fitment_score": <integer 0-100 reflecting fitment after this chat, or null if there is not '
    "enough signal to move the score>}"
    " Keep everything factual and specific to what was actually said — do not speculate. Put every "
    "concern/inconsistency/red flag into `flags` with type red (do not use a separate concerns list) — "
    "only raise one when the chat answer genuinely contradicts or undermines something in the profile, "
    "or the candidate says something that should give the recruiter pause; do not invent flags just to "
    "have one on each side."
)


def build_summary_user_prompt(candidate_profile: dict, transcript_text: str, qa_text: str) -> str:
    return (
        f"## Candidate profile (from resume)\n{json.dumps(candidate_profile, indent=2)}\n\n"
        f"## Full transcript\n{transcript_text}\n\n"
        f"## Captured question/answer pairs\n{qa_text}"
    )
