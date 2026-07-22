from __future__ import annotations
import hashlib, json, re
from pathlib import Path
from urllib.parse import urlparse

MEANINGFUL_WORDS = {
    "administration", "agency", "board", "bureau", "center", "centers", "commission",
    "committee", "corporation", "council", "department", "division", "office", "service",
    "authority", "institute", "foundation", "program", "administrative"
}
STOPWORDS = {"the", "of", "for", "and", "on", "in", "to", "united", "states", "u", "s"}

def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path

def normalize_name(value: str) -> str:
    value = (value or "").lower().replace("&", " and ")
    value = re.sub(r"\bu\.?\s*s\.?\b", "united states", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def matching_tokens(value: str) -> list[str]:
    return [t for t in normalize_name(value).split() if t not in STOPWORDS]

def acronym(value: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", value or "") if w.lower() not in STOPWORDS]
    return "".join(w[0].upper() for w in words if w)

def domain(value: str) -> str:
    if not value:
        return ""
    url = value if "://" in value else "https://" + value
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")

def stable_id(name: str, prefix: str = "ORG") -> str:
    norm = normalize_name(name)
    stem = re.sub(r"[^A-Z0-9]+", "_", norm.upper()).strip("_")[:60] or "UNKNOWN"
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:8].upper()
    return f"{prefix}-{stem}-{digest}"

def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path: Path, value) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
