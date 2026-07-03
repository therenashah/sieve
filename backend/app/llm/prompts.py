"""Prompt templates, keyed by use case. Filled in as each pipeline stage is built.

Convention: each entry is a (system_prompt, user_prompt_template) pair, where the
user template is formatted with the stage's own inputs before being passed to
`llm.client.call_json`.
"""

RUBRIC_GENERATION: dict[str, str] = {
    "system": "",
    "user_template": "",
}

MANDATORY_GATE_CHECK: dict[str, str] = {
    "system": "",
    "user_template": "",
}

FITMENT_SCORING: dict[str, str] = {
    "system": "",
    "user_template": "",
}

NL_TO_FILTER: dict[str, str] = {
    "system": "",
    "user_template": "",
}

TRANSCRIPT_ANALYSIS: dict[str, str] = {
    "system": "",
    "user_template": "",
}
