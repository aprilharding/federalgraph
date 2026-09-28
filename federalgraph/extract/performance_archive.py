from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from federalgraph.common import ensure_dir

UA = "FederalGraph/0.8 (+public-interest research)"
SOURCE = "Performance.gov Federal Program Inventory Archive"
SOURCE_KEY = "performance_fpi_archive"


def records_from_reference_csv(text: str, source_url: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    fields = {re.sub(r"[^a-z0-9]", "", f.lower()): f for f in reader.fieldnames}

    def field(*names: str) -> str:
        for name in names:
            key = re.sub(r"[^a-z0-9]", "", name.lower())
            if key in fields:
                return fields[key]
        return ""

    name_col = field("program", "program name", "program title", "title")
    code_col = field("program code", "program id", "code")
    agency_col = field("agency", "agency name")
    dept_col = field("department", "department name")
    desc_col = field("description", "program description", "purpose")
    if not name_col:
        return []

    rows: list[dict] = []
    for idx, row in enumerate(reader, start=2):
        name = (row.get(name_col) or "").strip()
        if not name:
            continue
        code = (row.get(code_col) or "").strip() if code_col else ""
        agency = (row.get(agency_col) or "").strip() if agency_col else ""
        department = (row.get(dept_col) or "").strip() if dept_col else ""
        description = (row.get(desc_col) or "").strip() if desc_col else ""
        rows.append(
            {
                "source": SOURCE,
                "source_key": SOURCE_KEY,
                "source_record_id": code or f"row:{idx}",
                "source_name": name,
                "source_description": description,
                "agency_stated_purpose": description,
                "source_status": "historical",
                "source_date": "",
                "source_url": source_url,
                "program_type_raw": "",
                "department_source_name": department,
                "department_source_code": "",
                "agency_source_name": agency,
                "agency_source_code": "",
                "office_source_name": "",
                "office_source_code": "",
                "popular_long_name": "",
                "popular_short_name": "",
                "related_programs_raw": "",
                "authorization_raw": "",
                "function_raw": "",
                "mission_category_raw": "",
                "admission_basis": "historical_official_program_inventory",
            }
        )
    return rows


def _table_records(html: str, source_url: str, agency_name: str = "") -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []
    for table_no, table in enumerate(soup.find_all("table"), start=1):
        trs = table.find_all("tr")
        if not trs:
            continue
        headers = [re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip() for cell in trs[0].find_all(["th", "td"])]
        header_norm = [h.lower() for h in headers]
        program_idx = next((i for i, h in enumerate(header_norm) if "program" in h and ("name" in h or "title" in h or h == "program")), None)
        if program_idx is None:
            continue
        description_idx = next((i for i, h in enumerate(header_norm) if "description" in h or "purpose" in h), None)
        code_idx = next((i for i, h in enumerate(header_norm) if "program code" in h or h == "code"), None)
        agency_idx = next((i for i, h in enumerate(header_norm) if h in {"agency", "agency name"}), None)
        for row_no, tr in enumerate(trs[1:], start=2):
            cells = [re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip() for cell in tr.find_all(["td", "th"])]
            if program_idx >= len(cells) or not cells[program_idx]:
                continue
            name = cells[program_idx]
            desc = cells[description_idx] if description_idx is not None and description_idx < len(cells) else ""
            code = cells[code_idx] if code_idx is not None and code_idx < len(cells) else ""
            agency = cells[agency_idx] if agency_idx is not None and agency_idx < len(cells) else agency_name
            rows.append(
                {
                    "source": SOURCE,
                    "source_key": SOURCE_KEY,
                    "source_record_id": code or f"table:{table_no}:row:{row_no}",
                    "source_name": name,
                    "source_description": desc,
                    "agency_stated_purpose": desc,
                    "source_status": "historical",
                    "source_date": "",
                    "source_url": source_url,
                    "program_type_raw": "",
                    "department_source_name": agency_name,
                    "department_source_code": "",
                    "agency_source_name": agency,
                    "agency_source_code": "",
                    "office_source_name": "",
                    "office_source_code": "",
                    "popular_long_name": "",
                    "popular_short_name": "",
                    "related_programs_raw": "",
                    "authorization_raw": "",
                    "function_raw": "",
                    "mission_category_raw": "",
                    "admission_basis": "historical_official_program_inventory",
                }
            )
    return rows


def extract(
    main_url: str,
    raw_dir: Path,
    *,
    reference_csv_url: str = "",
    timeout: int = 90,
) -> list[dict]:
    out_dir = raw_dir / "performance_fpi_archive"
    ensure_dir(out_dir)
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    if reference_csv_url:
        response = session.get(reference_csv_url, timeout=timeout)
        response.raise_for_status()
        (out_dir / "reference_table.csv").write_bytes(response.content)
        records = records_from_reference_csv(response.text, response.url)
        if records:
            return records

    response = session.get(main_url, timeout=timeout)
    response.raise_for_status()
    (out_dir / "federalprograminventory.html").write_text(response.text, encoding="utf-8")
    records = _table_records(response.text, response.url)

    # The archive has moved over time. Follow only local links plausibly related to the FPI,
    # then parse explicit program tables. We deliberately do not infer programs from arbitrary headings.
    soup = BeautifulSoup(response.text, "html.parser")
    candidates: list[tuple[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        href = urljoin(response.url, anchor["href"])
        marker = f"{label} {href}".lower()
        if "program" in marker or "federalprograminventory" in marker:
            if href.startswith("http") and "performance.gov" in href:
                candidates.append((label, href))

    seen = {response.url}
    for label, url in candidates[:100]:
        if url in seen:
            continue
        seen.add(url)
        try:
            child = session.get(url, timeout=timeout)
            child.raise_for_status()
        except requests.RequestException:
            continue
        child_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", url.rsplit("/", 1)[-1] or "page")[:100]
        (out_dir / child_name).write_text(child.text, encoding="utf-8")
        records.extend(_table_records(child.text, child.url, agency_name=label))

    # Deduplicate exact archive source records; zero is permitted because archive HTML changes.
    unique: dict[tuple[str, str], dict] = {}
    for row in records:
        unique[(row["source_record_id"], row["source_name"])] = row
    return list(unique.values())
