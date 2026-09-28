from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import pandas as pd
from rapidfuzz.fuzz import token_set_ratio

from federalgraph.common import normalize_name

_SOURCE_PRIORITY = {
    "sam_assistance": 10,
    "treasury_tax_expenditures": 20,
    "performance_fpi_archive": 30,
    "supplemental": 90,
}


def _program_id(anchor: str) -> str:
    digest = hashlib.sha1(anchor.encode("utf-8")).hexdigest()[:10].upper()
    return f"PRG{digest}"


def _source_key(row: dict) -> str:
    return f"{row.get('source_key','')}::{row.get('source_record_id','')}"


def _load_org_index(processed_dir: Path) -> tuple[dict[str, set[str]], dict[str, str]]:
    names: dict[str, set[str]] = defaultdict(set)
    canonical: dict[str, str] = {}
    org_path = processed_dir / "organizations.csv"
    if not org_path.exists():
        return names, canonical
    for row in pd.read_csv(org_path).fillna("").to_dict("records"):
        org_id = str(row.get("organization_id") or row.get("external_id") or row.get("org_id") or "")
        name = str(row.get("canonical_name") or row.get("name") or "")
        if org_id and name:
            names[normalize_name(name)].add(org_id)
            canonical[org_id] = name
    alias_path = processed_dir / "organization_aliases.csv"
    if alias_path.exists():
        for row in pd.read_csv(alias_path).fillna("").to_dict("records"):
            org_id = str(row.get("organization_id") or row.get("external_id") or row.get("org_id") or "")
            alias = str(row.get("alias") or row.get("alias_name") or row.get("name") or "")
            if org_id and alias:
                names[normalize_name(alias)].add(org_id)
    source_path = processed_dir / "organization_sources.csv"
    if source_path.exists():
        for row in pd.read_csv(source_path).fillna("").to_dict("records"):
            org_id = str(row.get("organization_id") or row.get("canonical_external_id") or row.get("external_id") or row.get("org_id") or "")
            name = str(row.get("source_name") or "")
            if org_id and name:
                names[normalize_name(name)].add(org_id)
    return names, canonical


def map_organizations(records: list[dict], processed_dir: Path) -> tuple[list[dict], list[dict]]:
    index, canonical = _load_org_index(processed_dir)
    mapped: list[dict] = []
    review: list[dict] = []
    for row in records:
        candidates = [
            ("office", str(row.get("office_source_name") or "")),
            ("agency", str(row.get("agency_source_name") or "")),
            ("department", str(row.get("department_source_name") or "")),
        ]
        match_id = ""
        method = ""
        raw_name = ""
        raw_level = ""
        for level, name in candidates:
            key = normalize_name(name)
            ids = index.get(key, set()) if key else set()
            if len(ids) == 1:
                match_id = next(iter(ids))
                method = f"exact_{level}_name_or_alias"
                raw_name = name
                raw_level = level
                break
            if len(ids) > 1:
                review.append(
                    {
                        "program_source_key": _source_key(row),
                        "program_source_name": row.get("source_name", ""),
                        "organization_source_name": name,
                        "organization_source_level": level,
                        "issue": "ambiguous_exact_organization_match",
                        "candidate_organization_ids": "|".join(sorted(ids)),
                    }
                )
                break
        copy = dict(row)
        copy.update(
            {
                "organization_id": match_id,
                "organization_canonical_name": canonical.get(match_id, ""),
                "organization_mapping_method": method,
                "organization_source_name_used": raw_name,
                "organization_source_level_used": raw_level,
            }
        )
        mapped.append(copy)
        if not match_id and not any(r["program_source_key"] == _source_key(row) for r in review):
            names = [name for _, name in candidates if name]
            review.append(
                {
                    "program_source_key": _source_key(row),
                    "program_source_name": row.get("source_name", ""),
                    "organization_source_name": " | ".join(names),
                    "organization_source_level": "",
                    "issue": "no_exact_organization_match",
                    "candidate_organization_ids": "",
                }
            )
    return mapped, review


def _aliases(row: dict) -> set[str]:
    values = {
        str(row.get("source_name") or "").strip(),
        str(row.get("popular_long_name") or "").strip(),
        str(row.get("popular_short_name") or "").strip(),
    }
    return {v for v in values if v}


