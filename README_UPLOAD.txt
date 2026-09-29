FederalGraph SAM bulk-ingestion fix

Upload these two files to the same paths in the GitHub repository, replacing the existing versions:

  federalgraph/extract/sam_assistance.py
  tests/test_sam_assistance.py

Changes:
- recognizes SAM numbered bulk headers such as Federal Agency (030), Authorization (040), Objectives (050)
- parses current SAM Federal Agency hierarchy into department + administering agency
- preserves Parent Shortname, Related Programs, Published Date, and source URL evidence
- falls back to Windows-1252 when the SAM bulk CSV is not valid UTF-8
- adds a regression test based on the current SAM bulk export shape

After updating locally from GitHub, run:

  federalgraph programs --skip-treasury --skip-performance --skip-uscode

Then inspect the summary. sam_authority_rows and program_organization_relationships should no longer both be zero, and programs_without_organizations should drop below the prior 2,873 if the canonical organization names align.
