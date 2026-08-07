"""Extraction layer: read the wave extracts from both ECC systems.

A wave folder holds one sub-folder per source system. Every row is
tagged with the system it came from, because the two systems were
configured from the same template and their key ranges overlap: a
KUNNR is only unique within a system, so from here on the key of a
source record is the pair (system, key).

The wave folder also holds the material harmonisation table - the
governed decision about which duplicated products collapse into one
target product. That is a business decision made in MDG, not something
the pipeline is allowed to infer, so it is read as input.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

# Source system -> sub-folder in the wave extract directory.
SOURCE_SYSTEMS = {
    "GEP": "gep",
    "GVP": "gvp",
}

# Logical object name -> file name in each system's extract folder.
EXTRACT_FILES = {
    "materials": "ecc_mara_material_master.csv",
    "customers": "ecc_kna1_customers.csv",
    "vendors": "ecc_lfa1_vendors.csv",
    "open_items": "ecc_open_items.csv",
    "batch_stock": "ecc_batch_stock.csv",
}

HARMONISATION_FILE = "material_harmonisation.csv"

#: What the governed decision table is allowed to say. Mapping acts on
#: ``merge`` and ignores anything else, so an unrecognised value has to
#: stop the run rather than quietly leave both products loaded.
HARMONISATION_DECISIONS = frozenset({"merge", "keep_separate"})

SYSTEM_FIELD = "SOURCE_SYSTEM"


class ExtractError(RuntimeError):
    """Raised when a wave extract is missing or unreadable."""


@dataclass
class Dataset:
    name: str
    sources: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def for_system(self, system: str) -> list[dict[str, str]]:
        return [row for row in self.rows if row[SYSTEM_FIELD] == system]


@dataclass(frozen=True)
class HarmonisationDecision:
    """One governed decision to collapse a duplicated product."""

    source_system: str
    material: str
    target_product: str
    decision: str
    note: str


def read_csv(path: str | Path, name: str, source_system: str) -> Dataset:
    """Read one system's extract.

    ``source_system`` is required: every downstream stage keys on it,
    and a row without it fails somewhere far from where it was read.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise ExtractError(f"extract not found: {file_path}")
    if source_system not in SOURCE_SYSTEMS:
        raise ExtractError(f"unknown source system: {source_system}")

    rows: list[dict[str, str]] = []
    with open(file_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            record = {key: (value or "").strip() for key, value in row.items()}
            record[SYSTEM_FIELD] = source_system
            rows.append(record)

    return Dataset(name=name, sources=[file_path.as_posix()], rows=rows)


def read_harmonisation(path: str | Path) -> list[HarmonisationDecision]:
    """Read the product harmonisation table, if the wave has one."""
    file_path = Path(path)
    if not file_path.exists():
        return []

    decisions: list[HarmonisationDecision] = []
    with open(file_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            decisions.append(
                HarmonisationDecision(
                    source_system=row["SOURCE_SYSTEM"].strip().upper(),
                    material=row["MATNR"].strip(),
                    target_product=row["TARGET_PRODUCT"].strip(),
                    decision=row["DECISION"].strip().lower(),
                    note=(row.get("NOTE") or "").strip(),
                )
            )
    _validate_harmonisation(decisions, file_path)
    return decisions


def _validate_harmonisation(
    decisions: list[HarmonisationDecision], file_path: Path
) -> None:
    """Refuse a decision table that does not say one thing.

    This is a governed table with a regulatory consequence, so a
    decision resolved by file order is not a decision, and a decision
    the pipeline does not recognise is not a decision either: mapping
    acts on ``merge`` and ignores everything else, which would let a
    typo reverse a signed-off merge in silence. Chains are caught by
    DQ-MAT-011 during cleansing instead: whether a target number really
    disappears depends on what the extracts contain, which is not
    knowable here.

    The duplicate guard compares material numbers unpadded, matching
    DQ-MAT-009: the two systems' number ranges are the reason the table
    exists, and 100801 and 000000000000100801 are the same material.
    """
    seen: set[tuple[str, str]] = set()
    for decision in decisions:
        # A system that does not exist matches no extracted material, so
        # the merge would not happen and REC-MRG-004 would report the
        # material as absent from the extract - sending a steward to
        # look for a record that is present, over a typo in a column
        # with two legal values.
        if decision.source_system not in SOURCE_SYSTEMS:
            raise ExtractError(
                f"{file_path}: {decision.source_system}/{decision.material} "
                f"names source system '{decision.source_system}'; "
                f"use one of {', '.join(sorted(SOURCE_SYSTEMS))}"
            )
        if decision.decision not in HARMONISATION_DECISIONS:
            raise ExtractError(
                f"{file_path}: {decision.source_system}/{decision.material} "
                f"has decision '{decision.decision}', which the pipeline does "
                f"not act on; use one of {', '.join(sorted(HARMONISATION_DECISIONS))}"
            )
        key = (decision.source_system, decision.material.lstrip("0") or "0")
        if key in seen:
            raise ExtractError(
                f"{file_path}: {decision.source_system}/{decision.material} "
                "has more than one decision; the survivor must be named once"
            )
        seen.add(key)


def extract_wave(source_dir: str | Path) -> dict[str, Dataset]:
    """Read every extract for a wave from every source system."""
    base = Path(source_dir)
    if not base.is_dir():
        raise ExtractError(f"wave source directory not found: {base}")

    datasets = {
        name: Dataset(name=name) for name in EXTRACT_FILES
    }

    for system, folder in SOURCE_SYSTEMS.items():
        system_dir = base / folder
        if not system_dir.is_dir():
            raise ExtractError(
                f"no extract folder for source system {system}: {system_dir}"
            )
        for name, filename in EXTRACT_FILES.items():
            part = read_csv(system_dir / filename, name, source_system=system)
            datasets[name].sources.extend(part.sources)
            datasets[name].rows.extend(part.rows)

    return datasets
