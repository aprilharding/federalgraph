from __future__ import annotations
from federalgraph.common import normalize_name, matching_tokens, acronym, domain

def normalize_records(records: list[dict]) -> list[dict]:
    out = []
    for rec in records:
        r = dict(rec)
        r["normalized_name"] = normalize_name(r.get("source_name", ""))
        r["match_tokens"] = "|".join(matching_tokens(r.get("source_name", "")))
        r["acronym"] = acronym(r.get("source_name", ""))
        r["domain"] = domain(r.get("website", ""))
        r["normalized_parent_name"] = normalize_name(r.get("parent_source_name", ""))
        out.append(r)
    return out
