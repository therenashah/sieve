"""Resume file (PDF/DOCX) -> raw text. Keep this dumb; the LLM does structuring."""


def parse_pdf(file_bytes: bytes) -> str:
    raise NotImplementedError


def parse_docx(file_bytes: bytes) -> str:
    raise NotImplementedError


def parse_resume(filename: str, file_bytes: bytes) -> str:
    """Dispatch to the right parser based on file extension."""
    raise NotImplementedError
