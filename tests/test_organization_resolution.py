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
    assert score < 96
    assert "same_domain_support" in reasons


def test_exact_cross_source_name_merges() -> None:
    rows = normalize_records(
        [
            record("USA.gov Agency Index", "Federal Trade Commission"),
            record("Federal Register Agencies API", "Federal Trade Commission"),
        ]
    )
    organizations, sources, *_ = resolve(rows)
    assert len(organizations) == 1
    assert len(sources) == 2


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
    organizations, _, _, relationships, _, _ = resolve(rows)
    assert len(organizations) == 2
    assert len(relationships) == 1
