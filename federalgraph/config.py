from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class Settings:
    values: Dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "Settings":
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            return cls(values=json.load(handle))
