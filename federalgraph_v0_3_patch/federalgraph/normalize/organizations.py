from __future__ import annotations

from federalgraph.common import (
    acronym,
    domain,
    explicit_parenthetical_acronym,
    matching_tokens,
    normalize_name,
    organization_identity_keys,
    strip_parenthetical_acronym,
)


def normalize_records(records: list[dict]) -> list[dict]:
    out = []
    for rec in records:
        r = dict(rec)
        source_name = r.get("source_name", "")
        r["normalized_name"] = normalize_name(source_name)
        r["base_name"] = strip_parenthetical_acronym(source_name)
        r["identity_keys"] = "|".join(organization_identity_keys(source_name))
        r["match_tokens"] = "|".join(matching_tokens(source_name))
        r["acronym"] = acronym(source_name)
        r["explicit_acronym"] = explicit_parenthetical_acronym(source_name)
        r["domain"] = domain(r.get("website", ""))
        r["normalized_parent_name"] = normalize_name(r.get("parent_source_name", ""))
        out.append(r)
    return out
