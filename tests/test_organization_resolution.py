from federalgraph.normalize.organizations import normalize_records
from federalgraph.resolve.organizations import resolve, score_pair


def record(source: str, name: str, website: str = "", parent: str = "") -> dict:
    return {
        "source": source,
        "source_record_id": f"{source}:{name}",
        "source_name": name,
        "source_url": "",
        "website": website,
        "description": "",
        "parent_source_name": parent,
        "source_level": "organization",
        "branch": "Executive",
    }


def test_shared_domain_does_not_establish_identity() -> None:
    rows = normalize_records(
        [
            record("USA.gov Agency Index", "Administration for Children and Families", "acf.hhs.gov"),
            record("USA.gov Agency Index", "Office of Child Care", "acf.hhs.gov"),
        ]
    )
    score, reasons = score_pair(rows[0], rows[1])
    assert score < 88
    assert "same_domain_support" not in reasons or score >= 60


def test_exact_cross_source_name_merges() -> None:
    rows = normalize_records(
        [
            record("USA.gov Agency Index", "Federal Trade Commission"),
            record("Federal Register Agencies API", "Federal Trade Commission"),
        ]
    )
    organizations, aliases, sources, *_ = resolve(rows)
    assert len(organizations) == 1
    assert len(sources) == 2
    assert any(row["alias"] == "Federal Trade Commission" for row in aliases)


def test_parenthetical_acronym_variant_merges() -> None:
    rows = normalize_records(
        [
            record("USA.gov Agency Index", "Administration for Children and Families (ACF)"),
            record("Federal Register Agencies API", "Administration for Children and Families"),
        ]
    )
    organizations, aliases, *_ = resolve(rows)
    assert len(organizations) == 1
    assert any(row["alias"] == "ACF" and row["alias_type"] == "source_acronym" for row in aliases)


def test_us_prefix_variant_merges_within_same_directory() -> None:
    rows = normalize_records(
        [
            record("USA.gov Agency Index", "Access Board", "https://www.access-board.gov"),
            record("USA.gov Agency Index", "U.S. Access Board", "https://www.access-board.gov"),
        ]
    )
    organizations, *_ = resolve(rows)
    assert len(organizations) == 1


def test_directory_inversion_merges() -> None:
    rows = normalize_records(
        [
            record("USA.gov Agency Index", "Economic Analysis, Bureau of"),
            record("Federal Register Agencies API", "Bureau of Economic Analysis"),
        ]
    )
    organizations, *_ = resolve(rows)
    assert len(organizations) == 1


def test_department_order_merges() -> None:
    rows = normalize_records(
        [
            record("USA.gov Agency Index", "Agriculture Department (USDA)"),
            record("Federal Register Agencies API", "Department of Agriculture"),
        ]
    )
    organizations, *_ = resolve(rows)
    assert len(organizations) == 1


def test_acronym_alone_cannot_create_strong_match() -> None:
    rows = normalize_records(
        [
            record("USA.gov Agency Index", "Central Command (CENTCOM)"),
            record("Federal Register Agencies API", "Commodity Credit Corporation"),
        ]
    )
    score, reasons = score_pair(rows[0], rows[1])
    assert score < 88
    assert "same_acronym_support" not in reasons


def test_parent_relationship_is_not_identity_merge() -> None:
    rows = normalize_records(
        [
            record("Current Federal Program Inventory", "Department of Health and Human Services"),
            record(
                "Current Federal Program Inventory",
                "Administration for Children and Families",
                parent="Department of Health and Human Services",
            ),
        ]
    )
    organizations, _, _, _, relationships, _, _, _ = resolve(rows)
    assert len(organizations) == 2
    assert len(relationships) == 1


def test_human_merge_override_persists_and_sets_preferred_name() -> None:
    rows = normalize_records(
        [
            record("Federal Register Agencies API", "Postal Rate Commission"),
            record("USA.gov Agency Index", "Postal Regulatory Commission", "https://www.prc.gov"),
        ]
    )
    overrides = [
        {
            "left_name": "Postal Rate Commission",
            "right_name": "Postal Regulatory Commission",
            "decision": "historical_alias",
            "preferred_name": "Postal Regulatory Commission",
        }
    ]
    organizations, aliases, sources, candidates, _, review, _, _ = resolve(
        rows, identity_overrides=overrides
    )
    assert len(organizations) == 1
    assert organizations[0]["canonical_name"] == "Postal Regulatory Commission"
    assert organizations[0]["resolution_status"] == "Reviewed merge"
    assert len(review) == 0
    assert any(row["decision"] == "manual_historical_alias" for row in candidates)
    assert {row["canonical_external_id"] for row in sources} == {
        organizations[0]["external_id"]
    }
    assert {row["alias"] for row in aliases} >= {
        "Postal Rate Commission",
        "Postal Regulatory Commission",
    }


def test_keep_separate_override_suppresses_repeat_review() -> None:
    rows = normalize_records(
        [
            record("USA.gov Agency Index", "Southeastern Power Administration"),
            record("Federal Register Agencies API", "Southwestern Power Administration"),
        ]
    )
    overrides = [
        {
            "left_name": "Southeastern Power Administration",
            "right_name": "Southwestern Power Administration",
            "decision": "keep_separate",
            "preferred_name": "",
        }
    ]
    organizations, _, _, candidates, _, review, _, _ = resolve(
        rows, identity_overrides=overrides
    )
    assert len(organizations) == 2
    assert len(review) == 0
    assert any(row["decision"] == "manual_keep_separate" for row in candidates)
    assert {row["resolution_status"] for row in organizations} == {"Reviewed separate"}


