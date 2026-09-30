# FederalGraph

FederalGraph is an open-source pipeline for compiling authoritative federal data sources into a unified, traceable knowledge graph.

The project begins with canonical organizations and programs, then extends to authorities, committees, congressional intent, financial accounts, objectives, key results, indicators, and oversight evidence.

## Design principles

1. **Sources are evidence, not the canonical model.** The same organization or program may appear differently across official sources.
2. **Identity and hierarchy are separate questions.** Sharing a parent, name fragment, or website domain does not make two records the same entity.
3. **Automated decisions must be inspectable.** The pipeline emits candidates, reasons, scores, and review queues rather than hiding uncertain matches.
4. **Authority and purpose are identity evidence.** Program reconciliation uses administering organization, authorizing authority, and statutory/agency-stated purpose alongside names.
5. **Financial completeness is a later layer.** Program identity does not depend on obligations, outlays, TAS mappings, or other dollar fields.
6. **Generated outputs are reproducible.** Raw source snapshots and transformation outputs are separated from maintained source code.

## Organization registry

The organization command combines evidence from:

- U.S. Government Manual / GovInfo — canonical naming authority when present;
- OPM Federal Workforce Data / FedScope organizational hierarchy;
- USA.gov agency index; and
- Federal Register Agencies API.

Reviewed statutory organizations missing from those directories are included as
cited source assertions in `config/statutory_organization_sources.csv`. They do
not override the Government Manual's naming authority when a Manual record exists.

```bash
federalgraph organizations
```

To add new reviewed statutory assertions to an existing local build without
downloading the directory sources again, reuse the saved source assertions:

```bash
federalgraph organizations --source-csv data/processed/organization_sources.csv
```

The statutory source rows are added once, even when they are already present in
the saved source CSV. Rebuild programs afterward to refresh organization links.

Outputs include canonical identities, aliases, source assertions, hierarchy candidates, status evidence, and review queues in `data/processed/`.

## Program registry (v0.8)

The program command deliberately does **not** assume the official OMB Federal Program Inventory is complete. It compiles program assertions from multiple official sources and resolves them into canonical program identities.

Primary program sources in this increment:

- SAM.gov Assistance Listings;
- SAM functional classifications / Functional Index evidence;
- Treasury tax-expenditure identities.

Additional discovery/evidence in this increment:

- archived Performance.gov Federal Program Inventory material;
- exact U.S. Code citations and statutory text for authority/purpose evidence;
- repeatable supplemental official-source CSVs for Budget Appendix, Congressional Budget Justification, AFR/PAR, statutory, regulatory, or appropriations candidates while source-specific document extractors are added.

USAspending and all fiscal amounts are intentionally deferred.

### SAM source access

The program build prefers SAM.gov's public current bulk Assistance Listings extract, so a SAM API key is **not normally required**. `SAM_API_KEY` is only used if the bulk extract fails or when `--max-sam-pages` intentionally exercises the API.

### Build programs

Run the whole configured program build:

```bash
federalgraph programs
```

Smoke-test one page of SAM without the other live sources:

```bash
federalgraph programs --max-sam-pages 1 --skip-treasury --skip-performance --skip-uscode
```

Use a preserved Performance.gov reference-table CSV if archive HTML changes:

```bash
federalgraph programs --performance-csv path/to/performance_fpi.csv
```

Add another official candidate source using a normalized CSV:

```bash
federalgraph programs --supplemental-csv path/to/cbj_program_candidates.csv
```

The supplemental CSV needs a `Program` / `Program Name` column and can optionally include `Department`, `Agency`, `Office`, `Purpose` / `Description`, `Program Type`, `Statute` / `Authority`, `Source`, and `Source URL`.

### Program outputs

The program build writes:

- `programs.csv`
- `program_sources.csv`
- `program_aliases.csv`
- `program_authorities.csv`
- `program_functions.csv`
- `program_organization_relationships.csv`
- `program_match_candidates.csv`
- `organization_mapping_review_queue.csv`
- `programs_without_organizations.csv`
- `organizations_without_programs.csv`
- `program_pipeline_summary.json`

