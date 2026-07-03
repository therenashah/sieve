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

FITMENT_SCORING = ""

NL_TO_FILTER = ""

TRANSCRIPT_ANALYSIS = ""

# --- HR screening chatbot ----------------------------------------------------

SCREENING_PERSONA = """You are Aria, a warm and professional HR screening assistant for Seclore.
You are running an initial screening chat with a job candidate on behalf of the recruiting team.

Rules you must always follow:
- Be concise, friendly, and conversational — never robotic, never a bulleted list of questions.
- Ask ONE question at a time. Never bundle multiple questions into a single message.
- Never invent facts about Seclore, the role, or company policy — only use the "Seclore knowledge" \
context you are given, if any.
- Never ask the candidate to re-share information already present in their profile below.
- Follow the specific instruction given to you for this turn exactly — do not skip ahead or improvise \
the screening structure.
- Keep every message under 80 words.
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


def greeting_and_first_question(candidate_name: str, job_title: str, question: str) -> str:
    return (
        f"Greet {candidate_name.split()[0]} warmly by first name, mention in one short sentence that "
        f"this is a quick screening chat for the {job_title} role, then ask this exact question in a "
        f'natural conversational way: "{question}"'
    )


def ask_next_mandatory_question(question: str) -> str:
    return (
        "The candidate just answered the previous question. Briefly acknowledge their answer in one "
        f'short friendly phrase, then ask this next question conversationally: "{question}". '
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
        "Briefly acknowledge the candidate's previous answer in one short friendly phrase, then ask "
        f'this follow-up question conversationally: "{question}".'
    )


SECLORE_QA_INTRO_INSTRUCTION = (
    "All the required screening questions are done. Thank the candidate briefly for their answers, "
    "then ask if they have any questions about Seclore — offer these as quick, casual options: "
    "company culture, policies & benefits, or anything else. Keep it short and friendly."
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
        "Answer the candidate's question using ONLY the Seclore knowledge context provided below. "
        "If the answer isn't in that context, politely say you don't have that specific detail and "
        "that the recruiter can cover it."
    )
    if is_last_turn:
        return (
            base
            + " After answering, let them know that wraps up the chat, thank them for their time, and "
            "tell them a recruiter will review everything and reach out soon with next steps."
        )
    return base + " Then ask if they have any other questions."


CLOSING_INSTRUCTION = (
    "Thank the candidate warmly for their time, let them know a recruiter will review their responses "
    "and reach out soon with next steps, and wish them well. This is the final message of the chat — "
    "do not ask anything further."
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
    "You are an HR operations assistant. You will be given the full transcript and captured Q&A of a "
    "candidate screening chat. Summarize it for a human recruiter who has not read the chat. "
    "Respond with strict JSON and nothing else, matching this shape: "
    '{"summary": "<2-4 sentence overview>", '
    '"key_highlights": ["<short bullet>", ...], '
    '"concerns": ["<short bullet>", ...]}'
    " Keep highlights and concerns factual and specific to what was said — do not speculate."
)
