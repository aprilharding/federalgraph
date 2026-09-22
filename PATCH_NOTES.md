# FederalGraph v0.6.1 hotfix

Fixes the first live GovInfo run.

## What failed in v0.6.0

The extractor downloaded the Government Manual package XML successfully, then tried to discover granules by scraping the package-level `/context` page. GovInfo renders that page's browse tree client-side, so a plain HTTP request can contain the section buttons without the individual granule links. That produced `GovInfo extractor found no granules` and stopped the pipeline before `data/processed` was regenerated.

## What changed

- Granule discovery now uses the official GovInfo packages API first.
- `GOVINFO_API_KEY` is supported when set.
- `DEMO_KEY` is used as the zero-setup fallback.
- If the API is unavailable, FederalGraph attempts to recover granule IDs from the already-downloaded package XML, then falls back to the old context-page method.
- Discovery diagnostics are written to `data/raw/govinfo/<package>/granule_discovery.json`.
- Version bumped to 0.6.1.

## Testing

Install development extras before running tests:

```bash
python -m pip install -e ".[dev]"
pytest
```

The normal pipeline does not require pytest.
