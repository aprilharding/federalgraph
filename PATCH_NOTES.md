# FederalGraph v0.7.0

This release cleans the four-source organization build after the first live GovInfo + OPM run.

## Changes

- Adds deterministic OPM structural identity keys for standalone entities represented at department, agency, and `XX00` default-subagency levels.
- Prevents fuzzy identity review between distinct records from the same authoritative source.
- Persists 13 cross-source decisions from the v0.6 live review: 8 merges and 5 keep-separate decisions.
- Removes artificial OPM parent/component links that were actually duplicate reporting representations of one identity.
- Adds RFC-0006 documenting the OPM structural identity rule.
- Adds tests for standalone OPM identity collapse, DOD component separation, and same-source subagency review suppression.

Expected effect on the 2026-09-22 live source set: approximately 997 provisional entities should fall to about 949 identity-resolved entities, while the identity review queue should approach zero. Naming review remains a separate task for non-GovInfo entities.
