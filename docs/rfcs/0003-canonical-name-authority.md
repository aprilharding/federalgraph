# RFC-0003: Canonical Organization Name Authority

## Status
Accepted for FederalGraph v0.5.

## Decision
Organization **identity** and organization **naming** are separate resolution problems.

Once source records have been resolved to one canonical organization identity, FederalGraph
selects the display/canonical name using a field-specific authority hierarchy:

1. **U.S. Government Manual / GovInfo** — authoritative canonical name whenever the entity
   appears in the Manual.
2. **Human-reviewed preferred name** — only when the entity does not appear in the Manual.
3. **OPM Federal Workforce Data / EHRI** — first provisional fallback.
4. **Federal Register Agencies API** — second provisional fallback.
5. **USA.gov Agency Index** — third provisional fallback.
6. Other sources — last-resort provisional fallback.

All non-selected source names remain aliases with provenance.

## Why
The project should not repeatedly debate whether a public-facing abbreviation, regulatory label,
workforce reporting label, or directory inversion is the "real" name of an entity. The U.S.
Government Manual is the official handbook of the Federal Government and therefore settles the
canonical display name for organizations it covers.

The other sources remain authoritative for other fields:

- OPM: workforce organization codes and employment-reporting hierarchy.
- Federal Register: regulatory-agency identifiers and regulatory participation.
- USA.gov: public-facing names, websites, and current-directory evidence.

Source authority is therefore **field-specific**, not a universal ranking.

## Naming review
If an identity has no Government Manual record and materially different names remain across the
fallback sources, FederalGraph chooses a deterministic fallback so the build is reproducible but
also emits the entity to `organization_name_review_queue.csv`.

Fuzzy similarity never decides a canonical name.

## GovInfo editions
When multiple Government Manual editions attest the same resolved identity, the most recent dated
GovInfo record is authoritative. If multiple materially different names occur for the same latest
edition, the entity is flagged for naming review rather than silently choosing between them.

## Provenance fields
`organizations.csv` carries:

- `canonical_name`
- `canonical_name_source`
- `canonical_name_source_record_id`
- `canonical_name_as_of`
- `canonical_name_authority_tier`
- `canonical_name_status`

This makes the selected name explainable and auditable.

## Scope
GovInfo absence does **not** mean an entity is invalid or non-federal. It means only that the U.S.
Government Manual cannot settle that entity's canonical name. Identity, status, hierarchy, and
organization-vs-program scope remain separate layers.
