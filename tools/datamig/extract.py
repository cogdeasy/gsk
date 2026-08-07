"""Extraction layer: read the ECC wave extracts."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

# Logical object name -> file name in the wave extract folder.
EXTRACT_FILES = {
    "materials": "ecc_mara_material_master.csv",
    "customers": "ecc_kna1_customers.csv",
    "vendors": "ecc_lfa1_vendors.csv",
    "open_items": "ecc_open_items.csv",
    "batch_stock": "ecc_batch_stock.csv",
}


class ExtractError(RuntimeError):
    """Raised when a wave extract is missing or unreadable."""


@dataclass
class Dataset:
    name: str
    source: str
    rows: list[dict[str, str]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)


def read_csv(path: str | Path, name: str) -> Dataset:
    file_path = Path(path)
    if not file_path.exists():
        raise ExtractError(f"extract not found: {file_path}")

    rows: list[dict[str, str]] = []
    with open(file_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append({key: (value or "").strip() for key, value in row.items()})

    return Dataset(name=name, source=file_path.as_posix(), rows=rows)


def extract_wave(source_dir: str | Path) -> dict[str, Dataset]:
    """Read every extract for a wave, keyed by logical object name."""
    base = Path(source_dir)
    if not base.is_dir():
        raise ExtractError(f"wave source directory not found: {base}")

    return {
        name: read_csv(base / filename, name)
        for name, filename in EXTRACT_FILES.items()
    }
