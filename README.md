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

```bash
federalgraph organizations
```

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
