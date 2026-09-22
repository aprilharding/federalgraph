from __future__ import annotations

from dataclasses import dataclass

from federalgraph.common import normalize_name, organization_identity_keys, strip_parenthetical_acronym


# Canonical naming is a field-level authority policy, not a general source ranking.
# The U.S. Government Manual is authoritative for the canonical display name
# whenever the resolved entity appears there. Other sources remain preserved as aliases.
SOURCE_TIERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("govinfo_govman", ("U.S. Government Manual", "US Government Manual", "GovInfo Government Manual")),
    ("opm_fwd", ("OPM Federal Workforce Data", "OPM EHRI", "OPM FedScope")),
    ("federal_register", ("Federal Register",)),
    ("usagov", ("USA.gov",)),
)


@dataclass(frozen=True)
class NameChoice:
    name: str
    source: str
    source_record_id: str
    source_as_of: str
    authority_tier: str
    status: str
    needs_review: bool
    variants: tuple[str, ...]


def source_tier(source: str) -> str:
    value = (source or "").strip()
    for tier, prefixes in SOURCE_TIERS:
        if any(value.startswith(prefix) for prefix in prefixes):
            return tier
    return "other"


def _as_of(rec: dict) -> str:
    return str(
        rec.get("source_as_of")
        or rec.get("publication_date")
        or rec.get("data_as_of")
        or ""
    ).strip()


def _display_name(rec: dict, *, exact: bool = False) -> str:
    raw = str(rec.get("source_name") or "").strip()
    return raw if exact else strip_parenthetical_acronym(raw)


def _equivalent_names(a: str, b: str) -> bool:
    if normalize_name(a) == normalize_name(b):
        return True
    return bool(set(organization_identity_keys(a)) & set(organization_identity_keys(b)))


def _has_material_name_disagreement(names: list[str]) -> bool:
    names = [n for n in names if n]
    if len(names) < 2:
        return False
    anchor = names[0]
    return any(not _equivalent_names(anchor, other) for other in names[1:])


def _latest_record(records: list[dict]) -> dict:
    """Choose deterministically, preferring records with the latest dated evidence."""

    return sorted(
        records,
        key=lambda rec: (
            _as_of(rec),
            _display_name(rec, exact=True).lower(),
            str(rec.get("source_record_id") or ""),
        ),
        reverse=True,
    )[0]


def choose_canonical_name(member_recs: list[dict], preferred_name: str = "") -> NameChoice:
    """Apply FederalGraph's canonical-name authority policy.

    Identity resolution must already have determined that ``member_recs`` are one
    entity. Naming is then resolved independently:

    1. Latest U.S. Government Manual / GovInfo name is authoritative.
    2. If no Government Manual record exists, a reviewed preferred name wins.
    3. Otherwise choose OPM > Federal Register > USA.gov > other as a reproducible
       provisional fallback.
    4. When the entity is absent from GovInfo and non-equivalent source names
       disagree, flag it for naming review instead of pretending the fallback is
       authoritative.
    """

    usable = [rec for rec in member_recs if str(rec.get("source_name") or "").strip()]
    if not usable:
        return NameChoice("", "", "", "", "other", "Missing name", True, tuple())

    govinfo = [rec for rec in usable if source_tier(str(rec.get("source") or "")) == "govinfo_govman"]
    if govinfo:
        chosen = _latest_record(govinfo)
        latest_date = _as_of(chosen)
        latest = [rec for rec in govinfo if _as_of(rec) == latest_date] if latest_date else govinfo
        latest_names = sorted({_display_name(rec, exact=True) for rec in latest if _display_name(rec, exact=True)})
        conflict = _has_material_name_disagreement(latest_names)
        return NameChoice(
            name=_display_name(chosen, exact=True),
            source=str(chosen.get("source") or ""),
            source_record_id=str(chosen.get("source_record_id") or ""),
            source_as_of=latest_date,
            authority_tier="govinfo_govman",
            status="GovInfo conflict - naming review" if conflict else "GovInfo authoritative",
            needs_review=conflict,
            variants=tuple(latest_names),
        )

    all_names = sorted({_display_name(rec) for rec in usable if _display_name(rec)})

    if preferred_name:
        return NameChoice(
            name=preferred_name.strip(),
            source="Human-reviewed identity override",
            source_record_id="",
            source_as_of="",
            authority_tier="human_review",
            status="Reviewed fallback name",
            needs_review=False,
            variants=tuple(all_names),
        )

    by_tier: dict[str, list[dict]] = {}
    for rec in usable:
        by_tier.setdefault(source_tier(str(rec.get("source") or "")), []).append(rec)

    chosen: dict | None = None
    chosen_tier = "other"
    for tier in ("opm_fwd", "federal_register", "usagov", "other"):
        if by_tier.get(tier):
            chosen_tier = tier
            chosen = _latest_record(by_tier[tier])
            break

    assert chosen is not None
    disagreement = _has_material_name_disagreement(all_names)
    return NameChoice(
        name=_display_name(chosen),
        source=str(chosen.get("source") or ""),
        source_record_id=str(chosen.get("source_record_id") or ""),
        source_as_of=_as_of(chosen),
        authority_tier=chosen_tier,
        status="Fallback provisional - naming review" if disagreement else "Fallback source hierarchy",
        needs_review=disagreement,
        variants=tuple(all_names),
    )
