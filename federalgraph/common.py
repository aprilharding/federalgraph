from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

MEANINGFUL_WORDS = {
    "administration",
    "agency",
    "board",
    "bureau",
    "center",
    "centers",
    "commission",
    "committee",
    "corporation",
    "council",
    "department",
    "division",
    "office",
    "service",
    "authority",
    "institute",
    "foundation",
    "program",
    "administrative",
}
STOPWORDS = {"the", "of", "for", "and", "on", "in", "to", "united", "states", "u", "s"}

# Patterns used only to create deterministic alias keys. They do not rewrite the
# displayed organization name.
_INVERTIBLE_SUFFIXES = {
    "administration for",
    "agency for",
    "authority for",
    "authority of",
    "board of",
    "bureau of",
    "center for",
    "center of",
    "commission of",
    "commission on",
    "committee on",
    "council of",
    "council on",
    "department of",
    "office of",
    "service of",
}
_ORG_DESIGNATORS = {
    "administration",
    "agency",
    "authority",
    "board",
    "bureau",
    "center",
    "commission",
    "committee",
    "corporation",
    "council",
    "department",
    "division",
    "foundation",
    "institute",
    "office",
    "service",
}


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


def explicit_parenthetical_acronym(value: str) -> str:
    """Return a trailing source-provided acronym such as ``(USDA)``.

    This is deliberately stricter than :func:`acronym`: generated initials are
    useful as corroborating evidence, but only an acronym explicitly present in
    a source is emitted as an alias.
    """

    match = re.search(r"\s*\(([^()]*)\)\s*$", value or "")
    if not match:
        return ""
    candidate = re.sub(r"[^A-Za-z0-9]", "", match.group(1))
    if 2 <= len(candidate) <= 12 and candidate.upper() == candidate:
        return candidate
    return ""


def strip_parenthetical_acronym(value: str) -> str:
    if not explicit_parenthetical_acronym(value):
        return (value or "").strip()
    return re.sub(r"\s*\([^()]*\)\s*$", "", value or "").strip()


def _inverted_index_alias(value: str) -> str:
    """Undo common directory alphabetization forms.

    Examples::

        Economic Analysis, Bureau of -> Bureau of Economic Analysis
        Global Media, Agency for -> Agency for Global Media

    A second conservative rule handles rows like ``Archives, National Archives
    and Records Administration`` where the right-hand side is already the full
    organization name.
    """

    if "," not in (value or ""):
        return ""
    left, right = [part.strip() for part in value.split(",", 1)]
    if not left or not right:
        return ""

    right_norm = normalize_name(right)
    left_norm = normalize_name(left)

    if right_norm in _INVERTIBLE_SUFFIXES:
        return f"{right} {left}".strip()

    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    if left_tokens and left_tokens.issubset(right_tokens) and right_tokens & _ORG_DESIGNATORS:
        return right

    return ""


def organization_identity_keys(value: str) -> list[str]:
    """Generate conservative, deterministic identity-equivalence keys.

    The keys exist only for entity resolution. They preserve the original source
    names as aliases and never become public labels by themselves.

    Rules intentionally cover syntactic variants rather than broad semantics:
    trailing parenthetical acronyms, ``U.S.``/``United States`` prefixes,
    directory inversion, ``X Department``/``Department of X``, and optional
    ``the`` articles.
    """

    original = (value or "").strip()
    if not original:
        return []

    base = strip_parenthetical_acronym(original)
    raw_variants = {original, base}

    inverted = _inverted_index_alias(base)
    if inverted:
        raw_variants.add(inverted)

    normalized = {normalize_name(v) for v in raw_variants if normalize_name(v)}

    # Department directories frequently alternate between "Treasury Department"
    # and "Department of the Treasury". Generate the mechanically reversible form.
    for item in list(normalized):
        if item.endswith(" department") and not item.startswith("department "):
            subject = item[: -len(" department")].strip()
            if subject:
                normalized.add(f"department of {subject}")

    # "U.S." is jurisdictional decoration for these federal-directory records.
    for item in list(normalized):
        if item.startswith("united states "):
            normalized.add(item[len("united states ") :])

    # The presence of the article "the" is inconsistent across official sources.
    for item in list(normalized):
        tokens = item.split()
        without_the = " ".join(token for token in tokens if token != "the")
        if without_the:
            normalized.add(without_the)

    # Re-run the department transformation after prefix/article normalization.
    for item in list(normalized):
        if item.endswith(" department") and not item.startswith("department "):
            subject = item[: -len(" department")].strip()
            if subject:
                normalized.add(f"department of {subject}")

    return sorted(normalized)


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
