from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from federalgraph.config import Settings
from federalgraph.export.csv_export import export_all
from federalgraph.export.wordpress import export as export_wordpress
from federalgraph.extract import federal_register, fpi, usagov
from federalgraph.normalize.organizations import normalize_records
from federalgraph.paths import ProjectPaths
from federalgraph.resolve.organizations import resolve

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

            if fpi_csv is not None:
                LOGGER.info("Extracting organization evidence from %s", fpi_csv)
                fpi_records = fpi.extract(fpi_csv)
                records.extend(fpi_records)
                extraction_summary["fpi_source_records"] = len(fpi_records)

        if not records:
            raise RuntimeError("No organization source records were produced.")

        normalized = normalize_records(records)
        outputs = resolve(
            normalized,
            auto_merge_threshold=float(resolution.get("auto_merge_threshold", 96)),
            review_threshold=float(resolution.get("review_threshold", 72)),
            hierarchy_threshold=float(resolution.get("hierarchy_threshold", 80)),
        )
        summary = export_all(self.paths.processed, *outputs, extraction_summary)
        export_wordpress(
            self.paths.processed / "organizations.csv",
            self.paths.processed / "wordpress_organizations.csv",
        )
        LOGGER.info("Organization build complete: %s", json.dumps(summary, sort_keys=True))
        return summary
