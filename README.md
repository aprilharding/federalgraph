# FederalGraph

FederalGraph is an open-source pipeline for compiling authoritative federal data sources into a unified, traceable knowledge graph.

The project begins with a canonical organization registry. Later layers will add programs, authorities, committees, congressional intent, financial accounts, objectives, key results, indicators, and oversight evidence.

## Design principles

1. **Sources are evidence, not the canonical model.** The same organization may appear differently across official sources.
2. **Identity and hierarchy are separate questions.** Sharing a parent or website domain does not make two named organizations the same entity.
3. **Automated decisions must be inspectable.** The pipeline emits candidates, reasons, scores, and review queues rather than hiding uncertain matches.
4. **Financial completeness and governance completeness are distinct.** A program can be financially mapped without being traceable to congressional intent, and vice versa.
5. **Generated outputs are reproducible.** Raw source snapshots and transformation outputs are separated from maintained source code.

## Current build: organization registry

The organization command currently combines evidence from:

- the USA.gov agency index;
- the Federal Register Agencies API; and
- an optional program-inventory CSV containing `Department` and `Agency` columns.

It produces:

- `organizations.csv`
- `organization_sources.csv`
- `organization_match_candidates.csv`
- `organization_relationships.csv`
- `organization_review_queue.csv`
- `organization_status_evidence.csv`
- `wordpress_organizations.csv`
- `pipeline_summary.json`

All output is provisional until review. Presence in an official directory is evidence of status, not proof that an entity is currently active or legally distinct.

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

## Build organizations

From live USA.gov and Federal Register sources:

```bash
federalgraph organizations
```

Add organization evidence from a local FPI-derived file:

```bash
federalgraph organizations --fpi-csv data/raw/fpi_program_orgs.csv
```

Reuse a prior extraction while refining resolution logic:

```bash
federalgraph organizations --source-csv data/raw/organization_sources.csv
```

Outputs are written to `data/processed/`. Raw downloaded source snapshots are written to `data/raw/`.

## Repository structure

```text
federalgraph/          Python package
  extract/             Source-specific extraction
  normalize/           Source-neutral normalization
  resolve/             Identity and hierarchy resolution
  export/              CSV and WordPress outputs
config/                Versioned source and threshold configuration
data/raw/               Downloaded or supplied source evidence
data/cache/             Reusable download cache
data/processed/         Generated graph outputs
tests/                  Automated tests
```

## Status

FederalGraph is under active development. The organization layer is the first working graph layer; its initial purpose is to make false merges, uncertain identities, and inferred hierarchy visible for review before other federal entities are attached to it.
