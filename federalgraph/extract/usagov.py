from __future__ import annotations
import re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from federalgraph.common import ensure_dir

UA = "FederalGraph/0.1 (+public-interest research)"

def page_urls(base_url: str, letters: str):
    yield base_url
    for letter in letters:
        yield f"{base_url}/{letter}"

def _agency_blocks(soup: BeautifulSoup):
    # USA.gov has changed markup over time. Prefer headings in main content, then lists/cards.
    main = soup.find("main") or soup
    for heading in main.find_all(["h2", "h3", "h4"]):
        text = heading.get_text(" ", strip=True)
        if not text or len(text) > 180:
            continue
        link = heading.find("a", href=True)
        container = heading.parent
        desc = ""
        website = ""
        source_detail_url = ""
        if link:
            source_detail_url = urljoin("https://www.usa.gov", link.get("href"))
        # Collect nearby text/links until next heading, but keep compact.
        sib = heading.find_next_sibling()
        parts = []
        for _ in range(5):
            if not sib or getattr(sib, "name", None) in {"h2", "h3", "h4"}:
                break
            t = sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else ""
            if t:
                parts.append(t)
            for a in sib.find_all("a", href=True) if hasattr(sib, "find_all") else []:
                href = a.get("href", "")
                if href.startswith("http") and "usa.gov" not in href:
                    website = href
                    break
            sib = sib.find_next_sibling() if hasattr(sib, "find_next_sibling") else None
        desc = " ".join(parts)[:2000]
        if source_detail_url or desc:
            yield text, desc, website, source_detail_url

def extract(base_url: str, letters: str, raw_dir: Path, timeout: int = 45) -> list[dict]:
    ensure_dir(raw_dir)
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    records, seen = [], set()
    failures = []
    for url in page_urls(base_url, letters):
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            (raw_dir / ("usagov_" + (url.rstrip("/").split("/")[-1] or "a") + ".html")).write_text(r.text, encoding="utf-8")
            soup = BeautifulSoup(r.text, "html.parser")
            count_before = len(records)
            for name, desc, website, detail_url in _agency_blocks(soup):
                key = re.sub(r"\W+", "", name.lower())
                if key in seen:
                    continue
                seen.add(key)
                records.append({
                    "source": "USA.gov Agency Index",
                    "source_record_id": detail_url or url + "#" + key,
                    "source_name": name,
                    "source_url": detail_url or url,
                    "website": website,
                    "description": desc,
                    "parent_source_name": "",
                    "source_level": "organization",
                    "branch": "",
                })
            if len(records) == count_before:
                failures.append({"url": url, "reason": "no records parsed"})
        except Exception as exc:
            failures.append({"url": url, "reason": str(exc)})
    if failures:
        import json
        (raw_dir / "usagov_failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
    if not records:
        raise RuntimeError("USA.gov extraction produced zero records. See data/raw/usagov_failures.json.")
    return records
