from __future__ import annotations
from pathlib import Path
import pandas as pd

def extract(path: Path) -> list[dict]:
    if not path or not path.exists():
        return []
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    dept_col = cols.get("department")
    agency_col = cols.get("agency")
    if not dept_col or not agency_col:
        raise ValueError("FPI CSV must contain Department and Agency columns.")
    records = []
    # Top-level department records
    for name in sorted(df[dept_col].dropna().astype(str).unique()):
        records.append({
            "source": "Current Federal Program Inventory",
            "source_record_id": "department:" + name,
            "source_name": name,
            "source_url": "",
            "website": "",
            "description": "",
            "parent_source_name": "",
            "source_level": "department",
            "branch": "Executive",
        })
    # Components
    for _, row in df[[dept_col, agency_col]].dropna().drop_duplicates().iterrows():
        dept, agency = str(row[dept_col]), str(row[agency_col])
        if agency == dept:
            continue
        records.append({
            "source": "Current Federal Program Inventory",
            "source_record_id": "agency:" + dept + ":" + agency,
            "source_name": agency,
            "source_url": "",
            "website": "",
            "description": "",
            "parent_source_name": dept,
            "source_level": "agency/component",
            "branch": "Executive",
        })
    return records
