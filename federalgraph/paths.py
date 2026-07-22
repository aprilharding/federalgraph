from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    config: Path
    raw: Path
    cache: Path
    processed: Path

    @classmethod
    def discover(cls, start: Optional[Path] = None) -> "ProjectPaths":
        current = (start or Path.cwd()).resolve()
        for candidate in (current, *current.parents):
            if (candidate / "pyproject.toml").exists():
                return cls(
                    root=candidate,
                    config=candidate / "config",
                    raw=candidate / "data" / "raw",
                    cache=candidate / "data" / "cache",
                    processed=candidate / "data" / "processed",
                )
        raise RuntimeError("Could not find project root containing pyproject.toml")

    def ensure_data_dirs(self) -> None:
        for path in (self.raw, self.cache, self.processed):
            path.mkdir(parents=True, exist_ok=True)
