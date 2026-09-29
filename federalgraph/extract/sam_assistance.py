from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests

from federalgraph.common import ensure_dir

UA = "FederalGraph/0.8 (+public-interest research)"
SOURCE = "SAM.gov Assistance Listings"
SOURCE_KEY = "sam_assistance"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if value not in (None, "", [], {}) else ""


def _authorization_citation(item: dict[str, Any]) -> str:
    parts: list[str] = []
    usc = item.get("USC") or item.get("usc") or {}
    if usc.get("title") and usc.get("section"):
        parts.append(f"{usc['title']} U.S.C. {usc['section']}")
    public_law = item.get("publicLaw") or {}
    if public_law.get("congressCode") and public_law.get("number"):
        parts.append(f"Pub. L. {public_law['congressCode']}-{public_law['number']}")
    statute = item.get("statute") or {}
    if statute.get("volume") and statute.get("page"):
        parts.append(f"{statute['volume']} Stat. {statute['page']}")
    act = item.get("act") or {}
    if act.get("description"):
        parts.append(str(act["description"]).strip())
    return "; ".join(dict.fromkeys(part for part in parts if part))


def records_from_payload(payload: dict[str, Any], source_url: str) -> tuple[list[dict], list[dict], list[dict]]:
    programs: list[dict] = []
    authorities: list[dict] = []
    functions: list[dict] = []

    for item in payload.get("assistanceListingsData") or []:
        listing_id = str(item.get("assistanceListingId") or item.get("programId") or "").strip()
        if not listing_id:
            continue
        org = item.get("federalOrganization") or {}
        overview = item.get("overview") or {}
        auth_container = item.get("authorizations") or {}
        auth_list = auth_container.get("list") or []
        function_list = overview.get("functionalCodes") or []
        mission = overview.get("missionSubCategories") or {}
        assistance_types = item.get("assistanceTypes") or item.get("assistanceType") or []
        programs.append(
            {
                "source": SOURCE,
                "source_key": SOURCE_KEY,
                "source_record_id": listing_id,
                "source_name": str(item.get("title") or "").strip(),
                "source_description": str(overview.get("assistanceListingDescription") or "").strip(),
                "agency_stated_purpose": str(overview.get("objective") or "").strip(),
                "source_status": str(item.get("status") or "").strip(),
                "source_date": str(item.get("publishedDate") or "").strip(),
                "source_url": str(item.get("programWebPage") or source_url),
                "program_type_raw": _json(assistance_types),
                "federal_agency_raw": "",
                "department_source_name": str(org.get("department") or "").strip(),
                "department_source_code": str(org.get("departmentCode") or "").strip(),
                "agency_source_name": str(org.get("agency") or "").strip(),
                "agency_source_code": str(org.get("agencyCode") or "").strip(),
                "office_source_name": str(org.get("office") or "").strip(),
                "office_source_code": str(org.get("officeCode") or "").strip(),
                "popular_long_name": str(item.get("popularLongName") or "").strip(),
                "popular_short_name": str(item.get("popularShortName") or "").strip(),
                "related_programs_raw": _json(item.get("relatedFederalAssistance")),
                "authorization_raw": _json(auth_container),
                "function_raw": _json(function_list),
                "mission_category_raw": _json(mission),
                "admission_basis": "official_program_enumeration",
            }
        )
        for position, auth in enumerate(auth_list, start=1):
            usc = auth.get("USC") or auth.get("usc") or {}
            public_law = auth.get("publicLaw") or {}
            statute = auth.get("statute") or {}
            act = auth.get("act") or {}
            authorities.append(
                {
                    "source_key": SOURCE_KEY,
                    "program_source_record_id": listing_id,
                    "authority_sequence": position,
                    "authority_citation": _authorization_citation(auth),
                    "usc_title": str(usc.get("title") or "").strip(),
                    "usc_section": str(usc.get("section") or "").strip(),
                    "usc_description": str(usc.get("description") or "").strip(),
                    "public_law_congress": str(public_law.get("congressCode") or "").strip(),
                    "public_law_number": str(public_law.get("number") or "").strip(),
                    "public_law_description": str(public_law.get("description") or "").strip(),
                    "statutes_at_large_volume": str(statute.get("volume") or "").strip(),
                    "statutes_at_large_page": str(statute.get("page") or "").strip(),
                    "act_title": str(act.get("title") or "").strip(),
                    "act_part": str(act.get("part") or "").strip(),
                    "act_section": str(act.get("section") or "").strip(),
                    "act_description": str(act.get("description") or "").strip(),
                    "authority_raw": _json(auth),
                }
            )
        for function in function_list:
            functions.append(
                {
                    "source_key": "sam_functional_index",
                    "program_source_record_id": listing_id,
                    "function_code": str(function.get("code") or "").strip(),
                    "function_name": str(function.get("name") or "").strip(),
                }
            )
    return programs, authorities, functions