The two gap reports are intentional: FederalGraph preserves programs that do not resolve to an organization and organizations for which the current program sources reveal no program.

## Agency report discovery

When the Performance.gov archive is unavailable, discover performance evidence
on agency websites using the USA.gov assertions already saved in
`data/processed/organization_sources.csv`. Run the organization build first if
that file does not exist. Only USA.gov rows seed this command; coverage of the
organization registry is therefore limited to agencies represented in that index.

Try five targets, then search every saved USA.gov website and save documents:

```bash
federalgraph reports --max-agencies 5
federalgraph reports --download-reports
```

Each search follows report, budget, strategic-plan, and related navigation links
on the agency site, prioritizing FY2024 and then newer named years. Defaults are
40 pages and three link levels per target, with four workers. Change the bounds
with `--max-pages`, `--max-depth`, and `--workers`; use `--source-csv` for another
organization source export. Robots exclusions, inaccessible sites, and searches
that found no candidate remain visible in the coverage export.

Outputs in `data/processed/`:

- `agency_report_sources.csv`: organization IDs, candidate titles/types, year
  candidates, report URLs, discovery pages, and optional snapshot hashes/paths.
- `agency_report_coverage.csv`: a result for each target, page counts, search-limit
  flags, and errors.
- `agency_report_summary.json`: target, candidate, and download counts; identifies
  limited smoke runs.

Raw HTML evidence and optional PDF/HTML documents go in
`data/raw/agency_reports/`. Report links and filename years are **unverified
candidates**: a landing page may cover several reports, and a component's link
may lead to its parent's report. The associated organization identifies the
website source, not a verified issuing organization. No candidate in a bounded
search is not proof of absence. This command does not extract program identities
or change the existing program exports; document extraction is a subsequent step.

### Run report discovery on GitHub

The manual **Discover agency reports** workflow runs without downloading reports
onto your computer. After this workflow is merged to the default branch:

1. Open the repository's **Actions** tab and choose **Discover agency reports**.
2. Click **Run workflow**. Keep website targets at `5` for a test, or set `0` to
   search every saved USA.gov target. Choose whether to save report documents.
3. Open the completed run. Under **Artifacts**, `federalgraph-tables-*` contains
   the organization outputs and report CSVs/summaries; `federalgraph-evidence-*`
   contains raw website evidence and downloaded reports.

The runner starts from a clean checkout and rebuilds organization sources using
all configured directory sources before discovering reports. It does not reuse
or upload your Mac's CSVs, so changing upstream directories can change results.
An optional repository secret `GOVINFO_API_KEY` is used by the organization build;
the configured public fallback applies when no key is supplied.

Artifacts request 90-day retention, subject to repository settings; this is not
permanent archival storage. They remain online until downloaded or expired.
The workflow attempts to upload available evidence even if a build fails, and
allows up to 330 minutes. A timeout or failed run is not a completed full search.
Large crawls consume GitHub's runner and artifact storage allowances. No
additional reports are saved in your local checkout unless you download them.

## Install

FederalGraph supports Python 3.9 or later.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Check the installation

```bash
federalgraph doctor
federalgraph sources
pytest
ruff check .
```

## Repository structure

```text
federalgraph/          Python package
  extract/             Source-specific extraction
  normalize/           Source-neutral normalization
  resolve/             Identity, hierarchy, and program resolution
  export/              CSV and WordPress outputs
config/                Versioned source and threshold configuration
data/raw/              Downloaded or supplied source evidence
data/cache/            Reusable download cache
data/processed/        Generated graph outputs
docs/rfcs/             Methodology and architecture decisions
tests/                 Automated tests
```

## Methodology status

The program framework is designed for the broader FederalGraph methodology: Performance.gov/current performance material, Budget Appendix/CBJs, AFRs/PARs, U.S. Code and enacted law, CFR/eCFR, appropriations, and oversight material can all emit the same neutral source-record schema. Source-specific automation for the document-heavy secondary layers will be added incrementally without changing canonical program IDs or the evidence model.
