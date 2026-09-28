# RFC 0007 — Program identity, statutory authority, and purpose

## Decision

FederalGraph defines programs by compiling multiple official source assertions rather than treating any one inventory as the universe of federal programs.

The primary program sources are:

1. SAM.gov Assistance Listings;
2. SAM functional classifications / Functional Index evidence; and
3. Treasury tax-expenditure identities.

USAspending is intentionally deferred because fiscal amounts are out of scope for the program-identity build.

Additional discovery sources are Performance.gov agency program inventories and performance materials, the President's Budget Appendix and Congressional Budget Justifications, AFRs/PARs and financial statements, the U.S. Code and enacted law, CFR/eCFR, appropriations and explanatory statements, and official oversight/evaluation material. CRS, GAO, OIG, and agency evaluations are validation/interpretation sources by default rather than automatic identity generators.

## Identity and purpose are resolved together

A program name by itself is weak identity evidence. Program reconciliation should use, when available:

- source identifier;
- administering organization;
- exact statutory authority;
- statutory purpose or purpose language;
- program mechanism/type; and
- source-provided description or objective.

The program ingest therefore captures statutory authority and purpose evidence during initial discovery rather than as a later enrichment project.

## Purpose hierarchy

FederalGraph preserves the distinction between Congressional/statutory purpose and agency-stated purpose.

1. Exact U.S. Code section text is preferred when the program source gives a specific U.S.C. citation.
2. Public Laws / Statutes at Large are the next legal source where a provision is uncodified or the enacted text is needed.
3. Current official agency program/performance material is the preferred non-statutory fallback.
4. Archived Performance.gov program material is retained as historical agency-stated evidence.

A purpose statement from Performance.gov is never labeled statutory merely because it describes a statutory program.

## Admission rule

A source assertion may create a canonical program automatically when an official source explicitly enumerates a program/provision (for example, a SAM Assistance Listing or Treasury tax expenditure) or when a source explicitly describes a separately administered program.

Budget accounts, appropriations headings, regulatory topics, offices, and oversight-report subjects are evidence/candidates rather than programs by default. They require corroboration before admission.

## Resolution rules

Automatic merge is conservative:

- same source identifier = same source program;
- exact normalized name + same resolved administering organization may merge across sources;
- same exact U.S.C. section + same organization + near-identical name may merge;
- fuzzy name similarity alone never establishes identity.

Broad programs and subprograms are represented with program relationships rather than collapsed as duplicates.

## Organization mapping

Programs map to the existing FederalGraph organization registry using the deepest exact organization name/alias supported by source evidence. If no organization resolves, the program remains unresolved and is emitted to `programs_without_organizations.csv` rather than forced to a parent agency.

## Out of scope for this release

No obligations, outlays, budget authority, revenue loss, TAS mapping, appropriations mapping, or other financial facts are part of v0.8.
