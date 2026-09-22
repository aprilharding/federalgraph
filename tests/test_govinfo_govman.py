from pathlib import Path

from federalgraph.extract.govinfo_govman import (
    discover_granule_ids,
    discover_granule_ids_from_xml,
    granule_ids_from_api_payload,
    parse_detail_html,
)

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo"
PACKAGE = "GOVMAN-2025-12-31"


def test_discover_granule_ids_from_context_html():
    html = (FIXTURES / "context.html").read_text(encoding="utf-8")
    ids = discover_granule_ids(html, PACKAGE)
    assert ids == [
        "GOVMAN-2025-12-31-114",
        "GOVMAN-2025-12-31-206",
        "GOVMAN-2025-12-31-266",
    ]


def test_granule_ids_from_govinfo_api_payload():
    payload = {
        "count": 3,
        "granules": [
            {"granuleId": "GOVMAN-2025-12-31-114"},
            {"granuleId": "GOVMAN-2025-12-31-206"},
            {"granuleId": "GOVMAN-2025-12-31-266"},
        ],
    }
    assert granule_ids_from_api_payload(payload) == [
        "GOVMAN-2025-12-31-114",
        "GOVMAN-2025-12-31-206",
        "GOVMAN-2025-12-31-266",
    ]


def test_granule_ids_from_package_xml_is_a_safe_fallback():
    xml = b'''<root>
      <ref>GOVMAN-2025-12-31-114</ref>
      <ref>GOVMAN-2025-12-31-266</ref>
      <ref>GOVMAN-2025-12-31-114</ref>
    </root>'''
    assert discover_granule_ids_from_xml(xml, PACKAGE) == [
        "GOVMAN-2025-12-31-114",
        "GOVMAN-2025-12-31-266",
    ]


def test_parse_govinfo_detail_preserves_official_name_and_section():
    html = (FIXTURES / "nist_detail.html").read_text(encoding="utf-8")
    row = parse_detail_html(html, PACKAGE, f"{PACKAGE}-266", "2025-12-31")
    assert row["government_organization"] == "National Institute of Standards and Technology"
    assert row["section"] == "Executive Branch/Departments"
    assert row["branch"] == "Executive Branch"
    assert row["section_category"] == "Departments"
    assert row["record_kind"] == "organization"
    assert row["is_entity_candidate"] is True
    assert row["xml_url"].endswith(f"/{PACKAGE}-266.xml")


def test_grouping_heading_is_preserved_but_not_emitted_as_entity_candidate():
    html = (FIXTURES / "group_detail.html").read_text(encoding="utf-8")
    row = parse_detail_html(html, PACKAGE, f"{PACKAGE}-206", "2025-12-31")
    assert row["government_organization"] == "Defense Agencies"
    assert row["record_kind"] == "grouping_heading"
    assert row["is_entity_candidate"] is False
