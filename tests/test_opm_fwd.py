import pandas as pd

from federalgraph.extract.opm_fwd import discover_columns, records_from_dataframe


def test_opm_current_schema_builds_department_agency_and_subagency_records():
    frame = pd.DataFrame(
        [
            {
                "department": "Department of Agriculture",
                "department_code": "AG",
                "agency": "Department of Agriculture",
                "agency_code": "AG",
                "agency_subelement": "AG02-Agricultural Marketing Service",
                "agency_subelement_code": "AG02",
            }
        ]
    )
    records = records_from_dataframe(frame, "07/31/2026", "https://example.test/employment.parquet")
    names = {row["source_name"] for row in records}
    assert "Department of Agriculture" in names
    assert "Agricultural Marketing Service" in names
    sub = next(row for row in records if row["source_level"] == "subagency")
    assert sub["source_record_id"] == "subagency:AG02"
    assert sub["parent_source_name"] == "Department of Agriculture"
    assert sub["opm_subagency_code"] == "AG02"
    assert sub["source_as_of"] == "07/31/2026"


def test_opm_legacy_schema_without_department_still_yields_entities():
    frame = pd.DataFrame(
        [
            {
                "agency": "DEPARTMENT OF THE TREASURY",
                "agency_code": "TR",
                "agency_subelement": "INTERNAL REVENUE SERVICE",
                "agency_subelement_code": "TR93",
            }
        ]
    )
    cols = discover_columns(frame)
    assert cols["department"] == ""
    records = records_from_dataframe(frame, "2026-07", "https://example.test/file")
    names = {row["source_name"] for row in records}
    assert "DEPARTMENT OF THE TREASURY" in names
    assert "INTERNAL REVENUE SERVICE" in names


def test_non_cfo_act_department_is_not_created_as_a_fake_entity():
    frame = pd.DataFrame(
        [
            {
                "department": "Non-CFO Act Agency",
                "agency": "Peace Corps",
                "agency_subelement": "PU00-Peace Corps",
                "agency_subelement_code": "PU00",
            }
        ]
    )
    records = records_from_dataframe(frame, "2026-07", "https://example.test/file")
    names = {row["source_name"] for row in records}
    assert "Non-CFO Act Agency" not in names
    assert "Peace Corps" in names
