from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from federalgraph.config import Settings
from federalgraph.export.csv_export import export_all
from federalgraph.export.program_csv import export_programs
from federalgraph.export.wordpress import export as export_wordpress
from federalgraph.extract import (
    federal_register,
    fpi,
    govinfo_govman,
    opm_fwd,
    performance_archive,
    sam_assistance,
    supplemental_programs,
    treasury_tax_expenditures,
    usagov,
    uscode_authority,
)
from federalgraph.normalize.organizations import normalize_records
from federalgraph.paths import ProjectPaths
from federalgraph.resolve.organizations import resolve
from federalgraph.resolve.programs import resolve as resolve_programs

LOGGER = logging.getLogger(__name__)


@dataclass
class Pipeline:
    paths: ProjectPaths

    def run_organizations(
        self,
        *,
        fpi_csv: Optional[Path] = None,
        source_csv: Optional[Path] = None,
        skip_usagov: bool = False,
        skip_federal_register: bool = False,
        skip_govinfo: bool = False,
        skip_opm: bool = False,
    ) -> dict[str, object]:
        self.paths.ensure_data_dirs()
        settings = Settings.load(self.paths.config / "sources.json").values
        source_settings = settings.get("sources", {})
        resolution = settings.get("resolution", {})
        extraction_summary: dict[str, object] = {}

        if source_csv is not None:
            if not source_csv.exists():
                raise FileNotFoundError(f"Source CSV not found: {source_csv}")
            records = pd.read_csv(source_csv).fillna("").to_dict("records")
            extraction_summary["input_mode"] = "existing_source_csv"
        else:
            records: list[dict] = []
            usa = source_settings.get("usagov", {})
            register = source_settings.get("federal_register", {})

            if usa.get("enabled", True) and not skip_usagov:
                LOGGER.info("Extracting organizations from USA.gov")
                usa_records = usagov.extract(
                    usa["base_url"],
                    usa.get("letters", "abcdefghijklmnopqrstuvwxyz"),
                    self.paths.raw,
                    timeout=int(usa.get("timeout_seconds", 45)),
                )
                records.extend(usa_records)
                extraction_summary["usagov_source_records"] = len(usa_records)

            if register.get("enabled", True) and not skip_federal_register:
                LOGGER.info("Extracting organizations from the Federal Register API")
                register_records = federal_register.extract(
                    register["endpoint"],
                    self.paths.raw,
                    timeout=int(register.get("timeout_seconds", 45)),
                )
                records.extend(register_records)
                extraction_summary["federal_register_source_records"] = len(register_records)

            govman = source_settings.get("govinfo_govman", {})
            if govman.get("enabled", False) and not skip_govinfo:
                LOGGER.info("Extracting organizations from the U.S. Government Manual / GovInfo")
                govinfo_records = govinfo_govman.extract(
                    govman["package_id"],
                    govman["xml_url"],
                    govman["publication_date"],
                    self.paths.raw,
                    timeout=int(govman.get("timeout_seconds", 120)),
                    workers=int(govman.get("workers", 12)),
                    api_base_url=govman.get("api_base_url", "https://api.govinfo.gov"),
                    api_key_env=govman.get("api_key_env", "GOVINFO_API_KEY"),
                    api_key_fallback=govman.get("api_key_fallback", "DEMO_KEY"),
                    page_size=int(govman.get("api_page_size", 100)),
                )
                records.extend(govinfo_records)
                extraction_summary["govinfo_source_records"] = len(govinfo_records)
                extraction_summary["govinfo_package_id"] = govman["package_id"]

            opm = source_settings.get("opm_fwd", {})
            if opm.get("enabled", False) and not skip_opm:
                LOGGER.info("Extracting organization hierarchy from OPM Federal Workforce Data")
                opm_records = opm_fwd.extract(
                    opm["files_api"],
                    opm["download_base_url"],
                    self.paths.raw,
                    timeout=int(opm.get("timeout_seconds", 180)),
                )
                records.extend(opm_records)
                extraction_summary["opm_source_records"] = len(opm_records)

            if fpi_csv is not None:
                LOGGER.info("Extracting organization evidence from %s", fpi_csv)
                fpi_records = fpi.extract(fpi_csv)
                records.extend(fpi_records)
                extraction_summary["fpi_source_records"] = len(fpi_records)

        # Reviewed statutory entities absent from the directory extracts remain
        # independent, cited source records. The source CSV may already contain
        # them on a subsequent build, so do not append the same assertion twice.
        statutory_path = self.paths.config / "statutory_organization_sources.csv"
        if statutory_path.exists():
            statutory_records = pd.read_csv(statutory_path).fillna("").to_dict("records")
            required = {"source", "source_record_id", "source_name", "source_url"}
            if statutory_records and not required.issubset(statutory_records[0]):
                raise ValueError(f"Statutory organization CSV needs columns: {sorted(required)}")
            existing = {
                (str(row.get("source") or ""), str(row.get("source_record_id") or ""))
                for row in records
            }
            added = 0
            for row in statutory_records:
                if not all(str(row.get(field) or "").strip() for field in required):
                    raise ValueError("Statutory organization records need source, ID, name, and URL")
                key = (str(row["source"]), str(row["source_record_id"]))
                if key not in existing:
                    records.append(row)
                    existing.add(key)
                    added += 1
            extraction_summary["statutory_organization_source_records_added"] = added

        if not records:
            raise RuntimeError("No organization source records were produced.")

        normalized = normalize_records(records)

        override_path = self.paths.config / "organization_identity_overrides.csv"
        identity_overrides: list[dict] = []
        if override_path.exists():
            identity_overrides = pd.read_csv(override_path).fillna("").to_dict("records")
            extraction_summary["identity_overrides_loaded"] = len(identity_overrides)

        outputs = resolve(
            normalized,
            auto_merge_threshold=float(resolution.get("auto_merge_threshold", 96)),
            review_threshold=float(resolution.get("review_threshold", 72)),
            hierarchy_threshold=float(resolution.get("hierarchy_threshold", 80)),
            identity_overrides=identity_overrides,
        )
        summary = export_all(self.paths.processed, *outputs, extraction_summary)
        export_wordpress(
            self.paths.processed / "organizations.csv",
            self.paths.processed / "wordpress_organizations.csv",
        )
        LOGGER.info("Organization build complete: %s", json.dumps(summary, sort_keys=True))
        return summary

    def run_programs(
        self,
        *,
        source_csv: Optional[Path] = None,
        performance_csv: Optional[Path] = None,
        supplemental_csvs: Optional[list[Path]] = None,
        skip_sam: bool = False,
        skip_treasury: bool = False,
        skip_performance: bool = False,
        skip_uscode: bool = False,
        max_sam_pages: Optional[int] = None,
    ) -> dict[str, object]:
        """Build the program registry without fiscal amounts.

        Program identity is compiled from multiple official sources.  Statutory authority and
        purpose evidence are collected during the same pass because they materially improve
        program reconciliation.  Financial facts are intentionally out of scope here.
        """

        self.paths.ensure_data_dirs()
        settings = Settings.load(self.paths.config / "sources.json").values
        source_settings = settings.get("sources", {})
        extraction_summary: dict[str, object] = {}
        authorities: list[dict] = []
        functions: list[dict] = []

        if source_csv is not None:
            if not source_csv.exists():
                raise FileNotFoundError(f"Program source CSV not found: {source_csv}")
            records = pd.read_csv(source_csv).fillna("").to_dict("records")
            extraction_summary["input_mode"] = "existing_program_source_csv"
        else:
            records: list[dict] = []

            sam = source_settings.get("sam_assistance", {})
            if sam.get("enabled", True) and not skip_sam:
                LOGGER.info("Extracting programs from SAM.gov Assistance Listings")
                sam_records, sam_authorities, sam_functions = sam_assistance.extract(
                    sam["endpoint"],
                    self.paths.raw,
                    bulk_url=sam.get("bulk_url", ""),
                    api_key_env=sam.get("api_key_env", "SAM_API_KEY"),
                    status=sam.get("status", "ALL"),
                    page_size=int(sam.get("page_size", 100)),
                    timeout=int(sam.get("timeout_seconds", 120)),
                    max_pages=max_sam_pages,
                )
                records.extend(sam_records)
                authorities.extend(sam_authorities)
                functions.extend(sam_functions)
                extraction_summary["sam_assistance_source_records"] = len(sam_records)
                extraction_summary["sam_authority_rows"] = len(sam_authorities)
                extraction_summary["sam_function_rows"] = len(sam_functions)

            treasury = source_settings.get("treasury_tax_expenditures", {})
            if treasury.get("enabled", True) and not skip_treasury:
                LOGGER.info("Extracting tax-expenditure identities from Treasury")
                treasury_records = treasury_tax_expenditures.extract(
                    treasury["workbook_url"],
                    self.paths.raw,
                    fiscal_year=int(treasury.get("fiscal_year", 2027)),
                    timeout=int(treasury.get("timeout_seconds", 120)),
                )
                records.extend(treasury_records)
                extraction_summary["treasury_tax_expenditure_source_records"] = len(treasury_records)

            performance = source_settings.get("performance_fpi_archive", {})
            if performance_csv is not None:
                LOGGER.info("Reading Performance.gov program inventory from %s", performance_csv)
                perf_records = performance_archive.records_from_reference_csv(
                    performance_csv.read_text(encoding="utf-8-sig"), str(performance_csv)
                )
                records.extend(perf_records)
                extraction_summary["performance_archive_source_records"] = len(perf_records)
            elif performance.get("enabled", True) and not skip_performance:
                LOGGER.info("Extracting programs from the Performance.gov FPI archive")
                perf_records = performance_archive.extract(
                    performance["main_url"],
                    self.paths.raw,
                    reference_csv_url=performance.get("reference_csv_url", ""),
                    timeout=int(performance.get("timeout_seconds", 90)),
                )
                records.extend(perf_records)
                extraction_summary["performance_archive_source_records"] = len(perf_records)

            for path in supplemental_csvs or []:
                LOGGER.info("Reading supplemental official program evidence from %s", path)
                extra = supplemental_programs.extract(path)
                records.extend(extra)
                extraction_summary.setdefault("supplemental_source_records", 0)
                extraction_summary["supplemental_source_records"] += len(extra)

        if not records:
            raise RuntimeError("No program source records were produced.")

        if authorities and not skip_uscode:
            uscode = source_settings.get("uscode", {})
            if uscode.get("enabled", True):
                LOGGER.info("Resolving exact U.S. Code citations for statutory purpose evidence")
                authorities = uscode_authority.enrich_authorities(
                    authorities,
                    self.paths.raw,
                    download_page=uscode.get(
                        "download_page", "https://uscode.house.gov/download/download.shtml"
                    ),
                    timeout=int(uscode.get("timeout_seconds", 120)),
                )
                extraction_summary["statutory_authority_rows_matched"] = sum(
                    1 for row in authorities if row.get("statutory_lookup_status") == "matched"
                )
                extraction_summary["statutory_purpose_rows_found"] = sum(
                    1 for row in authorities if row.get("statutory_purpose_text")
                )

        outputs = resolve_programs(records, authorities, functions, self.paths.processed)
        summary = export_programs(self.paths.processed, outputs, extraction_summary)
        LOGGER.info("Program build complete: %s", json.dumps(summary, sort_keys=True))
        return summary
