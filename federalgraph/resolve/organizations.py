from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from rapidfuzz import fuzz

from federalgraph.common import (
    MEANINGFUL_WORDS,
    matching_tokens,
    normalize_name,
    organization_identity_keys,
    stable_id,
    strip_parenthetical_acronym,
)


@dataclass
class Candidate:
    left: int
    right: int
    score: float
    reasons: list[str]
    decision: str


class UnionFind:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[b] = a


def _same_source(a: dict, b: dict) -> bool:
    return a.get("source") == b.get("source")


def _identity_keys(rec: dict) -> set[str]:
    raw = rec.get("identity_keys", "")
    if isinstance(raw, str) and raw:
        return {item for item in raw.split("|") if item}
    return set(organization_identity_keys(rec.get("source_name", "")))


def _strong_identity_keys(rec: dict) -> set[str]:
    """Remove keys too short to be safe as automatic identity evidence."""

    keys = set()
    for key in _identity_keys(rec):
        compact = key.replace(" ", "")
        if len(compact) >= 4:
            keys.add(key)

    # Official directories frequently contain alphabetized/reordered versions of
    # exactly the same words ("Census Bureau" / "Bureau of the Census"). An
    # exact token multiset is deterministic lexical equivalence, not fuzzy
    # similarity. Require at least two meaningful tokens so short labels do not
    # become overly broad keys.
    tokens = matching_tokens(rec.get("base_name") or rec.get("source_name", ""))
    if len(tokens) >= 2:
        keys.add("tokens:" + " ".join(sorted(tokens)))
    return keys


def score_pair(a: dict, b: dict) -> tuple[float, list[str]]:
    """Score a *review* candidate.

    Automatic merging is intentionally not driven by this score. It happens only
    when records share a deterministic identity-equivalence key. Fuzzy scoring is
    used to prioritize unresolved pairs for human review.
    """

    na, nb = a.get("normalized_name", ""), b.get("normalized_name", "")
    ta = set(matching_tokens(a.get("base_name") or a.get("source_name", "")))
    tb = set(matching_tokens(b.get("base_name") or b.get("source_name", "")))
    reasons: list[str] = []

    if not na or not nb:
        return 0.0, reasons

    name_ratio = float(fuzz.ratio(na, nb))
    token_overlap = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    score = max(name_ratio, token_overlap * 100)

    if name_ratio >= 85:
        reasons.append(f"high_name_similarity:{name_ratio:.0f}")
    if token_overlap >= 0.60:
        reasons.append(f"high_token_overlap:{token_overlap:.2f}")

    # Acronyms can corroborate a plausible name match, but never establish a
    # candidate or a merge by themselves.
    aa, ab = a.get("acronym", ""), b.get("acronym", "")
    if aa and ab and aa == ab and len(aa) >= 3 and (name_ratio >= 60 or token_overlap >= 0.50):
        score = min(100.0, score + 4)
        reasons.append("same_acronym_support")

    # Shared domains and parents are corroborating evidence only.
    da, db = a.get("domain", ""), b.get("domain", "")
    if da and db and da == db and score >= 60:
        score = min(100.0, score + 4)
        reasons.append("same_domain_support")

    pa, pb = a.get("normalized_parent_name", ""), b.get("normalized_parent_name", "")
    if pa and pb and pa == pb and score >= 60:
        score = min(100.0, score + 3)
        reasons.append("same_parent_support")

    # Within the same official directory, differently named rows should remain
    # distinct unless deterministic alias rules already resolved them.
    if _same_source(a, b):
        score = min(score, 94.0)
        reasons.append("same_source_separation_guard")

    return round(score, 2), reasons


def _deterministic_alias_pairs(records: list[dict], uf: UnionFind) -> list[Candidate]:
    """Union records that share a conservative identity-equivalence key."""

    blocks: dict[str, set[int]] = defaultdict(set)
    for i, rec in enumerate(records):
        for key in _strong_identity_keys(rec):
            blocks[key].add(i)

    candidates: list[Candidate] = []
    seen: set[tuple[int, int]] = set()

    for key, ids in sorted(blocks.items()):
        # Very broad keys are evidence of an over-general normalization rule. Do
        # not allow them to silently collapse many records.
        if len(ids) > 20:
            continue
        for left, right in combinations(sorted(ids), 2):
            pair = (left, right)
            if pair in seen:
                continue
            seen.add(pair)
            uf.union(left, right)
            candidates.append(
                Candidate(
                    left,
                    right,
                    100.0,
                    [f"deterministic_alias_key:{key}"],
                    "auto_merge",
                )
            )

    return candidates


