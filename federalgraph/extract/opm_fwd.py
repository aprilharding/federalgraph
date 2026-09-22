from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

from federalgraph.common import ensure_dir

UA = "FederalGraph/0.6 (+public-interest research)"
SOURCE_NAME = "OPM Federal Workforce Data"

SYNTHETIC_DEPARTMENTS = {"non-cfo act agency", "other", "unknown", "not reported", ""}


def _norm_col(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _pick_column(columns: Iterable[str], aliases: tuple[str, ...], required: bool = False) -> str:
    lookup = {_norm_col(column): column for column in columns}
    for alias in aliases:
        key = _norm_col(alias)
        if key in lookup:
            return lookup[key]
    if required:
        raise RuntimeError(
            "OPM FWD employment file is missing an expected organization column. "
            f"Looked for {aliases}; available columns are: {sorted(map(str, columns))}"
        )
    return ""


def discover_columns(frame: pd.DataFrame) -> dict[str, str]:
    columns = list(frame.columns)
    return {
        "department": _pick_column(
            columns,
            ("department", "department_name", "departmentname", "dept_name"),
        ),
        "department_code": _pick_column(
            columns,
            ("department_code", "departmentcode", "dept_code"),
        ),
        "agency": _pick_column(
            columns,
            ("agency", "agency_name", "agencyname"),
            required=True,
        ),
        "agency_code": _pick_column(
            columns,
            ("agency_code", "agencycode", "agy"),
        ),
        "subagency": _pick_column(
            columns,
            (
                "subagency",
                "subagency_name",
                "subagencyname",
                "agency_subelement",
                "agency_subelement_name",
                "agency_subelement_translation",
                "agysubt",
            ),
            required=True,
        ),
        "subagency_code": _pick_column(
            columns,
            (
                "subagency_code",
                "subagencycode",
                "agency_subelement_code",
                "agencysubelementcode",
                "agysub",
            ),
        ),
    }


def _clean(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _strip_code_prefix(name: str, code: str) -> str:
    if not name:
        return ""
    if code:
        pattern = rf"^\s*{re.escape(code)}\s*[-–—:]\s*"
        stripped = re.sub(pattern, "", name, flags=re.IGNORECASE).strip()
        if stripped != name:
            return stripped
    return re.sub(r"^[A-Z0-9]{3,6}\s*[-–—:]\s*", "", name).strip()


def _record_id(level: str, code: str, name: str) -> str:
    token = code or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{level}:{token}"


def records_from_dataframe(frame: pd.DataFrame, data_as_of: str, source_url: str) -> list[dict]:
    cols = discover_columns(frame)
    rows: dict[tuple[str, str], dict] = {}

    def add(level: str, name: str, code: str, parent: str, **extra: str) -> None:
        name = _clean(name)
        code = _clean(code)
        parent = _clean(parent)
        if not name:
            return
        if level == "department" and name.lower() in SYNTHETIC_DEPARTMENTS:
            return
        key = (level, code or name.lower())
        rows[key] = {
            "source": SOURCE_NAME,
            "source_record_id": _record_id(level, code, name),
            "source_name": name,
            "source_url": source_url,
            "website": "",
            "description": "",
            "parent_source_name": parent,
            "source_level": level,
            "branch": "Executive Branch",
            "source_as_of": data_as_of,
            "data_as_of": data_as_of,
            "opm_department_code": extra.get("department_code", ""),
            "opm_agency_code": extra.get("agency_code", ""),
            "opm_subagency_code": extra.get("subagency_code", ""),
        }

    for _, source_row in frame.iterrows():
        agency = _clean(source_row.get(cols["agency"], ""))
        department = _clean(source_row.get(cols["department"], "")) if cols["department"] else agency
        department_code = _clean(source_row.get(cols["department_code"], "")) if cols["department_code"] else ""
        agency_code = _clean(source_row.get(cols["agency_code"], "")) if cols["agency_code"] else ""
        raw_subagency = _clean(source_row.get(cols["subagency"], ""))
        subagency_code = _clean(source_row.get(cols["subagency_code"], "")) if cols["subagency_code"] else ""
        subagency = _strip_code_prefix(raw_subagency, subagency_code)

        add(
            "department",
            department,
            department_code,
            "",
            department_code=department_code,
        )
        agency_parent = "" if department.lower() in SYNTHETIC_DEPARTMENTS or agency == department else department
        add(
            "agency",
            agency,
            agency_code,
            agency_parent,
            department_code=department_code,
            agency_code=agency_code,
        )
        sub_parent = agency or department
        if subagency and subagency != agency:
            add(
                "subagency",
                subagency,
                subagency_code,
                sub_parent,
                department_code=department_code,
                agency_code=agency_code,
                subagency_code=subagency_code,
            )

    return sorted(rows.values(), key=lambda row: (row["source_level"], row["source_name"].lower()))


def _select_current_file(files: list[dict]) -> dict:
    if not files:
        raise RuntimeError("OPM FWD API returned no current employment files.")

    def key(item: dict) -> tuple[str, int, int, int]:
        captured = str(item.get("dataCapturedThrough") or item.get("data_captured_through") or "")
        year = int(item.get("year") or 0)
        month = int(item.get("month") or 0)
        version = int(item.get("version") or 0)
        return captured, year, month, version

    return sorted(files, key=key, reverse=True)[0]



def _normalize_month(value: object) -> str:
    raw = str(value or "").strip()
    if raw.isdigit():
        return raw.zfill(2)
    months = {
        "january": "01", "jan": "01", "february": "02", "feb": "02",
        "march": "03", "mar": "03", "april": "04", "apr": "04",
        "may": "05", "june": "06", "jun": "06", "july": "07", "jul": "07",
        "august": "08", "aug": "08", "september": "09", "sep": "09", "sept": "09",
        "october": "10", "oct": "10", "november": "11", "nov": "11",
        "december": "12", "dec": "12",
    }
    return months.get(raw.lower(), raw)

def extract(files_api: str, download_base_url: str, raw_dir: Path, timeout: int = 120) -> list[dict]:
    ensure_dir(raw_dir)
    opm_dir = raw_dir / "opm_fwd"
    ensure_dir(opm_dir)

    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    response = session.get(files_api, params={"current": "true"}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        files = payload.get("results") or payload.get("data") or payload.get("files") or []
    else:
        files = payload
    if not isinstance(files, list):
        raise RuntimeError("Unexpected OPM FWD file-list response shape.")

    (opm_dir / "employment_files.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    selected = _select_current_file(files)
    year = str(selected.get("year"))
    month = _normalize_month(selected.get("month"))
    version = str(selected.get("version"))
    data_as_of = str(
        selected.get("dataCapturedThrough")
        or selected.get("data_captured_through")
        or f"{year}-{month}"
    )
    download_url = f"{download_base_url.rstrip('/')}/{year}/{month}/{version}/download"

    parquet_path = opm_dir / f"employment_{year}_{month}_v{version}.parquet"
    with session.get(download_url, timeout=timeout, stream=True) as download:
        download.raise_for_status()
        with parquet_path.open("wb") as handle:
            for chunk in download.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)

    frame = pd.read_parquet(parquet_path)
    records = records_from_dataframe(frame, data_as_of, download_url)
    if not records:
        raise RuntimeError("OPM FWD extraction produced zero organization records.")

    pd.DataFrame(records).to_csv(opm_dir / "organization_records.csv", index=False)
    return records
