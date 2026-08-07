"""Custom code object inventory.

The inventory is the programme's view of the estate: which of the two
ECC source systems an object lives in, who owns it, which deployment
wave it belongs to, how heavily it is used and whether it is GxP
classified. Findings are joined to it so the backlog can be prioritised
by wave and sized with the validation overhead that GxP objects carry.

Two columns carry the two-into-one merge:

``convergence_group``
    Objects sharing a group implement the same business function in
    both source systems and collapse to a single S/4HANA object.
``disposition``
    ``retain`` - remediate this object in place.
    ``converge`` - remediate as part of its convergence group.
    ``decommission`` - the object stops existing when the two systems
    become one, so it is not remediated at all.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


class InventoryError(RuntimeError):
    """Raised when the estate inventory contradicts itself."""


SOURCE_SYSTEMS = {
    "GEP": "GSK core ECC 6.0",
    "GVP": "GSK Vaccines ECC 6.0",
}

RETAIN = "retain"
CONVERGE = "converge"
DECOMMISSION = "decommission"

# Sorts after any numbered wave. Not a wave number itself: an object
# nobody has scheduled is the end of the backlog, not wave 999.
UNSCHEDULED_RANK = 10**6


def wave_rank(wave: str) -> int:
    """Delivery order of a wave. Anything unscheduled sorts last.

    Every wave comparison goes through this rather than sorting the
    names, which agree with it only up to `wave9`: as text `wave10`
    sorts before `wave2`, which in the table a programme sequences
    builds from puts later work first. The number is read rather than
    looked up, so a wave the programme adds is ordered the day it
    appears - enumerating them meant `wave3` arriving ranked equal to
    `unassigned` and tie-broken by object name.
    """
    number = wave.removeprefix("wave")
    if wave.startswith("wave") and number.isdigit():
        return int(number)
    return UNSCHEDULED_RANK


def is_a_duplication(members: list[tuple[str, bool]]) -> bool:
    """Whether a convergence group is two implementations of one thing.

    ``members`` is (source system, is decommissioned) per member. Two
    callers need this answer - the scanner, to decide whether to report
    the group at all, and SI-CONV-001, to decide whether to flag the
    objects - and they have to give the same answer or a finding ends
    up on an object whose group appears in no table.

    A pair that both sides switch off stays a duplication: it is the
    reason the interface disappears, and the avoided effort is reported
    as such. A pair where only one side is switched off is not - the
    survivor has nothing left to converge with and is simply an object
    to remediate.
    """
    systems = {system for system, _ in members}
    remaining = {system for system, dropped in members if not dropped}
    if not remaining:
        return len(systems) > 1
    return len(remaining) > 1


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
    source_system: str
    object_type: str
    path: str
    module: str
    owner: str
    gxp_class: str
    wave: str
    monthly_executions: int
    business_criticality: str
    validation_package: str
    convergence_group: str = ""
    disposition: str = RETAIN
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

    @property
    def converges(self) -> bool:
        return self.disposition == CONVERGE and bool(self.convergence_group)

    @property
    def is_decommissioned(self) -> bool:
        """True when the merge removes the object instead of migrating it."""
        return self.disposition == DECOMMISSION


class Inventory:
    """Lookup of inventory entries by source path and by object name."""

    def __init__(self, entries: list[InventoryEntry]) -> None:
        self._entries = entries
        self._by_path = {self._normalise(entry.path): entry for entry in entries}
        self._by_name = {entry.object_name.upper(): entry for entry in entries}

    @property
    def entries(self) -> list[InventoryEntry]:
        return list(self._entries)

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
                        source_system=row["source_system"].strip().upper(),
                        object_type=row["object_type"].strip(),
                        path=row["path"].strip(),
                        module=row["module"].strip(),
                        owner=row["owner"].strip(),
                        gxp_class=row["gxp_class"].strip(),
                        wave=row["wave"].strip(),
                        monthly_executions=int(row["monthly_executions"]),
                        business_criticality=row["business_criticality"].strip(),
                        validation_package=row["validation_package"].strip(),
                        convergence_group=(row.get("convergence_group") or "").strip(),
                        disposition=(row.get("disposition") or RETAIN).strip() or RETAIN,
                        remediated_path=(row.get("remediated_path") or "").strip(),
                    )
                )
        inventory = cls(entries)
        inventory._check_groups_are_wave_aligned(path)
        return inventory

    def _check_groups_are_wave_aligned(self, path: str | Path) -> None:
        """A convergence group is delivered as one piece of work.

        `--wave` narrows the estate on the strength of that, so a group
        split across two waves would vanish from the convergence
        backlog of each while `SI-CONV-001` still fired on the visible
        member - the report flagging an object as duplicated and
        stating that no duplication exists.
        """
        waves: dict[str, set[str]] = {}
        for entry in self._entries:
            if entry.convergence_group:
                waves.setdefault(entry.convergence_group, set()).add(entry.wave)
        for group_id, group_waves in sorted(waves.items()):
            if len(group_waves) > 1:
                raise InventoryError(
                    f"{path}: convergence group {group_id} spans "
                    f"{', '.join(sorted(group_waves))}; a group is planned "
                    "and delivered as one piece of work, so its members "
                    "belong in one wave"
                )

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
        return sorted({entry.wave for entry in self._entries}, key=wave_rank)

    def source_systems(self) -> list[str]:
        return sorted({entry.source_system for entry in self._entries})

    def convergence_group(self, group_id: str) -> list[InventoryEntry]:
        """Every object that collapses into the same S/4HANA successor."""
        return [entry for entry in self._entries if entry.convergence_group == group_id]

    def is_cross_system_group(self, group_id: str) -> bool:
        """Whether the group actually spans both ECC systems."""
        return is_a_duplication(
            [
                (entry.source_system, entry.is_decommissioned)
                for entry in self.convergence_group(group_id)
            ]
        )
