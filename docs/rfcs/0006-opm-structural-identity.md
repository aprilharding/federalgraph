# RFC-0006: OPM Structural Identity Keys

## Status
Accepted for FederalGraph v0.7.

## Problem
Federal Workforce Data represents many standalone federal entities at multiple reporting levels. The same organization can appear as a department, agency, and default subagency with abbreviated or truncated labels. Treating those rows as separate identities creates duplicate organizations, false parent/component relationships, and noisy fuzzy-review candidates.

At the same time, OPM also contains genuinely distinct component agencies and subagencies. Similar names alone must not collapse them.

## Decision
Use OPM's own organization codes as deterministic identity evidence in the narrow case where the reporting levels represent the same standalone entity.

Rows share one OPM structural identity key when:

1. the department row has department code `XX`; or
2. the agency row has department code `XX` and agency code `XX`; or
3. the default-subagency row has department code `XX`, agency code `XX`, and subagency code `XX00`.

These rows receive the same deterministic key `opm-unit:XX` and are resolved as one identity before hierarchy is built.

This rule does **not** merge a component agency when its agency code differs from its department code. For example, OPM department `DOD` and agencies `AF`, `AR`, and `NV` remain distinct.

Named subagencies such as `DD13`, `AR2A`, or `AF3C` also remain distinct.

## Same-source fuzzy matching
Distinct records within the same authoritative source are not sent to fuzzy identity review. Same-source aliases must be resolved by deterministic source-specific evidence or an explicit human override.

This prevents structurally distinct OPM units such as Army North and Army South, or Naval Air Systems Command and Naval Sea Systems Command, from appearing as duplicate candidates merely because their names are similar.

## Effect on hierarchy
Identity resolution runs before hierarchy construction. When OPM department/agency/default-subagency rows collapse to one identity, the artificial self-hierarchy edge disappears. Genuine Department → Agency → Subagency reporting relationships remain provisional OPM hierarchy evidence.
