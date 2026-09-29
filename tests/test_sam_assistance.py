import csv

import pytest

from federalgraph.export.program_csv import export_programs
from federalgraph.extract.sam_assistance import records_from_csv, records_from_payload
from federalgraph.resolve.programs import resolve


def test_sam_payload_emits_program_authority_and_function_rows():
    payload = {
        "assistanceListingsData": [
            {
                "status": "Active",
                "assistanceListingId": "10.123",
                "title": "Example Rural Program",
                "popularShortName": "ERP",
                "federalOrganization": {
                    "department": "Department of Agriculture",
                    "departmentCode": "1200",
                    "agency": "Farm Service Agency",
                    "agencyCode": "12D2",
                },
                "overview": {
                    "objective": "To help eligible rural producers.",
                    "assistanceListingDescription": "An example assistance program.",
                    "functionalCodes": [{"code": "01", "name": "Agriculture"}],
                },
                "authorizations": {
                    "list": [
                        {
                            "USC": {"title": "7", "section": "1234", "description": ""},
                            "publicLaw": {"congressCode": "118", "number": "1"},
                            "act": {"description": "Example Act"},
                        }
                    ]
                },
            }
        ]
    }
    programs, authorities, functions = records_from_payload(payload, "https://api.sam.gov/test")
    assert programs[0]["source_record_id"] == "10.123"
    assert programs[0]["agency_stated_purpose"] == "To help eligible rural producers."
    assert authorities[0]["usc_title"] == "7"
    assert authorities[0]["usc_section"] == "1234"
    assert "7 U.S.C. 1234" in authorities[0]["authority_citation"]
    assert functions == [
        {
            "source_key": "sam_functional_index",
            "program_source_record_id": "10.123",
            "function_code": "01",
            "function_name": "Agriculture",
        }
    ]


def test_sam_bulk_csv_parser_handles_common_export_columns():
    text = """Program Number,Program Title,Federal Agency,Objectives,Authorization,Functional Index\n10.999,Example Program,Farm Service Agency,Help producers,7 U.S.C. 1234,Agriculture\n"""
    programs, authorities, functions = records_from_csv(text, "https://example.test/current.csv")
    assert programs[0]["source_record_id"] == "10.999"
    assert programs[0]["agency_source_name"] == "Farm Service Agency"
    assert authorities[0]["usc_title"] == "7"
    assert authorities[0]["usc_section"] == "1234"
    assert functions[0]["function_name"] == "Agriculture"


def test_sam_bulk_csv_parser_handles_current_numbered_headers_and_hierarchy():
    text = '''Program Title,Program Number,Popular Name (020),Federal Agency (030),Authorization (040),Objectives (050),Published Date,Parent Shortname,URL\n"Agricultural Research Basic and Applied Research",10.001,,"AGRICULTURAL RESEARCH SERVICE, AGRICULTURE, DEPARTMENT OF",7 U.S.C. 427,Support agricultural research,2026-01-01,USDA,https://sam.gov/example\n'''

    programs, authorities, functions = records_from_csv(text, "https://example.test/current.csv")

    assert len(programs) == 1
    assert programs[0]["source_record_id"] == "10.001"
    assert programs[0]["department_source_name"] == "Department of Agriculture"
    assert programs[0]["agency_source_name"] == "Agricultural Research Service"
    assert programs[0]["federal_agency_raw"] == (
        "AGRICULTURAL RESEARCH SERVICE, AGRICULTURE, DEPARTMENT OF"
    )
    assert programs[0]["agency_stated_purpose"] == "Support agricultural research"
    assert programs[0]["source_date"] == "2026-01-01"
    assert programs[0]["source_url"] == "https://sam.gov/example"
    assert programs[0]["parent_shortname"] == "USDA"
    assert authorities[0]["usc_title"] == "7"
    assert authorities[0]["usc_section"] == "427"
    assert functions == []