def _specific_usc(authority_rows: Iterable[dict]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for row in authority_rows:
        title = str(row.get("usc_title") or "").strip()
        section = str(row.get("usc_section") or "").strip()
        if title and section:
            out[f"{row.get('source_key')}::{row.get('program_source_record_id')}"] .add(f"{title}:{section}")
    return out


def resolve(
    records: list[dict],
    authority_rows: list[dict],
    function_rows: list[dict],
    processed_dir: Path,
) -> dict[str, list[dict]]:
    mapped, org_review = map_organizations(records, processed_dir)
    authorities = _specific_usc(authority_rows)

    # Union-find, but only for strong deterministic/equivalent evidence.
    keys = [_source_key(row) for row in mapped]
    parent = {key: key for key in keys}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Exact normalized source name + same resolved organization is safe enough to auto-cluster.
    by_name_org: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in mapped:
        norm = normalize_name(str(row.get("source_name") or ""))
        org = str(row.get("organization_id") or "")
        if norm and org:
            by_name_org[(norm, org)].append(_source_key(row))
    for group in by_name_org.values():
        for key in group[1:]:
            union(group[0], key)

    # Same exact USC section + same org + meaningfully similar names is additional strong evidence.
    by_org_usc: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in mapped:
        key = _source_key(row)
        org = str(row.get("organization_id") or "")
        for citation in authorities.get(key, set()):
            if org:
                by_org_usc[(org, citation)].append(row)
    for group in by_org_usc.values():
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                if token_set_ratio(left.get("source_name", ""), right.get("source_name", "")) >= 92:
                    union(_source_key(left), _source_key(right))

    clusters: dict[str, list[dict]] = defaultdict(list)
    for row in mapped:
        clusters[find(_source_key(row))].append(row)

    programs: list[dict] = []
    sources: list[dict] = []
    aliases: list[dict] = []
    relationships: list[dict] = []
    match_candidates: list[dict] = []
    key_to_program: dict[str, str] = {}

    for cluster_rows in clusters.values():
        anchor_row = sorted(
            cluster_rows,
            key=lambda row: (_SOURCE_PRIORITY.get(str(row.get("source_key")), 999), _source_key(row)),
        )[0]
        anchor = _source_key(anchor_row)
        program_id = _program_id(anchor)
        canonical_name = str(anchor_row.get("source_name") or "").strip()
        org_ids = sorted({str(r.get("organization_id") or "") for r in cluster_rows if r.get("organization_id")})
        program_type = "tax_expenditure" if any(r.get("source_key") == "treasury_tax_expenditures" for r in cluster_rows) else ""

        # Canonical purpose: exact statutory purpose when available; otherwise an official agency objective/description.
        statutory = []
        for auth in authority_rows:
            key = f"{auth.get('source_key')}::{auth.get('program_source_record_id')}"
            if any(key == _source_key(r) for r in cluster_rows) and auth.get("statutory_purpose_text"):
                statutory.append(str(auth.get("statutory_purpose_text")))
        agency_purpose = next((str(r.get("agency_stated_purpose") or "").strip() for r in cluster_rows if str(r.get("agency_stated_purpose") or "").strip()), "")
        canonical_purpose = statutory[0] if statutory else agency_purpose
        purpose_type = "statutory" if statutory else ("agency_stated" if agency_purpose else "")

        programs.append(
            {
                "program_id": program_id,
                "canonical_name": canonical_name,
                "program_type": program_type,
                "canonical_purpose": canonical_purpose,
                "canonical_purpose_type": purpose_type,
                "status": str(anchor_row.get("source_status") or ""),
                "primary_organization_id": org_ids[0] if len(org_ids) == 1 else "",
                "source_count": len(cluster_rows),
                "resolution_status": "resolved" if len(org_ids) <= 1 else "needs_review",
            }
        )
        seen_aliases: set[str] = set()
        for row in cluster_rows:
            key = _source_key(row)
            key_to_program[key] = program_id
            copy = dict(row)
            copy["program_id"] = program_id
            sources.append(copy)
            for alias in _aliases(row):
                if alias not in seen_aliases:
                    aliases.append(
                        {
                            "program_id": program_id,
                            "alias": alias,
                            "source_key": row.get("source_key", ""),
                            "source_record_id": row.get("source_record_id", ""),
                        }
                    )
                    seen_aliases.add(alias)
            if row.get("organization_id"):
                relationships.append(
                    {
                        "program_id": program_id,
                        "organization_id": row.get("organization_id", ""),
                        "relationship_type": "administered_by",
                        "source_key": row.get("source_key", ""),
                        "source_record_id": row.get("source_record_id", ""),
                        "mapping_method": row.get("organization_mapping_method", ""),
                    }
                )

    # Cross-cluster fuzzy similarities are review-only. Generate pairs only where
    # there is corroborating organization or authority context rather than comparing
    # every program with every other program.
    pair_keys: set[tuple[str, str]] = set()
    by_org: dict[str, list[dict]] = defaultdict(list)
    by_usc: dict[str, list[dict]] = defaultdict(list)
    for row in mapped:
        if row.get("organization_id"):
            by_org[str(row["organization_id"])].append(row)
        for citation in authorities.get(_source_key(row), set()):
            by_usc[citation].append(row)

    for groups in (by_org.values(), by_usc.values()):
        for group in groups:
            for i, left in enumerate(group):
                for right in group[i + 1 :]:
                    a, b = sorted((_source_key(left), _source_key(right)))
                    pair_keys.add((a, b))

    rows_by_key = {_source_key(row): row for row in mapped}
    for left_key, right_key in sorted(pair_keys):
        left, right = rows_by_key[left_key], rows_by_key[right_key]
        if find(left_key) == find(right_key):
            continue
        score = token_set_ratio(left.get("source_name", ""), right.get("source_name", ""))
        same_org = bool(left.get("organization_id") and left.get("organization_id") == right.get("organization_id"))
        shared_usc = sorted(authorities.get(left_key, set()) & authorities.get(right_key, set()))
        if score >= 88 and (same_org or shared_usc):
            match_candidates.append(
                {
                    "left_program_id": key_to_program.get(left_key, ""),
                    "right_program_id": key_to_program.get(right_key, ""),
                    "left_name": left.get("source_name", ""),
                    "right_name": right.get("source_name", ""),
                    "name_similarity": score,
                    "same_organization": same_org,
                    "shared_usc": "|".join(shared_usc),
                    "decision": "review",
                }
            )

    mapped_authorities: list[dict] = []
    for row in authority_rows:
        key = f"{row.get('source_key')}::{row.get('program_source_record_id')}"
        copy = dict(row)
        copy["program_id"] = key_to_program.get(key, "")
        mapped_authorities.append(copy)

    mapped_functions: list[dict] = []
    for row in function_rows:
        key = f"sam_assistance::{row.get('program_source_record_id')}"
        copy = dict(row)
        copy["program_id"] = key_to_program.get(key, "")
        mapped_functions.append(copy)

    orphan_programs = [
        {
            "program_id": row["program_id"],
            "canonical_name": row["canonical_name"],
            "program_type": row["program_type"],
            "reason": "no_resolved_administering_organization",
        }
        for row in programs
        if not row["primary_organization_id"]
    ]

    org_path = processed_dir / "organizations.csv"
    organizations_without_programs: list[dict] = []
    if org_path.exists():
        orgs = pd.read_csv(org_path).fillna("").to_dict("records")
        used = {r["organization_id"] for r in relationships if r.get("organization_id")}
        for org in orgs:
            oid = str(org.get("organization_id") or org.get("external_id") or org.get("org_id") or "")
            if oid and oid not in used:
                organizations_without_programs.append(
                    {
                        "organization_id": oid,
                        "canonical_name": org.get("canonical_name") or org.get("name") or "",
                    }
                )

    return {
        "programs": programs,
        "program_sources": sources,
        "program_aliases": aliases,
        "program_authorities": mapped_authorities,
        "program_functions": mapped_functions,
        "program_organization_relationships": relationships,
        "program_match_candidates": match_candidates,
        "organization_mapping_review_queue": org_review,
        "programs_without_organizations": orphan_programs,
        "organizations_without_programs": organizations_without_programs,
    }