def _review_pairs(records: list[dict], uf: UnionFind, review_threshold: float) -> list[Candidate]:
    """Generate fuzzy candidates only after deterministic aliases are resolved."""

    blocks: dict[str, set[int]] = defaultdict(set)
    for i, rec in enumerate(records):
        tokens = matching_tokens(rec.get("base_name") or rec.get("source_name", ""))
        # Block on distinctive lexical evidence, never acronym or shared domain.
        for token in tokens:
            if len(token) < 4 or token in MEANINGFUL_WORDS:
                continue
            blocks[token].add(i)

    pairs: set[tuple[int, int]] = set()
    for ids in blocks.values():
        if len(ids) > 80:
            continue
        for left, right in combinations(sorted(ids), 2):
            if uf.find(left) != uf.find(right):
                pairs.add((left, right))

    candidates: list[Candidate] = []
    for left, right in sorted(pairs):
        score, reasons = score_pair(records[left], records[right])
        if score < review_threshold:
            continue
        candidates.append(Candidate(left, right, score, reasons, "manual_review"))
    return candidates


def _choose_canonical_name(member_recs: list[dict]) -> str:
    """Choose a readable display name without discarding any aliases.

    Prefer names independently attested across sources, but penalize known
    directory-index forms such as ``Agriculture Department``. USA.gov wins
    display-style ties because it is the current public directory.
    """

    support: dict[str, set[str]] = defaultdict(set)
    for rec in member_recs:
        base = strip_parenthetical_acronym(rec.get("source_name", ""))
        if base:
            support[normalize_name(base)].add(rec.get("source", ""))

    def rank(rec: dict) -> tuple:
        source = rec.get("source", "")
        base = strip_parenthetical_acronym(rec.get("source_name", ""))
        normalized = normalize_name(base)
        score = len(support.get(normalized, set())) * 100
        if source.startswith("USA.gov"):
            score += 10
        elif source.startswith("Federal Register"):
            score += 5
        if base.startswith("U.S. "):
            score += 2
        if "," in base:
            score -= 30
        if normalized.endswith(" department") and not normalized.startswith("department "):
            score -= 150
        return (-score, len(base), base.lower())

    ranked = sorted(member_recs, key=rank)
    return strip_parenthetical_acronym(ranked[0].get("source_name", ""))


def _alias_id(organization_id: str, alias: str) -> str:
    digest = hashlib.sha1(f"{organization_id}|{normalize_name(alias)}".encode("utf-8")).hexdigest()
    return f"ALIAS-{digest[:12].upper()}"


def _build_alias_rows(organization_id: str, member_recs: list[dict]) -> list[dict]:
    evidence: dict[tuple[str, str], dict[str, set[str]]] = {}

    for rec in member_recs:
        source = rec.get("source", "")
        source_record_id = str(rec.get("source_record_id", ""))
        source_name = (rec.get("source_name") or "").strip()
        if source_name:
            key = (source_name, "source_name")
            bucket = evidence.setdefault(key, {"sources": set(), "record_ids": set()})
            bucket["sources"].add(source)
            bucket["record_ids"].add(source_record_id)

        explicit_acronym = (rec.get("explicit_acronym") or "").strip()
        if explicit_acronym:
            key = (explicit_acronym, "source_acronym")
            bucket = evidence.setdefault(key, {"sources": set(), "record_ids": set()})
            bucket["sources"].add(source)
            bucket["record_ids"].add(source_record_id)

    rows = []
    for (alias, alias_type), bucket in sorted(evidence.items(), key=lambda item: item[0][0].lower()):
        rows.append(
            {
                "alias_id": _alias_id(organization_id, alias),
                "organization_id": organization_id,
                "alias": alias,
                "normalized_alias": normalize_name(alias),
                "alias_type": alias_type,
                "sources": "|".join(sorted(s for s in bucket["sources"] if s)),
                "source_record_ids": "|".join(sorted(r for r in bucket["record_ids"] if r)),
                "source_count": len({s for s in bucket["sources"] if s}),
            }
        )
    return rows


