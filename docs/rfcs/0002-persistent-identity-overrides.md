# RFC-0002: Persistent Organization Identity Overrides

## Status
Accepted for FederalGraph v0.4.

## Problem
The v0.3 resolver reduced organization identity ambiguity dramatically, but some
valid equivalences cannot be derived safely from lexical similarity alone. Examples
include legal names versus public names, historical renames, and branded names.
Likewise, some lexically similar organizations must be permanently kept separate.

A reproducible open-source pipeline must remember reviewed decisions rather than
asking a human to re-adjudicate the same pair on every run.

## Decision
FederalGraph stores human-reviewed identity decisions in:

`config/organization_identity_overrides.csv`

Each row contains:

- `left_name`
- `right_name`
- `decision`
- `preferred_name`
- `reviewed_by`
- `notes`

Supported decisions are:

- `merge`: the two source-visible names represent one identity.
- `historical_alias`: the names represent the same continuing identity across a
  rename; the preferred current/later name is canonical.
- `keep_separate`: the names are distinct identities and should not return to the
  fuzzy review queue.

## Resolver order

1. Normalize source records.
2. Apply deterministic lexical alias rules.
3. Apply persistent human merge / historical-alias decisions.
4. Protect reviewed keep-separate pairs.
5. Generate fuzzy review candidates for anything still unresolved.
6. Choose canonical names, honoring `preferred_name` for reviewed merges.
7. Emit aliases and source provenance for every canonical identity.

Fuzzy scores never cause an automatic merge.

## V1 review
The first override set was derived from the 2026-09-21 USA.gov and Federal
Register extraction. It includes all 25 unique pairs in the v0.3 manual-review
queue plus additional high-confidence equivalences discovered by auditing shared
websites, source descriptions, legal/public names, and explicit rename language.

The same review also records known false positives as `keep_separate` decisions.

## Scope boundary
These overrides resolve **identity**, not whether an entity is current, defunct,
a program rather than an organization, or part of the federal government. Those
are separate classification/status layers and must not be inferred from identity
resolution.