def test_govinfo_name_is_authoritative_over_other_sources() -> None:
    rows = normalize_records(
        [
            record("USA.gov Agency Index", "Treasury Department"),
            record("Federal Register Agencies API", "Department of the Treasury"),
            record("U.S. Government Manual (GovInfo)", "Department of the Treasury"),
        ]
    )
    organizations, _, _, _, _, _, name_review, _ = resolve(rows)
    assert len(organizations) == 1
    org = organizations[0]
    assert org["canonical_name"] == "Department of the Treasury"
    assert org["canonical_name_authority_tier"] == "govinfo_govman"
    assert org["canonical_name_status"] == "GovInfo authoritative"
    assert org["canonical_name_source"].startswith("U.S. Government Manual")
    assert name_review == []


def test_human_preferred_name_cannot_override_govinfo() -> None:
    rows = normalize_records(
        [
            record("Federal Register Agencies API", "Postal Rate Commission"),
            record("USA.gov Agency Index", "Postal Regulatory Commission"),
            record("U.S. Government Manual (GovInfo)", "Postal Regulatory Commission"),
        ]
    )
    overrides = [
        {
            "left_name": "Postal Rate Commission",
            "right_name": "Postal Regulatory Commission",
            "decision": "historical_alias",
            "preferred_name": "Postal Rate Commission",
        }
    ]
    organizations, *_ = resolve(rows, identity_overrides=overrides)
    assert len(organizations) == 1
    assert organizations[0]["canonical_name"] == "Postal Regulatory Commission"
    assert organizations[0]["canonical_name_authority_tier"] == "govinfo_govman"


def test_non_govinfo_name_disagreement_enters_name_review_queue() -> None:
    rows = normalize_records(
        [
            record("USA.gov Agency Index", "Example Service"),
            record("OPM Federal Workforce Data", "Example Administration"),
        ]
    )
    overrides = [
        {
            "left_name": "Example Service",
            "right_name": "Example Administration",
            "decision": "merge",
            "preferred_name": "",
        }
    ]
    organizations, _, _, _, _, _, name_review, _ = resolve(rows, identity_overrides=overrides)
    assert len(organizations) == 1
    org = organizations[0]
    assert org["canonical_name"] == "Example Administration"
    assert org["canonical_name_authority_tier"] == "opm_fwd"
    assert org["canonical_name_status"] == "Fallback provisional - naming review"
    assert len(name_review) == 1


def test_reviewed_preferred_name_wins_when_govinfo_is_absent() -> None:
    rows = normalize_records(
        [
            record("Federal Register Agencies API", "Old Example Commission"),
            record("USA.gov Agency Index", "Example Commission"),
        ]
    )
    overrides = [
        {
            "left_name": "Old Example Commission",
            "right_name": "Example Commission",
            "decision": "historical_alias",
            "preferred_name": "Example Commission",
        }
    ]
    organizations, _, _, _, _, _, name_review, _ = resolve(rows, identity_overrides=overrides)
    assert len(organizations) == 1
    assert organizations[0]["canonical_name"] == "Example Commission"
    assert organizations[0]["canonical_name_authority_tier"] == "human_review"
    assert name_review == []


def opm_record(
    level: str,
    name: str,
    department_code: str,
    agency_code: str = "",
    subagency_code: str = "",
    parent: str = "",
) -> dict:
    row = record("OPM Federal Workforce Data", name, parent=parent)
    row.update(
        {
            "source_record_id": (
                f"department:{department_code}"
                if level == "department"
                else f"agency:{agency_code}"
                if level == "agency"
                else f"subagency:{subagency_code}"
            ),
            "source_level": level,
            "opm_department_code": department_code,
            "opm_agency_code": agency_code,
            "opm_subagency_code": subagency_code,
        }
    )
    return row


def test_opm_standalone_department_agency_and_default_subagency_are_one_identity() -> None:
    rows = normalize_records(
        [
            opm_record("department", "FEDERAL MEDIATION AND CONCILIATION SERVICE", "FM"),
            opm_record(
                "agency",
                "FED MEDIATION AND CONCILIATION SERVICE",
                "FM",
                agency_code="FM",
                parent="FEDERAL MEDIATION AND CONCILIATION SERVICE",
            ),
            opm_record(
                "subagency",
                "FEDERAL MEDIATION AND CONCILIATION SERVICE",
                "FM",
                agency_code="FM",
                subagency_code="FM00",
                parent="FED MEDIATION AND CONCILIATION SERVICE",
            ),
        ]
    )
    organizations, _, _, _, relationships, review, _, _ = resolve(rows)
    assert len(organizations) == 1
    assert relationships == []
    assert review == []


def test_opm_component_agency_does_not_merge_into_parent_department() -> None:
    rows = normalize_records(
        [
            opm_record("department", "DEPARTMENT OF DEFENSE", "DOD"),
            opm_record(
                "agency",
                "DEPARTMENT OF THE AIR FORCE",
                "DOD",
                agency_code="AF",
                parent="DEPARTMENT OF DEFENSE",
            ),
        ]
    )
    organizations, _, _, _, relationships, review, _, _ = resolve(rows)
    assert len(organizations) == 2
    assert len(relationships) == 1
    assert review == []


def test_distinct_opm_subagencies_do_not_enter_fuzzy_review_queue() -> None:
    rows = normalize_records(
        [
            opm_record(
                "subagency",
                "U.S. ARMY NORTH",
                "DOD",
                agency_code="AR",
                subagency_code="AR5A",
                parent="DEPARTMENT OF THE ARMY",
            ),
            opm_record(
                "subagency",
                "U.S. ARMY SOUTH",
                "DOD",
                agency_code="AR",
                subagency_code="ARSO",
                parent="DEPARTMENT OF THE ARMY",
            ),
        ]
    )
    organizations, _, _, _, _, review, _, _ = resolve(rows)
    assert len(organizations) == 2
    assert review == []
