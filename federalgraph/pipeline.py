from __future__ import annotations

import logging
from dataclasses import dataclass

from federalgraph.paths import ProjectPaths

LOGGER = logging.getLogger(__name__)


@dataclass
class Pipeline:
    paths: ProjectPaths

    def run_organizations(self) -> int:
        self.paths.ensure_data_dirs()
        LOGGER.info("Organization pipeline scaffold is ready.")
        LOGGER.info("Processed output directory: %s", self.paths.processed)
        LOGGER.info("Next commit: live extractors and resolver v2.")
        return 0
