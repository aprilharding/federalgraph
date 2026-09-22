from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from federalgraph.common import ensure_dir

UA = "FederalGraph/0.6.1 (+public-interest research)"
SOURCE_NAME = "U.S. Government Manual / GovInfo"

# Manual granules that are structural/grouping labels rather than distinct
# organizational identities. Keep them in the GovInfo audit file but do not feed
# them into the canonical organization resolver.
GROUPING_HEADINGS = {
    "bureaus",
    "offices / boards",
    "offices and boards",
    "defense agencies",
    "joint service schools",
    "federally aided corporations",
}


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _stripped_strings(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [s.strip() for s in soup.stripped_strings if s.strip()]


def _value_after_label(html: str, label: str) -> str:
    values = _stripped_strings(html)
    label_low = label.lower()
    for i, value in enumerate(values):
        if value.lower() == label_low:
            for candidate in values[i + 1 : i + 8]:
                if candidate and candidate.lower() != label_low:
                    return candidate
    return ""


def discover_granule_ids(context_html: str, package_id: str) -> list[str]:
    """Best-effort discovery from a rendered/context HTML page.

    Kept as a fallback only. GovInfo's package-level /context page can be
    client-rendered and may contain no granule hrefs in the HTML returned to
    requests, so live extraction now prefers the GovInfo API granules endpoint.
    """

    soup = BeautifulSoup(context_html, "html.parser")
    ids: set[str] = set()
    pattern = re.compile(rf"/app/details/{re.escape(package_id)}/({re.escape(package_id)}-[^/?#]+)")
    for link in soup.find_all("a", href=True):
        match = pattern.search(link.get("href", ""))
        if match:
            ids.add(match.group(1))
    if not ids:
        for match in re.finditer(rf"{re.escape(package_id)}-[A-Za-z0-9_-]+", context_html):
            ids.add(match.group(0))
    return sorted(ids)


def discover_granule_ids_from_xml(package_xml: bytes, package_id: str) -> list[str]:
    """Fallback: recover GovInfo granule IDs mentioned inside package XML.

    This deliberately does not try to understand the publication schema; it only
    recovers exact GovInfo identifiers. The API remains the preferred source for
    the granule list.
    """

    text = package_xml.decode("utf-8", errors="ignore")
    pattern = re.compile(rf"\b({re.escape(package_id)}-[A-Za-z0-9][A-Za-z0-9_-]*)\b")
    return sorted({m.group(1) for m in pattern.finditer(text)})


def granule_ids_from_api_payload(payload: object) -> list[str]:
    """Extract granule IDs from the shapes used by the GovInfo packages API."""

    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = (
            payload.get("granules")
            or payload.get("results")
            or payload.get("data")
            or payload.get("items")
            or []
        )
        if isinstance(items, dict):
            items = items.get("results") or items.get("granules") or items.get("items") or []
    else:
        items = []

    ids: list[str] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        granule_id = (
            item.get("granuleId")
            or item.get("granule_id")
            or item.get("granuleID")
            or item.get("id")
            or ""
        )
        if granule_id:
            ids.append(str(granule_id))
    return ids


def discover_granule_ids_from_api(
    session: requests.Session,
    package_id: str,
    api_base_url: str,
    api_key: str,
    timeout: int,
    page_size: int = 100,
) -> list[str]:
    """List every granule in a GovInfo package through the official API."""

    base = api_base_url.rstrip("/")
    endpoint = f"{base}/packages/{package_id}/granules"
    offset = 0
    ids: list[str] = []
    seen: set[str] = set()

    while True:
        response = session.get(
            endpoint,
            params={
                "offset": offset,
                "pageSize": page_size,
                "api_key": api_key,
            },
            timeout=timeout,
        )
        if response.status_code in {401, 403, 429}:
            raise RuntimeError(
                "GovInfo granules API rejected the API key or rate limit. "
                "Set GOVINFO_API_KEY to an api.data.gov key and rerun."
            )
        response.raise_for_status()
        payload = response.json()
        page_ids = granule_ids_from_api_payload(payload)

        for granule_id in page_ids:
            if granule_id not in seen:
                seen.add(granule_id)
                ids.append(granule_id)

        if not page_ids:
            break

        total = 0
        if isinstance(payload, dict):
            for key in ("count", "totalCount", "total", "numberOfRecords"):
                value = payload.get(key)
                try:
                    total = int(value)
                    break
                except (TypeError, ValueError):
                    pass

        offset += len(page_ids)
        if total and offset >= total:
            break
        if len(page_ids) < page_size and not total:
            break

        # Defensive stop if an API bug returns the same page repeatedly.
        if offset > 10000:
            raise RuntimeError(f"GovInfo granule pagination exceeded 10,000 rows for {package_id}.")

    return ids


def parse_detail_html(html: str, package_id: str, granule_id: str, publication_date: str) -> dict:
    name = _value_after_label(html, "Government Organization")
    section = _value_after_label(html, "Section")
    parsed_date = _value_after_label(html, "Publication Date") or publication_date
    branch = section.split("/", 1)[0].strip() if section else ""
    section_category = section.split("/", 1)[1].strip() if "/" in section else ""
    normalized = re.sub(r"\s+", " ", name).strip().lower()
    record_kind = "grouping_heading" if normalized in GROUPING_HEADINGS else "organization"
    is_entity_candidate = record_kind == "organization" and bool(name)
    detail_url = f"https://www.govinfo.gov/app/details/{package_id}/{granule_id}"
    xml_url = f"https://www.govinfo.gov/content/pkg/{package_id}/xml/{granule_id}.xml"
    return {
        "package_id": package_id,
        "granule_id": granule_id,
        "publication_date": parsed_date,
        "government_organization": name,
        "section": section,
        "branch": branch,
        "section_category": section_category,
        "record_kind": record_kind,
        "is_entity_candidate": is_entity_candidate,
        "details_url": detail_url,
        "xml_url": xml_url,
    }


def _fetch_detail(package_id: str, granule_id: str, timeout: int) -> tuple[str, str]:
    # Use one request per worker rather than sharing one Session across threads.
    url = f"https://www.govinfo.gov/app/details/{package_id}/{granule_id}"
    response = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    response.raise_for_status()
    response.encoding = "utf-8"
    return granule_id, response.text


def extract(
    package_id: str,
    xml_url: str,
    publication_date: str,
    raw_dir: Path,
    timeout: int = 120,
    workers: int = 12,
    api_base_url: str = "https://api.govinfo.gov",
    api_key_env: str = "GOVINFO_API_KEY",
    api_key_fallback: str = "DEMO_KEY",
    page_size: int = 100,
) -> list[dict]:
    """Extract current-edition Government Manual organization records.

    The package XML is preserved and hashed as the edition-level artifact. Granule
    discovery uses GovInfo's official packages API, because the package-level
    ``/context`` web page is client-rendered and does not reliably expose granule
    links to a plain HTTP client. The extractor falls back to identifiers found in
    the package XML, then finally to legacy context-page discovery.
    """

    ensure_dir(raw_dir)
    gov_dir = raw_dir / "govinfo" / package_id
    ensure_dir(gov_dir)

    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    xml_response = session.get(xml_url, timeout=timeout)
    xml_response.raise_for_status()
    package_xml = xml_response.content
    package_xml_path = gov_dir / f"{package_id}.xml"
    package_xml_path.write_bytes(package_xml)
    package_sha256 = _sha256(package_xml)

    discovery_method = "govinfo_api"
    api_key = os.environ.get(api_key_env, "").strip() or api_key_fallback
    api_error = ""
    try:
        granule_ids = discover_granule_ids_from_api(
            session,
            package_id,
            api_base_url,
            api_key,
            timeout,
            page_size=page_size,
        )
    except Exception as exc:  # network/API fallback path
        api_error = str(exc)
        granule_ids = []

    if not granule_ids:
        discovery_method = "package_xml_regex"
        granule_ids = discover_granule_ids_from_xml(package_xml, package_id)

    context_url = f"https://www.govinfo.gov/app/details/{package_id}/context"
    context_html = ""
    if not granule_ids:
        discovery_method = "context_html_fallback"
        context_response = session.get(context_url, timeout=timeout)
        context_response.raise_for_status()
        context_response.encoding = "utf-8"
        context_html = context_response.text
        (gov_dir / "context.html").write_text(context_html, encoding="utf-8")
        granule_ids = discover_granule_ids(context_html, package_id)

    (gov_dir / "granule_discovery.json").write_text(
        json.dumps(
            {
                "package_id": package_id,
                "method": discovery_method,
                "granule_count": len(granule_ids),
                "api_key_source": api_key_env if os.environ.get(api_key_env) else "DEMO_KEY",
                "api_error": api_error,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if not granule_ids:
        raise RuntimeError(
            f"GovInfo extractor found no granules for {package_id}. "
            f"See {gov_dir / 'granule_discovery.json'} for discovery diagnostics."
        )

    details: dict[str, str] = {}
    failures: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(_fetch_detail, package_id, granule_id, timeout): granule_id
            for granule_id in granule_ids
        }
        for future in as_completed(future_map):
            granule_id = future_map[future]
            try:
                key, html = future.result()
                details[key] = html
                (gov_dir / f"{key}.html").write_text(html, encoding="utf-8")
            except Exception as exc:  # pragma: no cover - network behavior
                failures.append({"granule_id": granule_id, "reason": str(exc)})

    audit_rows: list[dict] = []
    records: list[dict] = []
    for granule_id in granule_ids:
        html = details.get(granule_id, "")
        if not html:
            continue
        parsed = parse_detail_html(html, package_id, granule_id, publication_date)
        parsed["package_xml_sha256"] = package_sha256
        audit_rows.append(parsed)
        if not parsed["is_entity_candidate"]:
            continue
        name = parsed["government_organization"]
        records.append(
            {
                "source": SOURCE_NAME,
                "source_record_id": granule_id,
                "source_name": name,
                "source_url": parsed["details_url"],
                "website": "",
                "description": "",
                "parent_source_name": "",
                "source_level": "organization",
                "branch": parsed["branch"],
                "source_as_of": publication_date,
                "publication_date": publication_date,
                "govinfo_package_id": package_id,
                "govinfo_granule_id": granule_id,
                "govinfo_section": parsed["section"],
                "govinfo_section_category": parsed["section_category"],
                "govinfo_xml_url": parsed["xml_url"],
                "govinfo_package_xml_sha256": package_sha256,
            }
        )

    with (gov_dir / "granules.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(audit_rows[0].keys()) if audit_rows else []
        if fieldnames:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(audit_rows)

    if failures:
        (gov_dir / "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")

    if not records:
        raise RuntimeError(
            f"GovInfo extraction produced zero organization records for {package_id}. "
            f"Discovered {len(granule_ids)} granules; detail failures: {len(failures)}."
        )
    return records
