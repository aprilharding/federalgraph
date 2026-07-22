# FederalGraph

FederalGraph compiles authoritative public sources into a canonical, traceable model of the federal government.

The long-term graph connects:

`Congressional intent → intended outcomes → objectives → key results → evidence → programs → money`

Organizations, authorities, committees, accounts, delivery partners, and oversight findings provide the institutional structure around that chain.

## Status

This repository is in active development. The first production pipeline will build the canonical organization layer from sources including USA.gov, the Federal Register, the U.S. Government Manual, financial ownership data, and the Federal Program Inventory.

## Design principles

1. **Sources are evidence, not canonical entities.** Multiple source records may refer to one organization.
2. **Identity and hierarchy are different questions.** A shared parent, website, or domain does not make two offices the same entity.
3. **Every assertion retains provenance.** Canonical records and relationships should trace back to source records.
4. **Ambiguity becomes review work.** The pipeline should expose uncertain matches instead of silently forcing them.
5. **Outputs are reproducible.** The same inputs and configuration should produce deterministic outputs.

## Install for development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Commands

```bash
federalgraph --help
federalgraph doctor
federalgraph sources
federalgraph organizations
```

`organizations` is scaffolded in this foundation commit. The next commit will add the live extractors and v2 organization resolver.

## Tests

```bash
pytest
ruff check .
```

## Project layout

```text
federalgraph/       Application package
config/             Versioned pipeline configuration
data/raw/           Source snapshots (not committed)
data/cache/         Download cache (not committed)
data/processed/     Generated datasets (not committed)
tests/              Automated tests
.github/workflows/  Continuous integration
```
