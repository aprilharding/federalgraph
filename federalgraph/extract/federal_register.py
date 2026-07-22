from __future__ import annotations
from pathlib import Path
import requests, json
from federalgraph.common import ensure_dir

UA = "FederalGraph/0.1 (+public-interest research)"

def _walk(items, parent=""):
    for item in items or []:
        name = item.get("name") or item.get("raw_name") or ""
        yield {
            "source": "Federal Register Agencies API",
            "source_record_id": str(item.get("id") or item.get("slug") or name),
            "source_name": name,
            "source_url": item.get("url") or ("https://www.federalregister.gov/agencies/" + str(item.get("slug", ""))),
            "website": item.get("homepage_url") or "",
            "description": item.get("description") or "",
            "parent_source_name": parent,
            "source_level": "subagency" if parent else "agency",
            "branch": "",
            "fr_slug": item.get("slug") or "",
            "recent_articles_url": item.get("recent_articles_url") or "",
        }
        children = item.get("children") or item.get("child_agencies") or []
        yield from _walk(children, name)

def extract(endpoint: str, raw_dir: Path, timeout: int = 45) -> list[dict]:
    ensure_dir(raw_dir)
    r = requests.get(endpoint, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    raw = r.json()
    (raw_dir / "federal_register_agencies.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    items = raw.get("results", raw) if isinstance(raw, dict) else raw
    records = list(_walk(items))
    if not records:
        raise RuntimeError("Federal Register extraction produced zero records.")
    return records
