from __future__ import annotations

import csv
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from federalgraph.common import ensure_dir

UA = "FederalGraph/0.6 (+public-interest research)"
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
    soup = BeautifulSoup(context_html, "html.parser")
    ids: set[str] = set()
    pattern = re.compile(rf"/app/details/{re.escape(package_id)}/({re.escape(package_id)}-[^/?#]+)")
    for link in soup.find_all("a", href=True):
        match = pattern.search(link.get("href", ""))
        if match:
            ids.add(match.group(1))
    # Fallback for client-rendered markup or changed anchor structure.
    if not ids:
        for match in re.finditer(rf"{re.escape(package_id)}-[A-Za-z0-9_-]+", context_html):
            ids.add(match.group(0))
    return sorted(ids)


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


def _fetch_detail(session: requests.Session, package_id: str, granule_id: str, timeout: int) -> tuple[str, str]:
    url = f"https://www.govinfo.gov/app/details/{package_id}/{granule_id}"
    response = session.get(url, timeout=timeout)
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
) -> list[dict]:
    """Extract current-edition Government Manual organization records.

    The full package XML is downloaded and hashed as the edition-level source artifact.
    Granule identifiers and field-level metadata are obtained from GovInfo's official
    package/detail pages because those pages expose ``Government Organization`` and
    ``Section`` explicitly and consistently. Every emitted record retains the direct
    granule XML URL so the organization assertion remains XML-addressable.
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

    context_url = f"https://www.govinfo.gov/app/details/{package_id}/context"
    context_response = session.get(context_url, timeout=timeout)
    context_response.raise_for_status()
    context_response.encoding = "utf-8"
    context_html = context_response.text
    (gov_dir / "context.html").write_text(context_html, encoding="utf-8")

    granule_ids = discover_granule_ids(context_html, package_id)
    if not granule_ids:
        raise RuntimeError(f"GovInfo extractor found no granules for {package_id}.")

    details: dict[str, str] = {}
    failures: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(_fetch_detail, session, package_id, granule_id, timeout): granule_id
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
        import json

        (gov_dir / "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")

    if not records:
        raise RuntimeError(f"GovInfo extraction produced zero organization records for {package_id}.")
    return records
