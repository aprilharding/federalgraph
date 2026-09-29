from pathlib import Path

import pandas as pd

from federalgraph.resolve.programs import map_organizations, resolve


def _write_orgs(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"external_id": "ORG-TREASURY", "canonical_name": "Department of the Treasury"},
            {"external_id": "ORG-IRS", "canonical_name": "Internal Revenue Service"},
        ]
    ).to_csv(path / "organizations.csv", index=False)
    pd.DataFrame(
        [
            {"organization_id": "ORG-IRS", "alias": "IRS"},
            {"organization_id": "ORG-TREASURY", "alias": "Treasury Department"},
        ]
    ).to_csv(path / "organization_aliases.csv", index=False)
    pd.DataFrame(
        [
            {"canonical_external_id": "ORG-IRS", "source_name": "INTERNAL REVENUE SERVICE"},
        ]
    ).to_csv(path / "organization_sources.csv", index=False)


def test_programs_merge_on_same_name_and_org_and_prefer_statutory_purpose(tmp_path: Path):
    processed = tmp_path / "processed"
    _write_orgs(processed)
    records = [
        {
            "source_key": "sam_assistance",
            "source_record_id": "21.001",
            "source_name": "Example Taxpayer Program",
            "agency_source_name": "IRS",
            "department_source_name": "Department of the Treasury",
            "agency_stated_purpose": "Agency description.",
            "source_status": "Active",
        },
        {
            "source_key": "performance_fpi_archive",
            "source_record_id": "TRE-001",
            "source_name": "Example Taxpayer Program",
            "agency_source_name": "Internal Revenue Service",
            "agency_stated_purpose": "Historical agency description.",
        },
    ]
    authorities = [
        {
            "source_key": "sam_assistance",
            "program_source_record_id": "21.001",
            "usc_title": "26",
            "usc_section": "9999",
            "statutory_purpose_text": "The Secretary shall carry out a program to assist taxpayers.",
        }
    ]
    outputs = resolve(records, authorities, [], processed)
    assert len(outputs["programs"]) == 1
    program = outputs["programs"][0]
    assert program["primary_organization_id"] == "ORG-IRS"
    assert program["canonical_purpose_type"] == "statutory"
    assert "assist taxpayers" in program["canonical_purpose"]


def test_unmapped_program_is_preserved_as_orphan(tmp_path: Path):
    processed = tmp_path / "processed"
    _write_orgs(processed)
    records = [
        {
            "source_key": "performance_fpi_archive",
            "source_record_id": "X-1",
            "source_name": "Mystery Program",
            "agency_source_name": "Agency Not In Graph",
        }
    ]
    outputs = resolve(records, [], [], processed)
    assert len(outputs["programs_without_organizations"]) == 1
    assert outputs["organization_mapping_review_queue"][0]["issue"] == "no_exact_organization_match"


def test_duplicate_office_name_is_queued_instead_of_assigned_arbitrarily(tmp_path: Path):
    processed = tmp_path / "processed"
    processed.mkdir()
    pd.DataFrame([
        {"external_id": "ORG-ED-OIG", "canonical_name": "Office of Inspector General"},
        {"external_id": "ORG-GSA-OIG", "canonical_name": "Office of Inspector General"},
    ]).to_csv(processed / "organizations.csv", index=False)
    mapped, review = map_organizations([{
        "source_key": "sam_assistance", "source_record_id": "1", "source_name": "Example Grant",
        "office_source_name": "Office of Inspector General",
    }], processed)
    assert mapped[0]["organization_id"] == ""
    assert review[0]["issue"] == "ambiguous_exact_organization_match"
    assert review[0]["candidate_organization_ids"] == "ORG-ED-OIG|ORG-GSA-OIG"
