from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from rapidfuzz import fuzz

from federalgraph.resolve.name_authority import choose_canonical_name

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


def _opm_structural_identity_key(rec: dict) -> str:
    """Return an authoritative OPM identity key when reporting levels are the same unit.

    OPM Federal Workforce Data often emits the same standalone organization at
    department, agency, and default-subagency levels using different display
    strings (usually abbreviated or truncated). When the department and agency
    codes are identical, and a default subagency is exactly ``XX00``, those rows
    are reporting representations of the same organizational identity.

    This deliberately does *not* merge component agencies inside a larger
    department (for example DOD/AF/AR/NV), or named subagencies such as DD13.
    """

    if rec.get("source") != "OPM Federal Workforce Data":
        return ""

    level = (rec.get("source_level") or "").strip().lower()
    dept = str(rec.get("opm_department_code") or "").strip()
    agency = str(rec.get("opm_agency_code") or "").strip()
    subagency = str(rec.get("opm_subagency_code") or "").strip()

    if level == "department" and dept:
        return f"opm-unit:{dept}"
    if level == "agency" and dept and agency and dept == agency:
        return f"opm-unit:{dept}"
    if (
        level == "subagency"
        and dept
        and agency
        and dept == agency
        and subagency == f"{agency}00"
    ):
        return f"opm-unit:{dept}"
    return ""


def _strong_identity_keys(rec: dict) -> set[str]:
    """Remove keys too short to be safe as automatic identity evidence."""

    keys = set()
    opm_key = _opm_structural_identity_key(rec)
    if opm_key:
        keys.add(opm_key)
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


def _review_pairs(
    records: list[dict],
    uf: UnionFind,
    review_threshold: float,
    blocked_root_pairs: set[tuple[int, int]] | None = None,
) -> list[Candidate]:
    """Generate fuzzy candidates only after deterministic/manual identity decisions are resolved."""

    blocked_root_pairs = blocked_root_pairs or set()

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
            left_root, right_root = uf.find(left), uf.find(right)
            if left_root == right_root:
                continue
            root_pair = tuple(sorted((left_root, right_root)))
            if root_pair in blocked_root_pairs:
                continue
            pairs.add((left, right))

    candidates: list[Candidate] = []
    for left, right in sorted(pairs):
        # Distinct rows from the same authoritative directory are not fuzzy
        # duplicate candidates. Same-source aliases must resolve through a
        # deterministic identity key (including OPM structural codes) or an
        # explicit human override. This prevents structurally distinct OPM
        # subagencies such as Army North/Army South from flooding the queue.
        if _same_source(records[left], records[right]):
            continue
        score, reasons = score_pair(records[left], records[right])
        if score < review_threshold:
            continue
        candidates.append(Candidate(left, right, score, reasons, "manual_review"))
    return candidates



def _override_name_key(value: str) -> str:
    return normalize_name((value or "").strip())