def resolve(
    records: list[dict],
    auto_merge_threshold: float = 96,
    review_threshold: float = 88,
    hierarchy_threshold: float = 80,
):
    # auto_merge_threshold remains in the public signature for configuration
    # compatibility. Fuzzy scores no longer drive automatic identity merges.
    del auto_merge_threshold, hierarchy_threshold

    n = len(records)
    uf = UnionFind(n)

    deterministic = _deterministic_alias_pairs(records, uf)
    fuzzy = _review_pairs(records, uf, review_threshold)
    candidates = deterministic + fuzzy

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[uf.find(i)].append(i)

    organizations: list[dict] = []
    alias_rows: list[dict] = []
    source_rows: list[dict] = []
    idx_to_org: dict[int, str] = {}

    for members in groups.values():
        member_recs = [records[i] for i in members]
        name = _choose_canonical_name(member_recs)
        oid = stable_id(name)
        aliases = sorted({r.get("source_name", "") for r in member_recs if r.get("source_name")})
        domains = sorted({r.get("domain", "") for r in member_recs if r.get("domain")})
        srcs = sorted({r.get("source", "") for r in member_recs if r.get("source")})
        parents = sorted(
            {r.get("parent_source_name", "") for r in member_recs if r.get("parent_source_name")}
        )

        org = {
            "external_id": oid,
            "canonical_name": name,
            "normalized_name": normalize_name(name),
            "aliases": "|".join(aliases),
            "domains": "|".join(domains),
            "sources": "|".join(srcs),
            "parent_name_candidates": "|".join(parents),
            "source_record_count": len(member_recs),
            "resolution_status": (
                "Deterministically resolved" if len(member_recs) > 1 else "Single-source provisional"
            ),
            "active_status": "Unreviewed",
        }
        organizations.append(org)
        alias_rows.extend(_build_alias_rows(oid, member_recs))

        for i, rec in zip(members, member_recs):
            idx_to_org[i] = oid
            source_row = dict(rec)
            source_row["canonical_external_id"] = oid
            source_row["match_method"] = (
                "deterministic_alias" if len(member_recs) > 1 else "new_entity"
            )
            source_rows.append(source_row)

    candidate_rows: list[dict] = []
    review: list[dict] = []
    orgs_needing_review: set[str] = set()

    for candidate in candidates:
        left_rec, right_rec = records[candidate.left], records[candidate.right]
        left_org = idx_to_org[candidate.left]
        right_org = idx_to_org[candidate.right]

        row = {
            "left_source": left_rec.get("source"),
            "left_source_record_id": left_rec.get("source_record_id"),
            "left_name": left_rec.get("source_name"),
            "right_source": right_rec.get("source"),
            "right_source_record_id": right_rec.get("source_record_id"),
            "right_name": right_rec.get("source_name"),
            "score": candidate.score,
            "reasons": "|".join(candidate.reasons),
            "decision": candidate.decision,
            "left_canonical_external_id": left_org,
            "right_canonical_external_id": right_org,
        }
        candidate_rows.append(row)

        if candidate.decision == "manual_review" and left_org != right_org:
            orgs_needing_review.update({left_org, right_org})
            review.append(
                {
                    **row,
                    "review_action": "merge / keep separate / hierarchy / historical alias",
                    "review_notes": "",
                }
            )

    for org in organizations:
        if org["external_id"] in orgs_needing_review:
            org["resolution_status"] = "Needs review"

    # Hierarchy is independent of identity. The current directories rarely supply
    # parent names, but FPI and future sources can populate them without changing
    # the identity resolver.
    name_to_ids: dict[str, list[int]] = defaultdict(list)
    for i, rec in enumerate(records):
        name_to_ids[rec.get("normalized_name", "")].append(i)

    relationships: list[dict] = []
    seen_rel: set[tuple[str, str]] = set()
    for i, rec in enumerate(records):
        parent_norm = rec.get("normalized_parent_name", "")
        if not parent_norm:
            continue
        for parent_index in name_to_ids.get(parent_norm, []):
            parent_id, child_id = idx_to_org[parent_index], idx_to_org[i]
            if parent_id == child_id:
                continue
            key = (parent_id, child_id)
            if key in seen_rel:
                continue
            seen_rel.add(key)
            relationships.append(
                {
                    "parent_org_id": parent_id,
                    "child_org_id": child_id,
                    "relationship_type": "parent/component",
                    "source": rec.get("source"),
                    "confidence": "High",
                    "review_status": "Provisional",
                    "evidence": rec.get("parent_source_name", ""),
                }
            )

    status: list[dict] = []
    for org in organizations:
        srcset = set(org["sources"].split("|")) if org["sources"] else set()
        found_usagov = any(source.startswith("USA.gov") for source in srcset)
        status.append(
            {
                "external_id": org["external_id"],
                "canonical_name": org["canonical_name"],
                "found_in_usagov": found_usagov,
                "found_in_federal_register": any(
                    source.startswith("Federal Register") for source in srcset
                ),
                "found_in_program_inventory": any(
                    source.startswith("Current Federal") for source in srcset
                ),
                "suggested_status": "Likely current" if found_usagov else "Needs status review",
                "status_basis": (
                    "USA.gov presence" if found_usagov else "No current-directory confirmation"
                ),
                "review_status": "Unreviewed",
            }
        )

    organizations = sorted(organizations, key=lambda row: row["canonical_name"].lower())
    alias_rows = sorted(alias_rows, key=lambda row: (row["organization_id"], row["alias"].lower()))
    candidate_rows = sorted(
        candidate_rows,
        key=lambda row: (-float(row["score"]), str(row["left_name"]), str(row["right_name"])),
    )
    review = sorted(
        review,
        key=lambda row: (-float(row["score"]), str(row["left_name"]), str(row["right_name"])),
    )

    return organizations, alias_rows, source_rows, candidate_rows, relationships, review, status
