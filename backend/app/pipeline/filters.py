"""Natural-language -> structured filter, executed via a whitelisted query builder."""


async def nl_to_filter(query: str, rubric: dict) -> dict:
    raise NotImplementedError


def execute_filter(candidates: list[dict], filter_spec: dict) -> list[dict]:
    """Apply a filter_spec built only from whitelisted fields/operators."""
    raise NotImplementedError
