# RFC-0004: GovInfo U.S. Government Manual ingest

Status: implemented in v0.6.0

## Decision

FederalGraph ingests the configured current edition of the U.S. Government Manual from GovInfo. The full package XML is downloaded and hashed as the immutable edition artifact. GovInfo granule metadata supplies the Government Organization name, section, branch, publication date, granule ID, details URL, and direct granule XML URL.

GovInfo is authoritative for `canonical_name` after identity resolution. It is not, by itself, authority that two records from different sources are the same identity.

## Current edition

The source is pinned in `config/sources.json` to:

- Package: `GOVMAN-2025-12-31`
- Publication date: `2025-12-31`
- Package XML: `https://www.govinfo.gov/content/pkg/GOVMAN-2025-12-31/xml/GOVMAN-2025-12-31.xml`

The build does not silently roll forward to a newer edition. Updating the edition is an explicit configuration change.

## Raw artifacts

Each run stores GovInfo material under:

`data/raw/govinfo/<package_id>/`

including the package XML, package context HTML, granule detail pages, a granule audit CSV, and any per-granule failures. The package XML SHA-256 is attached to emitted source records.

## Entity handling

Every Government Manual granule is retained in the audit file. Known structural headings such as `Bureaus`, `Offices / Boards`, `Defense Agencies`, `Joint Service Schools`, and `Federally Aided Corporations` are classified as grouping headings and are not emitted as canonical entity candidates.

All source names remain preserved as evidence and aliases. GovInfo names are never beautified or normalized for display; normalization is used only for matching.

## Source identifiers

- `source`: `U.S. Government Manual / GovInfo`
- `source_record_id`: GovInfo granule ID
- `govinfo_package_id`: package ID
- `govinfo_granule_id`: granule ID
- `govinfo_xml_url`: direct granule XML URL
- `source_as_of`: edition publication date

## Hierarchy

The ingest records GovInfo branch and section metadata. It does not infer parent/component relationships from document order in this version. OPM and later structural sources may supply hierarchy evidence without changing identity.
