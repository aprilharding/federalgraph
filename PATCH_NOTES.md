# FederalGraph v0.8 — Program identity + statutory purpose foundation

This patch adds the first real program-ingest pipeline while deliberately keeping money out of scope.

## Working sources in this increment

- SAM.gov Assistance Listings public current bulk extract (API fallback available with `SAM_API_KEY`)
- SAM functional-code evidence emitted separately as `program_functions.csv`
- Treasury FY2027 tax-expenditure workbook (identity only)
- archived Performance.gov FPI parser, plus `--performance-csv` fallback for a preserved reference table
- U.S. Code USLM XML lookup for exact U.S.C. citations supplied by program sources
- repeatable `--supplemental-csv` input for official Budget/CBJ/AFR/etc. candidate extracts while those document-specific extractors are built

## Outputs

`programs.csv`, `program_sources.csv`, `program_aliases.csv`, `program_authorities.csv`, `program_functions.csv`, `program_organization_relationships.csv`, `program_match_candidates.csv`, `organization_mapping_review_queue.csv`, `programs_without_organizations.csv`, `organizations_without_programs.csv`, and `program_pipeline_summary.json`.

## Important behavior

- Program identity is source-neutral; SAM is not treated as the whole universe.
- Statutory authority/purpose evidence is gathered during identity resolution.
- Fuzzy matching is review-only.
- Unresolved program → organization mappings are preserved as gaps instead of being forced upward.
- Financial amounts are intentionally ignored.

## Run

```bash
python -m pip install -e '.[dev]'
pytest
federalgraph programs
```

For a quick SAM smoke test:

```bash
federalgraph programs --max-sam-pages 1 --skip-treasury --skip-performance --skip-uscode
```
