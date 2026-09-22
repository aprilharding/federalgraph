# FederalGraph v0.6.0

This release turns on the two additional organization sources discussed in RFC-0004 and RFC-0005.

## Added

- Current-edition U.S. Government Manual / GovInfo ingest.
- GovInfo package XML caching and SHA-256 provenance.
- GovInfo granule audit output and grouping-heading filtering.
- Current OPM Federal Workforce Data Employment ingest via the public Parquet API.
- OPM Department / Agency / Subagency source records and code fields.
- `--skip-govinfo` and `--skip-opm` CLI escape hatches.
- `pyarrow` dependency for OPM Parquet files.
- Parser/unit tests for both new sources.

## Naming policy

GovInfo remains authoritative for `canonical_name` after identity resolution. OPM is the first fallback naming authority when a resolved identity is absent from GovInfo.

## Run

```bash
python -m pip install -e .
federalgraph organizations
```

The first run downloads roughly 13 MB of GovInfo XML plus the current OPM employment Parquet file (tens of MB), so it will take longer than v0.5.
