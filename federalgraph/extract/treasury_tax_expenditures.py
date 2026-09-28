from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

from federalgraph.common import ensure_dir

UA = "FederalGraph/0.8 (+public-interest research)"
SOURCE = "U.S. Treasury Tax Expenditures"
SOURCE_KEY = "treasury_tax_expenditures"

_HEADER_WORDS = {
    "tax expenditure",
    "tax expenditures",
    "description",
    "item",
    "number",
    "total",
}


def _clean(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _candidate_from_row(values: list[object]) -> tuple[str, str]:
    cleaned = [_clean(v) for v in values]
    nonempty = [(i, v) for i, v in enumerate(cleaned) if v]
    if not nonempty:
        return "", ""

    for i, value in nonempty[:4]:
        if re.fullmatch(r"\d{1,3}", value):
            for _, later in nonempty:
                if later == value:
                    continue
                low = later.lower().rstrip(":")
                if low not in _HEADER_WORDS and len(later) >= 5 and not re.fullmatch(r"[\d,().$%-]+", later):
                    return value, later

    first = nonempty[0][1]
    match = re.match(r"^\s*(\d{1,3})\s*[.|:)\-]\s*(.+)$", first)
    if match and len(match.group(2).strip()) >= 5:
        return match.group(1), match.group(2).strip()
    return "", ""


def records_from_workbook(workbook: bytes, fiscal_year: int, source_url: str) -> list[dict]:
    excel = pd.ExcelFile(io.BytesIO(workbook))
    found: dict[str, dict] = {}
    for sheet in excel.sheet_names:
        frame = pd.read_excel(excel, sheet_name=sheet, header=None, dtype=object)
        function_category = ""
        for row_index, row in frame.iterrows():
            values = list(row.values)
            nonempty = [_clean(v) for v in values if _clean(v)]
            item_no, name = _candidate_from_row(values)
            if item_no and name:
                key = item_no
                existing = found.get(key)
                record = {
                    "source": SOURCE,
                    "source_key": SOURCE_KEY,
                    "source_record_id": f"FY{fiscal_year}:{item_no}",
                    "source_name": name,
                    "source_description": "",
                    "agency_stated_purpose": "",
                    "source_status": "",
                    "source_date": str(fiscal_year),
                    "source_url": source_url,
                    "program_type_raw": "tax_expenditure",
                    "department_source_name": "",
                    "source_publisher_name": "Department of the Treasury",
                    "department_source_code": "",
                    "agency_source_name": "",
                    "agency_source_code": "",
                    "office_source_name": "",
                    "office_source_code": "",
                    "popular_long_name": "",
                    "popular_short_name": "",
                    "related_programs_raw": "",
                    "authorization_raw": "",
                    "function_raw": function_category,
                    "mission_category_raw": function_category,
                    "admission_basis": "official_tax_expenditure_enumeration",
                    "treasury_item_number": item_no,
                    "treasury_sheet": sheet,
                    "treasury_row": int(row_index) + 1,
                }
                if existing is None or len(record["source_name"]) > len(existing["source_name"]):
                    found[key] = record
                continue

            # Treasury tables commonly use single-text category rows before numbered provisions.
            if len(nonempty) == 1:
                candidate = nonempty[0].rstrip(":")
                low = candidate.lower()
                if 3 <= len(candidate) <= 120 and not re.search(r"fiscal year|estimate|million|table \d", low):
                    function_category = candidate

    return sorted(found.values(), key=lambda row: int(row["treasury_item_number"]))


def extract(
    workbook_url: str,
    raw_dir: Path,
    *,
    fiscal_year: int,
    timeout: int = 120,
) -> list[dict]:
    out_dir = raw_dir / "treasury_tax_expenditures"
    ensure_dir(out_dir)
    response = requests.get(workbook_url, headers={"User-Agent": UA}, timeout=timeout)
    response.raise_for_status()
    workbook = response.content
    path = out_dir / f"Tax-Expenditures-FY{fiscal_year}.xlsx"
    path.write_bytes(workbook)
    records = records_from_workbook(workbook, fiscal_year, workbook_url)
    if not records:
        raise RuntimeError(
            "Treasury tax-expenditure workbook was downloaded, but no numbered provisions were recognized. "
            "The workbook format may have changed."
        )
    return records
