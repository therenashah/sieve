"""Rubric generation, copilot-assisted editing, diff/apply, all per JD."""


async def generate_rubric(jd_text: str) -> dict:
    raise NotImplementedError


async def propose_rubric_edit(rubric: dict, instruction: str) -> dict:
    """Copilot: natural-language instruction -> proposed rubric diff."""
    raise NotImplementedError


def diff_rubric(current: dict, proposed: dict) -> dict:
    raise NotImplementedError


def apply_rubric_diff(current: dict, diff: dict) -> dict:
    raise NotImplementedError
