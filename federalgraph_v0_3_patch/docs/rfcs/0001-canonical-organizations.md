# RFC-0001: Canonical organization identity

**Status:** Accepted for v0.3  
**Scope:** FederalGraph organization registry

## Goal

Build a reproducible list of distinct federal organizational entities from multiple authoritative directories without silently collapsing parent/child organizations or treating source formatting differences as separate entities.

## Principles

1. **Organization identity is separate from names.** A source name is evidence about an organization, not the organization's identity by itself.
2. **Aliases preserve source language.** FederalGraph retains every source-provided name and explicit acronym attached to a resolved organization.
3. **Hierarchy is not identity.** Parent/component relationships are emitted separately from merge decisions.
4. **Automatic merges require deterministic equivalence.** Fuzzy similarity scores prioritize human review; they do not cause automatic merges.
5. **Acronyms corroborate; they do not establish identity.** Matching initials alone are never enough to create or merge a candidate.
6. **Source evidence is retained.** Every source record remains traceable to the canonical entity produced by the resolver.
7. **Uncertainty is explicit.** Ambiguous cases remain distinct and are labeled `Needs review` rather than being silently merged.

## Deterministic equivalence rules

v0.3 may automatically resolve records when their names become identical after one or more conservative syntactic transformations:

- remove a trailing source-provided acronym, e.g. `Department of Agriculture (USDA)`;
- normalize `U.S.` and `United States` jurisdictional prefixes;
- ignore inconsistent use of the article `the`;
- undo directory alphabetization, e.g. `Economic Analysis, Bureau of` -> `Bureau of Economic Analysis`;
- normalize `X Department` -> `Department of X`.

These transformations produce **resolution keys only**. They do not overwrite source names.

## Output tables

### `organizations.csv`

One row per provisional canonical organization. Important fields include canonical name, sources, source-record count, and resolution status.

### `organization_aliases.csv`

One row per source-attested name or explicit source acronym associated with an organization. Generated normalization keys are not published as aliases.

### `organization_sources.csv`

One row per source assertion, retaining the source record identifier and linking it to the canonical organization ID.

### `organization_match_candidates.csv`

Both deterministic merges and unresolved fuzzy candidates, with the evidence used by the resolver.

### `organization_review_queue.csv`

Only unresolved pairs that clear the configured fuzzy review threshold. These require a human decision.

### `organization_relationships.csv`

Parent/component relationships. Relationship inference is intentionally separate from identity resolution.

### `organization_status_evidence.csv`

Evidence about whether an entity appears current; presence in a directory is evidence, not a final legal status determination.

## Stable IDs

The v0.3 IDs remain reproducible but provisional because they are derived from the selected canonical display name. A later RFC will define persistent ID assignment and a decision ledger so future naming changes cannot alter an established entity ID.

## Non-goals for v0.3

- Full parent/child hierarchy across government
- Historical succession and renaming chains
- Legal status determination
- Manually curated acronym dictionaries
- Persistent review decisions across runs

Those layers can be added without changing the core rule that identity, aliases, source evidence, and hierarchy are separate concerns.
