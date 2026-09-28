from federalgraph.extract.sam_assistance import records_from_payload


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
    from federalgraph.extract.sam_assistance import records_from_csv

    text = """Program Number,Program Title,Federal Agency,Objectives,Authorization,Functional Index\n10.999,Example Program,Farm Service Agency,Help producers,7 U.S.C. 1234,Agriculture\n"""
    programs, authorities, functions = records_from_csv(text, "https://example.test/current.csv")
    assert programs[0]["source_record_id"] == "10.999"
    assert programs[0]["agency_source_name"] == "Farm Service Agency"
    assert authorities[0]["usc_title"] == "7"
    assert authorities[0]["usc_section"] == "1234"
    assert functions[0]["function_name"] == "Agriculture"