def _norm_col(value: str) -> str:
    # SAM's public Assistance Listings CSV appends CFDA field numbers to many
    # headings (for example, "Federal Agency (030)" and "Authorization (040)").
    # The numbers are metadata, not part of the semantic column name.
    value = re.sub(r"\s*\(\d+\)\s*$", "", str(value).lower())
    return re.sub(r"[^a-z0-9]+", "", value)


def _title_case_org(value: str) -> str:
    value = " ".join((value or "").split()).strip()
    if re.fullmatch(r"[A-Z]{2,8}", value):
        return value
    return value.title() if value else ""


def _sam_org_match_name(value: str) -> str:
    """Clean a SAM hierarchy component for matching; retain the source in raw."""
    value = re.sub(r"\s*\([A-Za-z0-9]{2,8}\)\s*$", "", value).strip()
    department = re.fullmatch(
        r"(?:DEPT\.?|DEPARTMENT)\s+OF\s+(THE\s+)?(.+)", value, flags=re.IGNORECASE
    )
    if department:
        article = "the " if department.group(1) else ""
        return f"Department of {article}{_title_case_org(department.group(2))}"
    return _title_case_org(value)


def _parse_sam_federal_agency(value: str) -> tuple[str, str, str]:
    """Parse SAM's bulk Federal Agency (030) hierarchy."""
    value = re.sub(r"\s+", " ", value or "").strip(" ,")
    if not value:
        return "", "", ""

    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) >= 3 and parts[-1].upper() in {"DEPARTMENT OF", "DEPARTMENT OF THE"}:
        article = "the " if parts[-1].upper() == "DEPARTMENT OF THE" else ""
        department = f"Department of {article}{_sam_org_match_name(parts[-2])}"
        agency = _sam_org_match_name(", ".join(parts[:-2]))
        return department, agency, ""

    # Independent agencies are sometimes repeated as their own parent.
    if len(parts) == 2 and parts[0].casefold() == parts[1].casefold():
        return "", _sam_org_match_name(parts[0]), ""

    # Other rows use a conventional parent label, e.g. CHILD, DEPT OF DEFENSE.
    if len(parts) >= 2 and re.fullmatch(
        r"(?:DEPT\.?|DEPARTMENT)\s+OF\s+(?:THE\s+)?[^,]+", parts[-1], flags=re.IGNORECASE
    ):
        department = _sam_org_match_name(parts[-1])
        agency = _sam_org_match_name(", ".join(parts[:-1]))
        return department, agency, ""

    return "", _sam_org_match_name(value), ""