def _apply_identity_overrides(
    records: list[dict],
    uf: UnionFind,
    overrides: list[dict] | None,
) -> tuple[list[Candidate], set[tuple[int, int]], dict[int, str], set[int], set[int]]:
    """Apply persistent human identity decisions.

    Overrides are intentionally human-readable and keyed by source-visible names.
    They are applied after deterministic lexical aliases but before fuzzy review.
    ``merge`` and ``historical_alias`` union the two identities. ``keep_separate``
    suppresses that pair from future review runs. Preferred names are used only
    for reviewed merges and never inferred from fuzzy scores.
    """

    if not overrides:
        return [], set(), {}, set(), set()

    name_to_indices: dict[str, set[int]] = defaultdict(set)
    for i, rec in enumerate(records):
        source_name = rec.get("source_name", "")
        base_name = rec.get("base_name", "")
        for value in (source_name, base_name):
            key = _override_name_key(value)
            if key:
                name_to_indices[key].add(i)

    applied: list[Candidate] = []
    keep_specs: list[tuple[set[int], set[int]]] = []
    preferred_specs: list[tuple[set[int], set[int], str]] = []
    merge_members: set[int] = set()

    for override in overrides:
        left_key = _override_name_key(override.get("left_name", ""))
        right_key = _override_name_key(override.get("right_name", ""))
        decision = (override.get("decision") or "").strip().lower()
        preferred_name = (override.get("preferred_name") or "").strip()
        left_ids = set(name_to_indices.get(left_key, set()))
        right_ids = set(name_to_indices.get(right_key, set()))

        if not left_ids or not right_ids:
            # Source directories change over time. A stale override should not
            # break the build; it simply remains unapplied until the alias is
            # present again.
            continue

        left_rep, right_rep = min(left_ids), min(right_ids)
        if decision in {"merge", "historical_alias"}:
            for left in left_ids:
                for right in right_ids:
                    uf.union(left, right)
                    merge_members.update({left, right})
            preferred_specs.append((left_ids, right_ids, preferred_name))
            applied.append(
                Candidate(
                    left_rep,
                    right_rep,
                    100.0,
                    [f"human_override:{decision}"],
                    f"manual_{decision}",
                )
            )
        elif decision == "keep_separate":
            keep_specs.append((left_ids, right_ids))
            applied.append(
                Candidate(
                    left_rep,
                    right_rep,
                    100.0,
                    ["human_override:keep_separate"],
                    "manual_keep_separate",
                )
            )

    # Resolve keep-separate pairs against the union-find roots *after* all human
    # merges have been applied. This suppresses every record-level variant of the
    # reviewed pair, not merely the two display names in the CSV.
    blocked_root_pairs: set[tuple[int, int]] = set()
    keep_roots: set[int] = set()
    for left_ids, right_ids in keep_specs:
        left_roots = {uf.find(i) for i in left_ids}
        right_roots = {uf.find(i) for i in right_ids}
        for left_root in left_roots:
            for right_root in right_roots:
                if left_root == right_root:
                    continue
                blocked_root_pairs.add(tuple(sorted((left_root, right_root))))
                keep_roots.update({left_root, right_root})

    preferred_names: dict[int, str] = {}
    for left_ids, right_ids, preferred_name in preferred_specs:
        if not preferred_name:
            continue
        roots = {uf.find(i) for i in left_ids | right_ids}
        for root in roots:
            preferred_names[root] = preferred_name

    merge_roots = {uf.find(i) for i in merge_members}
    return applied, blocked_root_pairs, preferred_names, merge_roots, keep_roots


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
    identity_overrides: list[dict] | None = None,
):
    # auto_merge_threshold remains in the public signature for configuration
    # compatibility. Fuzzy scores no longer drive automatic identity merges.
    del auto_merge_threshold, hierarchy_threshold

    n = len(records)
    uf = UnionFind(n)

    deterministic = _deterministic_alias_pairs(records, uf)
    manual, blocked_root_pairs, preferred_names, merge_roots, keep_roots = _apply_identity_overrides(
        records, uf, identity_overrides
    )
    fuzzy = _review_pairs(records, uf, review_threshold, blocked_root_pairs)
    candidates = deterministic + manual + fuzzy

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[uf.find(i)].append(i)

    organizations: list[dict] = []
    alias_rows: list[dict] = []
    source_rows: list[dict] = []
    name_review: list[dict] = []
    idx_to_org: dict[int, str] = {}

    for root, members in groups.items():
        member_recs = [records[i] for i in members]
        name_choice = choose_canonical_name(member_recs, preferred_names.get(root, ""))
        name = name_choice.name
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
            "canonical_name_source": name_choice.source,
            "canonical_name_source_record_id": name_choice.source_record_id,
            "canonical_name_as_of": name_choice.source_as_of,
            "canonical_name_authority_tier": name_choice.authority_tier,
            "canonical_name_status": name_choice.status,
            "normalized_name": normalize_name(name),
            "aliases": "|".join(aliases),
            "domains": "|".join(domains),
            "sources": "|".join(srcs),
            "parent_name_candidates": "|".join(parents),
            "source_record_count": len(member_recs),
            "resolution_status": (
                "Reviewed merge"
                if root in merge_roots
                else (
                    "Reviewed separate"
                    if root in keep_roots
                    else (
                        "Deterministically resolved"
                        if len(member_recs) > 1
                        else "Single-source provisional"
                    )
                )
            ),
            "active_status": "Unreviewed",
        }
        organizations.append(org)
        alias_rows.extend(_build_alias_rows(oid, member_recs))
        if name_choice.needs_review:
            name_review.append(
                {
                    "external_id": oid,
                    "chosen_name": name_choice.name,
                    "chosen_source": name_choice.source,
                    "chosen_source_record_id": name_choice.source_record_id,
                    "canonical_name_status": name_choice.status,
                    "candidate_names": "|".join(name_choice.variants),
                    "review_action": "confirm canonical name / select fallback name",
                    "review_notes": "",
                }
            )

        for i, rec in zip(members, member_recs):
            idx_to_org[i] = oid
            source_row = dict(rec)
            source_row["canonical_external_id"] = oid
            source_row["match_method"] = (
                "reviewed_identity_merge"
                if root in merge_roots
                else ("deterministic_alias" if len(member_recs) > 1 else "new_entity")
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
    name_review = sorted(name_review, key=lambda row: str(row["chosen_name"]).lower())

    return (
        organizations,
        alias_rows,
        source_rows,
        candidate_rows,
        relationships,
        review,
        name_review,
        status,
    )
