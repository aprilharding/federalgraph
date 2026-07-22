from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol


@dataclass(frozen=True)
class SourceRecord:
    source_name: str
    source_record_id: str
    record_type: str
    payload: Mapping[str, object]


class SourceExtractor(Protocol):
    name: str

    def extract(self) -> Iterable[SourceRecord]:
        """Yield records from one authoritative source."""