def _parse_authority_text(source_key: str, listing_id: str, text: str) -> list[dict]:
    import re
    rows: list[dict] = []
    text = str(text or "").strip()
    if not text:
        return rows
    citations = list(re.finditer(r"(?P<title>\d+)\s*U\.?S\.?C\.?\s*(?:§{1,2}\s*)?(?P<section>[0-9A-Za-z._-]+)", text, flags=re.IGNORECASE))
    if not citations:
        return [{
            "source_key": source_key,
            "program_source_record_id": listing_id,
            "authority_sequence": 1,
            "authority_citation": text,
            "usc_title": "",
            "usc_section": "",
            "usc_description": "",
            "public_law_congress": "",
            "public_law_number": "",
            "public_law_description": "",
            "statutes_at_large_volume": "",
            "statutes_at_large_page": "",
            "act_title": "",
            "act_part": "",
            "act_section": "",
            "act_description": "",
            "authority_raw": text,
        }]
    for sequence, match in enumerate(citations, start=1):
        rows.append({
            "source_key": source_key,
            "program_source_record_id": listing_id,
            "authority_sequence": sequence,
            "authority_citation": match.group(0),
            "usc_title": match.group("title"),
            "usc_section": match.group("section"),
            "usc_description": "",
            "public_law_congress": "",
            "public_law_number": "",
            "public_law_description": "",
            "statutes_at_large_volume": "",
            "statutes_at_large_page": "",
            "act_title": "",
            "act_part": "",
            "act_section": "",
            "act_description": "",
            "authority_raw": text,
        })
    return rows


def records_from_csv(text: str, source_url: str) -> tuple[list[dict], list[dict], list[dict]]:
    import csv
    import io
    import re

    reader = csv.DictReader(io.StringIO(text))
    fields = {_norm_col(field): field for field in (reader.fieldnames or [])}

    def field(*aliases: str) -> str:
        for alias in aliases:
            key = _norm_col(alias)
            if key in fields:
                return fields[key]
        return ""

    id_col = field("Federal Assistance ID", "Assistance Listing ID", "Program Number", "CFDA Number", "Assistance Listing Number")
    name_col = field("Program Title", "Title", "Program Name")
    objective_col = field("Objectives", "Objective", "Program Objective")
    desc_col = field("Program Description", "Assistance Listing Description", "Description")
    auth_col = field("Authorizations", "Authorization", "Authorizing Legislation")
    dept_col = field("Department", "Department Name")
    agency_col = field("Agency", "Agency Name", "Federal Agency")
    federal_agency_col = field("Federal Agency")
    office_col = field("Office", "Office Name", "Sub-Tier", "Subtier")
    org_col = field("Federal Organization", "Federal Agency / Organization", "Organization")
    status_col = field("Status", "Program Status")
    popular_col = field("Popular Name", "Popular Long Name")
    short_col = field("Popular Short Name")
    parent_shortname_col = field("Parent Shortname", "Parent Short Name")
    related_col = field("Related Programs")
    published_col = field("Published Date")
    website_col = field("Website Address")
    url_col = field("URL")
    functional_col = field("Functional Index", "Functional Codes", "Functional Code", "Function")
    if not id_col or not name_col:
        raise RuntimeError(
            "SAM Assistance Listings bulk CSV is missing expected ID/title columns. "
            f"Available columns: {reader.fieldnames}"
        )

    programs: list[dict] = []
    authorities: list[dict] = []
    functions: list[dict] = []
    for row in reader:
        listing_id = str(row.get(id_col) or "").strip()
        name = str(row.get(name_col) or "").strip()
        if not listing_id or not name:
            continue
        department = str(row.get(dept_col) or "").strip() if dept_col else ""
        agency = str(row.get(agency_col) or "").strip() if agency_col else ""
        federal_agency_raw = str(row.get(federal_agency_col) or "") if federal_agency_col else ""
        office = str(row.get(office_col) or "").strip() if office_col else ""

        # Current SAM bulk rows encode hierarchy in Federal Agency (030), e.g.
        # AGRICULTURAL RESEARCH SERVICE, AGRICULTURE, DEPARTMENT OF.
        if agency_col and not department and agency:
            department, parsed_agency, parsed_office = _parse_sam_federal_agency(agency)
            agency = parsed_agency
            office = office or parsed_office

        if org_col and not (department or agency or office):
            department, agency, office = _parse_sam_federal_agency(str(row.get(org_col) or ""))

        authority_text = str(row.get(auth_col) or "").strip() if auth_col else ""
        functional_text = str(row.get(functional_col) or "").strip() if functional_col else ""
        programs.append({
            "source": SOURCE,
            "source_key": SOURCE_KEY,
            "source_record_id": listing_id,
            "source_name": name,
            "source_description": str(row.get(desc_col) or "").strip() if desc_col else "",
            "agency_stated_purpose": str(row.get(objective_col) or "").strip() if objective_col else "",
            "source_status": str(row.get(status_col) or "").strip() if status_col else "",
            "source_date": str(row.get(published_col) or "").strip() if published_col else "",
            "source_url": (
                str(row.get(url_col) or "").strip()
                if url_col and str(row.get(url_col) or "").strip()
                else (
                    str(row.get(website_col) or "").strip()
                    if website_col and str(row.get(website_col) or "").strip()
                    else source_url
                )
            ),
            "program_type_raw": "assistance",
            "federal_agency_raw": federal_agency_raw,
            "department_source_name": department,
            "department_source_code": "",
            "agency_source_name": agency,
            "agency_source_code": "",
            "office_source_name": office,
            "office_source_code": "",
            "popular_long_name": str(row.get(popular_col) or "").strip() if popular_col else "",
            "popular_short_name": str(row.get(short_col) or "").strip() if short_col else "",
            "parent_shortname": str(row.get(parent_shortname_col) or "").strip() if parent_shortname_col else "",
            "related_programs_raw": str(row.get(related_col) or "").strip() if related_col else "",
            "authorization_raw": authority_text,
            "function_raw": functional_text,
            "mission_category_raw": "",
            "admission_basis": "official_program_enumeration",
        })
        authorities.extend(_parse_authority_text(SOURCE_KEY, listing_id, authority_text))
        if functional_text:
            for token in re.split(r"\s*[|;]\s*", functional_text):
                token = token.strip()
                if token:
                    functions.append({
                        "source_key": "sam_functional_index",
                        "program_source_record_id": listing_id,
                        "function_code": "",
                        "function_name": token,
                    })
    return programs, authorities, functions


