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

from .identity import material_key

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

#: What every row of the table must carry. A governed input arriving
#: malformed is an operator's mistake to correct, not a traceback.
HARMONISATION_COLUMNS = ("SOURCE_SYSTEM", "MATNR", "TARGET_PRODUCT", "DECISION")

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
    # Before the file check: an unknown system is a defect in the
    # caller, and reporting a missing extract instead sends whoever
    # reads it looking for the wrong thing.
    if source_system not in SOURCE_SYSTEMS:
        raise ExtractError(f"unknown source system: {source_system}")
    file_path = Path(path)
    if not file_path.exists():
        raise ExtractError(f"extract not found: {file_path}")

    rows: list[dict[str, str]] = []
    with open(file_path, newline="", encoding="utf-8") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            record = {key: (value or "").strip() for key, value in row.items()}
            # An extract that names its own system is checked against
            # the folder it arrived in rather than relabelled by it. The
            # two disagreeing means a file is in the wrong place, and
            # the whole pipeline keys on the answer: silently taking the
            # folder's word for it migrates one system's records under
            # the other's name.
            stated = record.get(SYSTEM_FIELD, "")
            if stated and stated != source_system:
                # The record's row, counted the way the spreadsheet the
                # steward opens it in counts: a quoted newline makes
                # the physical line something nobody is looking at.
                raise ExtractError(
                    f"{file_path}: row {number} was extracted from {stated} but "
                    f"read as {source_system}; the file is in the wrong "
                    "system's folder or the column is wrong"
                )
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
        reader = csv.DictReader(handle)
        # The CLI turns ExtractError into a message and exit code 2, so
        # anything that reaches an operator as a traceback is a mistake
        # in a governed table that the pipeline failed to explain.
        missing = [
            column
            for column in HARMONISATION_COLUMNS
            if column not in (reader.fieldnames or [])
        ]
        if missing:
            raise ExtractError(
                f"{file_path}: decision table has no {', '.join(missing)} "
                f"column; it needs {', '.join(HARMONISATION_COLUMNS)}"
            )
        # From 2: a spreadsheet counts the header as row 1, and the
        # steward correcting this is reading it in one.
        for line, row in enumerate(reader, start=2):
            values = {
                column: (row.get(column) or "").strip()
                for column in HARMONISATION_COLUMNS
            }
            # Not TARGET_PRODUCT: a `keep_separate` ruling has no
            # surviving product to name. A `merge` without one is
            # caught below, where the decision is known.
            empty = [
                column
                for column in ("SOURCE_SYSTEM", "MATNR", "DECISION")
                if not values[column]
            ]
            if empty:
                raise ExtractError(
                    f"{file_path}: row {line} leaves {', '.join(empty)} empty; "
                    "a decision that does not say what it decides about is "
                    "not a decision"
                )
            decisions.append(
                HarmonisationDecision(
                    source_system=values["SOURCE_SYSTEM"].upper(),
                    material=values["MATNR"],
                    target_product=values["TARGET_PRODUCT"],
                    decision=values["DECISION"].lower(),
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
        if decision.decision == "merge" and not decision.target_product:
            raise ExtractError(
                f"{file_path}: {decision.source_system}/{decision.material} "
                "is to be merged but names no surviving product; without "
                "one the record has nowhere to land"
            )
        # The same key the rest of the pipeline decides with. Spelling
        # the padding rule out here again is how the two halves of a
        # decision drifted apart before, and a guard that disagrees
        # with the code applying the decisions lets file order pick
        # the survivor.
        key = material_key(decision.source_system, decision.material)
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
