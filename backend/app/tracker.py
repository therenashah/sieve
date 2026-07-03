"""Parses the recruiter's candidate tracker (CSV or Excel export) into rows
ready for the `candidates` table. Column names are matched case/whitespace
insensitively so minor header drift doesn't break the upload.
"""

import io

import pandas as pd

# tracker column -> candidates table column
_COLUMN_MAP = {
    "candidate name": "name",
    "candidate id": "external_id",
    "match score (ai based)": "match_score",
    "overall status": "overall_status",
    "email": "email",
    "phone number": "phone",
    "recruiter": "recruiter",
    "tags": "tags",
    "application date": "application_date",
    "source type": "source_type",
    "source name": "source_name",
    "candidate ownership status": "ownership_status",
    "shortlisting": "shortlisting_status",
    "resume screening": "resume_screening_status",
    "l1 interview": "l1_status",
    "l2 interview": "l2_status",
    "l3 interview": "l3_status",
    "pre-offer": "pre_offer_status",
}


def parse_tracker(filename: str, content: bytes) -> tuple[list[dict], list[dict]]:
    buf = io.BytesIO(content)
    if filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(buf, dtype=str)
    else:
        df = pd.read_csv(buf, dtype=str)

    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df.fillna("")

    rows: list[dict] = []
    errors: list[dict] = []

    for position, (_, raw_row) in enumerate(df.iterrows()):
        record = {field: str(raw_row.get(col, "")).strip() for col, field in _COLUMN_MAP.items()}
        row_number = position + 2  # header is row 1

        if not record["name"] or not record["external_id"]:
            errors.append({"row": row_number, "reason": "Missing Candidate Name or Candidate ID — row skipped"})
            continue

        if record["match_score"]:
            try:
                record["match_score"] = int(float(record["match_score"]))
            except ValueError:
                errors.append({"row": row_number, "reason": f"Unreadable match score '{record['match_score']}' — left blank"})
                record["match_score"] = None
        else:
            record["match_score"] = None

        rows.append(record)

    return rows, errors
