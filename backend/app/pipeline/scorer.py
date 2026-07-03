"""Per-criterion scoring against a rubric, plus selective re-scoring."""


async def score_candidate(profile: dict, rubric: dict) -> dict:
    raise NotImplementedError


async def rescore_criteria(profile: dict, rubric: dict, criterion_names: list[str]) -> dict:
    raise NotImplementedError
