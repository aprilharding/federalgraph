from __future__ import annotations

from pathlib import Path

import pandas as pd

from federalgraph.common import ensure_dir, write_json


def _write(path: Path, rows: list[dict]) -> None:
    ensure_dir(path.parent)
    pd.DataFrame(rows).to_csv(path, index=False)


def export_programs(out_dir: Path, outputs: dict[str, list[dict]], extraction_summary: dict) -> dict:
    ensure_dir(out_dir)
    for name, rows in outputs.items():
        _write(out_dir / f"{name}.csv", rows)
    summary = {
        **extraction_summary,
        "canonical_programs": len(outputs.get("programs", [])),
        "program_source_records": len(outputs.get("program_sources", [])),
        "program_authorities": len(outputs.get("program_authorities", [])),
        "program_functions": len(outputs.get("program_functions", [])),
        "program_organization_relationships": len(outputs.get("program_organization_relationships", [])),
        "program_identity_review_rows": len(outputs.get("program_match_candidates", [])),
        "organization_mapping_review_rows": len(outputs.get("organization_mapping_review_queue", [])),
        "programs_without_organizations": len(outputs.get("programs_without_organizations", [])),
        "organizations_without_programs": len(outputs.get("organizations_without_programs", [])),
    }
    write_json(out_dir / "program_pipeline_summary.json", summary)
    return summary
