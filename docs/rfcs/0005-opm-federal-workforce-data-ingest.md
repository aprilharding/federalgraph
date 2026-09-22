# RFC-0005: OPM Federal Workforce Data organization ingest

Status: implemented in v0.6.0

## Decision

FederalGraph ingests the current OPM Federal Workforce Data Employment file through OPM's public API. The API requires no authentication. The extractor downloads the current Parquet file, then emits unique Department, Agency, and Subagency organization records with OPM codes and parent-name evidence.

OPM is a source of official workforce organizational codes and hierarchy evidence. It is not the canonical naming authority when the same entity appears in the U.S. Government Manual.

## API

List endpoint:

`https://data.opm.gov/api/v1/files/employment?current=true`

The extractor selects the latest current file and downloads:

`/api/v1/files/employment/{year}/{month}/{version}/download`

Raw artifacts are saved under `data/raw/opm_fwd/`.

## Data model

Emitted source records include:

- `source`: `OPM Federal Workforce Data`
- `source_record_id`: stable level/code pair such as `subagency:TR93`
- `source_name`
- `source_level`: department, agency, or subagency
- `parent_source_name`
- `source_as_of`
- `opm_department_code`
- `opm_agency_code`
- `opm_subagency_code`

The synthetic FWD grouping `Non-CFO Act Agency` is not emitted as an organization.

## Schema tolerance

The extractor supports both the current FWD schema and the older FedScope-style organization fields. In particular it recognizes `agency`, `agency_code`, `agency_subelement`, and `agency_subelement_code`, and also uses Department fields when present.

## Naming authority

After identity resolution:

1. GovInfo U.S. Government Manual name
2. OPM FWD name
3. Federal Register name
4. USA.gov name

A non-GovInfo disagreement remains reviewable.

## Data quality

OPM's employment data is workforce-reporting data, not a complete legal organization registry. Missing workforce submissions must never delete an existing FederalGraph identity. OPM records add evidence and hierarchy candidates only.
