from __future__ import annotations

import re
import zipfile
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

from federalgraph.common import ensure_dir

UA = "FederalGraph/0.8 (+public-interest research)"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean_num(value: str) -> str:
    value = re.sub(r"\s+", "", value or "")
    value = value.replace("§", "")
    value = re.sub(r"^(Sec\.?|Section)", "", value, flags=re.IGNORECASE)
    return value.strip(". ")


def section_records_from_xml(path: Path, wanted_sections: set[str]) -> dict[str, dict]:
    wanted = {_clean_num(section) for section in wanted_sections if section}
    found: dict[str, dict] = {}
    if not wanted:
        return found
    for _, elem in ET.iterparse(path, events=("end",)):
        if _local(elem.tag) != "section":
            continue
        num = ""
        heading = ""
        for child in elem.iter():
            local = _local(child.tag)
            if local == "num" and not num:
                num = _clean_num("".join(child.itertext()))
            elif local == "heading" and not heading:
                heading = re.sub(r"\s+", " ", " ".join(child.itertext())).strip()
        if num in wanted:
            text = re.sub(r"\s+", " ", " ".join(elem.itertext())).strip()
            found[num] = {"section": num, "heading": heading, "text": text}
        elem.clear()
    return found


def extract_purpose_candidate(section_text: str) -> tuple[str, str]:
    text = re.sub(r"\s+", " ", section_text or "").strip()
    if not text:
        return "", "not_found"
    sentences = re.split(r"(?<=[.;])\s+(?=[A-Z(])", text)
    signals = re.compile(
        r"\b(purpose|purposes|establish(?:ed|es)?|shall (?:carry out|administer|establish)|"
        r"objective|objectives|goal|goals|program is to|program shall)\b",
        flags=re.IGNORECASE,
    )
    selected = [sentence.strip() for sentence in sentences if signals.search(sentence)]
    if selected:
        return " ".join(selected[:4])[:2500], "statutory_signal_text"
    return "", "section_found_no_purpose_signal"


def _discover_title_xml_url(download_page: str, title: str, timeout: int) -> str:
    response = requests.get(download_page, headers={"User-Agent": UA}, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title_pattern = re.compile(rf"\bTitle\s+0*{re.escape(str(title))}\b", re.IGNORECASE)
    for container in soup.find_all(["tr", "div", "li", "p"]):
        if not title_pattern.search(container.get_text(" ", strip=True)):
            continue
        for anchor in container.find_all("a", href=True):
            href = anchor["href"]
            text = anchor.get_text(" ", strip=True).lower()
            if text == "xml" or "xml" in href.lower():
                return urljoin(response.url, href)
    # Fallback: scan all links for the title number and XML marker.
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        low = href.lower()
        if "xml" in low and re.search(rf"usc0*{re.escape(str(title))}(?:\D|$)", low):
            return urljoin(response.url, href)
    return ""


def _download_title_xml(download_page: str, title: str, raw_dir: Path, timeout: int) -> Path | None:
    out_dir = raw_dir / "uscode" / "xml"
    ensure_dir(out_dir)
    existing = sorted(out_dir.glob(f"*usc{int(title):02d}*.xml")) + sorted(out_dir.glob(f"*usc{title}*.xml"))
    if existing:
        return existing[0]
    url = _discover_title_xml_url(download_page, title, timeout)
    if not url:
        return None
    response = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    response.raise_for_status()
    filename = url.rsplit("/", 1)[-1].split("?", 1)[0] or f"usc{int(title):02d}.xml"
    path = out_dir / filename
    path.write_bytes(response.content)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
            if not xml_names:
                return None
            archive.extract(xml_names[0], out_dir)
            return out_dir / xml_names[0]
    return path


def enrich_authorities(
    authority_rows: list[dict],
    raw_dir: Path,
    *,
    download_page: str,
    timeout: int = 120,
) -> list[dict]:
    by_title: dict[str, set[str]] = {}
    for row in authority_rows:
        title = str(row.get("usc_title") or "").strip()
        section = str(row.get("usc_section") or "").strip()
        if title and section:
            by_title.setdefault(title, set()).add(section)

    lookups: dict[tuple[str, str], dict] = {}
    for title, sections in sorted(by_title.items(), key=lambda pair: int(pair[0]) if pair[0].isdigit() else 999):
        try:
            xml_path = _download_title_xml(download_page, title, raw_dir, timeout)
        except requests.RequestException:
            xml_path = None
        if xml_path is None:
            continue
        for section, record in section_records_from_xml(xml_path, sections).items():
            lookups[(title, section)] = record

    enriched: list[dict] = []
    for row in authority_rows:
        copy = dict(row)
        title = str(row.get("usc_title") or "").strip()
        section = _clean_num(str(row.get("usc_section") or ""))
        matched = lookups.get((title, section))
        if matched:
            purpose, method = extract_purpose_candidate(matched["text"])
            copy.update(
                {
                    "statutory_section_heading": matched["heading"],
                    "statutory_section_text": matched["text"],
                    "statutory_purpose_text": purpose,
                    "statutory_purpose_method": method,
                    "statutory_lookup_status": "matched",
                }
            )
        else:
            copy.update(
                {
                    "statutory_section_heading": "",
                    "statutory_section_text": "",
                    "statutory_purpose_text": "",
                    "statutory_purpose_method": "",
                    "statutory_lookup_status": "not_matched" if title and section else "no_exact_usc_citation",
                }
            )
        enriched.append(copy)
    return enriched
