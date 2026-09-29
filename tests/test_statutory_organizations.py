from pathlib import Path

import pandas as pd

from federalgraph.extract.sam_assistance import records_from_csv
from federalgraph.paths import ProjectPaths
from federalgraph.pipeline import Pipeline
from federalgraph.resolve.programs import resolve as resolve_programs


def test_statutory_organization_fills_sam_gap_without_duplicate_on_rebuild(tmp_path: Path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "sources.json").write_text("{}", encoding="utf-8")
    statutory = Path(__file__).resolve().parents[1] / "config" / "statutory_organization_sources.csv"
    (config / statutory.name).write_bytes(statutory.read_bytes())
    base = tmp_path / "base.csv"
    pd.DataFrame([
        {
            "source": "Test directory",
            "source_record_id": "other",
            "source_name": "Other Agency",
            "source_url": "https://example.test/other",
        }
    ]).to_csv(base, index=False)
    paths = ProjectPaths(tmp_path, config, tmp_path / "raw", tmp_path / "cache", tmp_path / "processed")

    first = Pipeline(paths).run_organizations(source_csv=base)
    assert first["canonical_entities"] == 2
    assert first["statutory_organization_source_records_added"] == 1
    source_rows = pd.read_csv(paths.processed / "organization_sources.csv").fillna("")
    statutory_row = source_rows.loc[
        source_rows["source_name"] == "Southeast Crescent Regional Commission"
    ].iloc[0]
    assert statutory_row["source"] == "U.S. Code"
    assert statutory_row["authority_citation"] == "40 U.S.C. 15301(a)(1)"
    assert "uscode.house.gov" in statutory_row["source_url"]

    sam_text = (
        'Program Title,Program Number,Federal Agency (030)\n'
        'Regional Grants,23.999,"SOUTHEAST CRESCENT REGIONAL COMMISSION, '
        'SOUTHEAST CRESCENT REGIONAL COMMISSION"\n'
    )
    sam_records, authorities, functions = records_from_csv(sam_text, "https://sam.gov/test")
    programs = resolve_programs(sam_records, authorities, functions, paths.processed)
    assert len(programs["program_organization_relationships"]) == 1
    assert programs["programs_without_organizations"] == []

    second = Pipeline(paths).run_organizations(
        source_csv=paths.processed / "organization_sources.csv"
    )
    assert second["canonical_entities"] == 2
    assert second["statutory_organization_source_records_added"] == 0
    assert second["source_records"] == 2
