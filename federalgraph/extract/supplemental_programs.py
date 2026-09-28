from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


def extract(path: Path, source_key: str = "supplemental") -> list[dict]:
    frame = pd.read_csv(path).fillna("")
    lookup = {re.sub(r"[^a-z0-9]", "", c.lower()): c for c in frame.columns}

    def col(*names: str) -> str:
        for name in names:
            key = re.sub(r"[^a-z0-9]", "", name.lower())
            if key in lookup:
                return lookup[key]
        return ""

    name_col = col("program", "program_name", "program title", "name")
    if not name_col:
        raise RuntimeError(f"Supplemental program CSV {path} needs a Program/Program Name column.")
    id_col = col("source_record_id", "program code", "program id", "id")
    source_col = col("source", "source system")
    purpose_col = col("purpose", "description", "program description")
    type_col = col("program type", "type")
    dept_col = col("department")
    agency_col = col("agency")
    office_col = col("office")
    authority_col = col("statute", "authority", "authorizing statute")
    url_col = col("source url", "url")

    rows: list[dict] = []
    for idx, row in frame.iterrows():
        name = str(row.get(name_col, "")).strip()
        if not name:
            continue
        rows.append(
            {
                "source": str(row.get(source_col, "")).strip() if source_col else path.name,
                "source_key": source_key,
                "source_record_id": str(row.get(id_col, "")).strip() if id_col else f"row:{idx + 2}",
                "source_name": name,
                "source_description": str(row.get(purpose_col, "")).strip() if purpose_col else "",
                "agency_stated_purpose": str(row.get(purpose_col, "")).strip() if purpose_col else "",
                "source_status": "",
                "source_date": "",
                "source_url": str(row.get(url_col, "")).strip() if url_col else "",
                "program_type_raw": str(row.get(type_col, "")).strip() if type_col else "",
                "department_source_name": str(row.get(dept_col, "")).strip() if dept_col else "",
                "department_source_code": "",
                "agency_source_name": str(row.get(agency_col, "")).strip() if agency_col else "",
                "agency_source_code": "",
                "office_source_name": str(row.get(office_col, "")).strip() if office_col else "",
                "office_source_code": "",
                "popular_long_name": "",
                "popular_short_name": "",
                "related_programs_raw": "",
                "authorization_raw": str(row.get(authority_col, "")).strip() if authority_col else "",
                "function_raw": "",
                "mission_category_raw": "",
                "admission_basis": "official_supplemental_source_candidate",
            }
        )
    return rows
