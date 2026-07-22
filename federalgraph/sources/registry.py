from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable

from federalgraph.sources.base import SourceExtractor


@dataclass
class SourceRegistry:
    _extractors: Dict[str, SourceExtractor] = field(default_factory=dict)

    def register(self, extractor: SourceExtractor) -> None:
        if extractor.name in self._extractors:
            raise ValueError(f"Source already registered: {extractor.name}")
        self._extractors[extractor.name] = extractor

    def names(self) -> Iterable[str]:
        return sorted(self._extractors)

    def get(self, name: str) -> SourceExtractor:
        try:
            return self._extractors[name]
        except KeyError as exc:
            raise KeyError(f"Unknown source: {name}") from exc
