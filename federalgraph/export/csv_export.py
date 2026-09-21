from __future__ import annotations

from pathlib import Path

import pandas as pd

from federalgraph.common import ensure_dir, write_json


def write_rows(path: Path, rows: list[dict]) -> None:
    ensure_dir(path.parent)
    pd.DataFrame(rows).to_csv(path, index=False)


def export_all(
    out_dir: Path,
    organizations,
    aliases,
    sources,
    candidates,
    relationships,
    review,
    status,
    extraction_summary,
):
    ensure_dir(out_dir)
    write_rows(out_dir / "organizations.csv", organizations)
    write_rows(out_dir / "organization_aliases.csv", aliases)
    write_rows(out_dir / "organization_sources.csv", sources)
    write_rows(out_dir / "organization_match_candidates.csv", candidates)
    write_rows(out_dir / "organization_relationships.csv", relationships)
    write_rows(out_dir / "organization_review_queue.csv", review)
    write_rows(out_dir / "organization_status_evidence.csv", status)
    summary = {
        **extraction_summary,
        "canonical_entities": len(organizations),
        "organization_aliases": len(aliases),
        "source_records": len(sources),
        "identity_match_candidates": len(candidates),
        "hierarchy_candidates": len(relationships),
        "review_rows": len(review),
        "status_evidence_rows": len(status),
    }
    write_json(out_dir / "pipeline_summary.json", summary)
    return summary