def extract(
    endpoint: str,
    raw_dir: Path,
    *,
    bulk_url: str = "",
    api_key_env: str = "SAM_API_KEY",
    status: str = "ALL",
    page_size: int = 100,
    timeout: int = 120,
    max_pages: int | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    out_dir = raw_dir / "sam_assistance"
    ensure_dir(out_dir)
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    # Prefer SAM's public current bulk extract. It avoids public API rate limits and is
    # the practical whole-government path. The API remains a fallback and smoke-test path.
    if bulk_url and max_pages is None:
        try:
            response = session.get(bulk_url, timeout=timeout)
            response.raise_for_status()
            (out_dir / "AssistanceListings_DataGov_PUBLIC_CURRENT.csv").write_bytes(response.content)
            try:
                bulk_text = response.content.decode("utf-8-sig")
            except UnicodeDecodeError:
                # Some current SAM records contain Windows-1252 punctuation.
                bulk_text = response.content.decode("cp1252")
            programs, authorities, functions = records_from_csv(bulk_text, response.url)
            if programs:
                return programs, authorities, functions
        except (requests.RequestException, RuntimeError):
            pass

    api_key = os.environ.get(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(
            "SAM bulk extraction failed and API fallback needs a key. "
            f"Set {api_key_env}, or verify the configured SAM bulk_url."
        )

    all_programs: list[dict] = []
    all_authorities: list[dict] = []
    all_functions: list[dict] = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        response = session.get(
            endpoint,
            params={
                "api_key": api_key,
                "status": status,
                "pageSize": page_size,
                "pageNumber": page,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        (out_dir / f"page_{page:04d}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        programs, authorities, functions = records_from_payload(payload, response.url)
        all_programs.extend(programs)
        all_authorities.extend(authorities)
        all_functions.extend(functions)
        total_pages = int(payload.get("totalPages") or 1)
        if max_pages is not None:
            total_pages = min(total_pages, max_pages)
        page += 1

    if not all_programs:
        raise RuntimeError("SAM Assistance Listings extraction produced zero program records.")
    return all_programs, all_authorities, all_functions
