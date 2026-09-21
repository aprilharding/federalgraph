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
    organizations, _, _, _, relationships, _, _ = resolve(rows)
    assert len(organizations) == 2
    assert len(relationships) == 1
