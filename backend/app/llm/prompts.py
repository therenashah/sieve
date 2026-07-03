"""Prompt templates, keyed by use case. Filled in as each pipeline stage is built.

Convention: each entry is a single template string, formatted with the stage's own
inputs (e.g. `RUBRIC_PROMPT.format(jd_text=...)`) before being passed as the sole
`prompt` argument to `llm.client.call_json`. call_json already appends its own
JSON-only system instruction, so templates only need to state the task.
"""

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
