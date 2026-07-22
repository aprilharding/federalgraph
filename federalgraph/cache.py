from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Cache:
    root: Path

    def path_for(self, namespace: str, key: str, suffix: str = ".bin") -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        directory = self.root / namespace
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{digest}{suffix}"