@pytest.mark.parametrize(
    ("raw", "department", "agency"),
    [
        (
            "Bureau Of Reclamation, Interior, Department Of The",
            "Department of the Interior",
            "Bureau Of Reclamation",
        ),
        (
            "Environmental Protection Agency, Environmental Protection Agency",
            "",
            "Environmental Protection Agency",
        ),
        ("NASA, NASA", "", "NASA"),
        (
            "Washington Headquarters Services (Whs), Dept Of Defense",
            "Department of Defense",
            "Washington Headquarters Services",
        ),
        (
            "Dept Of The Army, Dept Of Defense",
            "Department of Defense",
            "Department of the Army",
        ),
        (
            "Defense Health Agency (Dha), Dept Of Defense",
            "Department of Defense",
            "Defense Health Agency",
        ),
        (
            "Natural Resources Revenue (00024), Interior, Department Of The",
            "Department of the Interior",
            "Natural Resources Revenue",
        ),
        (
            "EXPORT-IMPORT BANK OF THE U.S., EXPORT-IMPORT BANK OF THE US",
            "",
            "Export-Import Bank Of The U.S.",
        ),
        (
            "FEDERAL FINANCIAL INSTITUTIONS EXAMINATION COUNCIL APPRAISAL SUBCOMMITTEE, "
            "FEDERAL FINANCIAL INSTITUTIONS EXAMINATION COUNCIL APPRAISAL SUBCOMMITTEE",
            "",
            "Appraisal Subcommittee of the Federal Financial Institutions Examination Council",
        ),
        (
            "THE INSTITUTE OF MUSEUM AND LIBRARY SERVICES, "
            "THE INSTITUTE OF MUSEUM AND LIBRARY SERVICES",
            "",
            "Institute Of Museum And Library Services",
        ),
        (
            "BARRY GOLDWATER SCHOLARSHIP AND EXCELLENCE IN EDUCATION FUND, "
            "BARRY GOLDWATER SCHOLARSHIP AND EXCELLENCE IN EDUCATION FUND",
            "",
            "Barry Goldwater Scholarship and Excellence in Education Foundation",
        ),
        (
            "MORRIS K. UDALL SCHOLARSHIP AND EXCELLENCE IN NATIONAL ENVIRONMENTAL POLICY "
            "FOUNDATION, MORRIS K UDALL SCHOLARSHIP AND EXCELLENCE IN NATIONAL "
            "ENVIRONMENTAL POLICY FOUNDATION",
            "",
            "Morris K. Udall and Stewart L. Udall Foundation",
        ),
        (
            "JAPAN-U.S. FRIENDSHIP COMMISSION, JAPAN-US FRIENDSHIP COMMISSION",
            "",
            "Japan-U.S. Friendship Commission",
        ),
        (
            "UNITED STATES AGENCY FOR GLOBAL MEDIA, BBG, "
            "UNITED STATES AGENCY FOR GLOBAL MEDIA, BBG",
            "",
            "United States Agency For Global Media",
        ),
        (
            "SOUTHEAST CRESCENT REGIONAL COMMISSION, SOUTHEAST CRESCENT REGIONAL COMMISSION",
            "",
            "Southeast Crescent Regional Commission",
        ),
    ],
)
def test_sam_bulk_csv_parses_structured_agencies_and_preserves_raw(raw, department, agency):
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Program Title", "Program Number", "Federal Agency (030)"])
    writer.writerow(["Example", "10.001", raw])

    programs, _, _ = records_from_csv(output.getvalue(), "https://example.test/current.csv")

    assert programs[0]["federal_agency_raw"] == raw
    assert programs[0]["department_source_name"] == department
    assert programs[0]["agency_source_name"] == agency


def test_program_sources_csv_retains_original_sam_organization(tmp_path):
    raw = "Defense Health Agency (Dha), Dept Of Defense"
    text = (
        'Program Title,Program Number,Federal Agency (030)\n'
        f'Example,10.001,"{raw}"\n'
    )
    programs, authorities, functions = records_from_csv(text, "https://example.test/current.csv")
    outputs = resolve(programs, authorities, functions, tmp_path)
    export_programs(tmp_path, outputs, {})

    with (tmp_path / "program_sources.csv").open(newline="", encoding="utf-8") as file:
        row = next(csv.DictReader(file))
    assert row["federal_agency_raw"] == raw
    assert row["department_source_name"] == "Department of Defense"
    assert row["agency_source_name"] == "Defense Health Agency"
