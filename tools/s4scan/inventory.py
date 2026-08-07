"""Custom code object inventory.

The inventory is the programme's view of the estate: who owns each
object, which deployment wave it belongs to, how heavily it is used and
whether it is GxP classified. Findings are joined to it so the backlog
can be prioritised by wave and sized with the validation overhead that
GxP objects carry.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

GXP_VALIDATION_MULTIPLIER = {
    "gxp_critical": 2.0,
    "gxp_relevant": 1.5,
    "non_gxp": 1.0,
}

CRITICALITY_WEIGHT = {
    "critical": 3,
    "high": 2,
    "medium": 1,
    "low": 0,
}


@dataclass(frozen=True)
class InventoryEntry:
    object_name: str
    object_type: str
    path: str
    module: str
    owner: str
    gxp_class: str
    wave: str
    monthly_executions: int
    business_criticality: str
    validation_package: str
    remediated_path: str = ""

    @property
    def is_remediated(self) -> bool:
        """True once a remediated S/4HANA implementation exists."""
        return bool(self.remediated_path)

    @property
    def validation_multiplier(self) -> float:
        return GXP_VALIDATION_MULTIPLIER.get(self.gxp_class, 1.0)

    @property
    def is_gxp(self) -> bool:
        return self.gxp_class in ("gxp_critical", "gxp_relevant")

    @property
    def criticality_weight(self) -> int:
        return CRITICALITY_WEIGHT.get(self.business_criticality, 0)


class Inventory:
    """Lookup of inventory entries by source path and by object name."""

    def __init__(self, entries: list[InventoryEntry]) -> None:
        self._entries = entries
        self._by_path = {self._normalise(entry.path): entry for entry in entries}
        self._by_name = {entry.object_name.upper(): entry for entry in entries}

    @staticmethod
    def _normalise(path: str) -> str:
        return str(Path(path).as_posix()).lstrip("./")

    @classmethod
    def load(cls, path: str | Path) -> Inventory:
        entries: list[InventoryEntry] = []
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                entries.append(
                    InventoryEntry(
                        object_name=row["object_name"].strip(),
                        object_type=row["object_type"].strip(),
                        path=row["path"].strip(),
                        module=row["module"].strip(),
                        owner=row["owner"].strip(),
                        gxp_class=row["gxp_class"].strip(),
                        wave=row["wave"].strip(),
                        monthly_executions=int(row["monthly_executions"]),
                        business_criticality=row["business_criticality"].strip(),
                        validation_package=row["validation_package"].strip(),
                        remediated_path=(row.get("remediated_path") or "").strip(),
                    )
                )
        return cls(entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    def for_path(self, path: str | Path) -> InventoryEntry | None:
        candidate = self._normalise(str(path))
        if candidate in self._by_path:
            return self._by_path[candidate]
        # Allow the scanner to be pointed at an absolute or nested path.
        for known, entry in self._by_path.items():
            if candidate.endswith(known):
                return entry
        return None

    def for_name(self, object_name: str) -> InventoryEntry | None:
        return self._by_name.get(object_name.upper())

    def waves(self) -> list[str]:
        return sorted({entry.wave for entry in self._entries})
