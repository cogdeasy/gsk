"""Scan engine: apply the rule set to the ABAP estate."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import parser
from .inventory import RETAIN, Inventory, InventoryEntry
from .rules import OBJECT_RULES, RULES, Rule, RuleFilter, Severity

ABAP_SUFFIXES = (".abap",)
TEST_SUFFIX = ".testclasses.abap"


@dataclass(frozen=True)
class Finding:
    rule: Rule
    path: str
    line: int
    evidence: str
    statement: str

    @property
    def rule_id(self) -> str:
        return self.rule.id

    @property
    def severity(self) -> Severity:
        return self.rule.severity

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule.id,
            "title": self.rule.title,
            "category": self.rule.category.value,
            "severity": self.rule.severity.value,
            "effort_points": self.rule.effort_points,
            "path": self.path,
            "line": self.line,
            "evidence": self.evidence,
            "statement": self.statement,
            "guidance": self.rule.guidance,
            "sap_reference": self.rule.sap_reference,
        }


@dataclass
class ObjectResult:
    path: str
    object_name: str
    entry: InventoryEntry | None
    loc: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def raw_effort_points(self) -> int:
        return sum(finding.rule.effort_points for finding in self.findings)

    @property
    def validation_multiplier(self) -> float:
        return self.entry.validation_multiplier if self.entry else 1.0

    @property
    def weighted_effort_points(self) -> float:
        return round(self.raw_effort_points * self.validation_multiplier, 1)

    @property
    def wave(self) -> str:
        return self.entry.wave if self.entry else "unassigned"

    @property
    def gxp_class(self) -> str:
        return self.entry.gxp_class if self.entry else "unclassified"

    @property
    def source_system(self) -> str:
        return self.entry.source_system if self.entry else "unassigned"

    @property
    def convergence_group(self) -> str:
        return self.entry.convergence_group if self.entry else ""

    @property
    def disposition(self) -> str:
        return self.entry.disposition if self.entry else RETAIN

    @property
    def is_decommissioned(self) -> bool:
        return self.entry.is_decommissioned if self.entry else False

    @property
    def is_remediated(self) -> bool:
        return self.entry.is_remediated if self.entry else False

    @property
    def remediated_path(self) -> str:
        return self.entry.remediated_path if self.entry else ""

    @property
    def worst_severity(self) -> Severity | None:
        if not self.findings:
            return None
        return min((finding.severity for finding in self.findings), key=lambda s: s.rank)

    def count_by_severity(self) -> dict[str, int]:
        counts = {severity.value: 0 for severity in Severity}
        for finding in self.findings:
            counts[finding.severity.value] += 1
        return counts


@dataclass
class ConvergenceGroup:
    """Objects in different ECC systems that become one S/4HANA object.

    The two source systems each grew their own implementation of the
    same business function. Remediating both and migrating both would
    carry the duplication into the target, so the group is planned and
    delivered as a single object: the fit-gap on the functional
    divergence is real work, but it is paid once.
    """

    group_id: str
    objects: list[ObjectResult] = field(default_factory=list)

    @property
    def source_systems(self) -> list[str]:
        return sorted({obj.source_system for obj in self.objects})

    @property
    def is_cross_system(self) -> bool:
        return len(self.source_systems) > 1

    @property
    def is_decommissioned(self) -> bool:
        """The pair disappears at the merge rather than becoming one object.

        Interfaces between the two systems are the usual case: once both
        sides are in the same client there is nothing left to interface.
        """
        return all(obj.is_decommissioned for obj in self.objects)

    @property
    def findings(self) -> list[Finding]:
        return [finding for obj in self.objects for finding in obj.findings]

    @property
    def wave(self) -> str:
        """The group lands in the earliest wave any member belongs to."""
        return min(obj.wave for obj in self.objects)

    @property
    def validation_multiplier(self) -> float:
        return max(obj.validation_multiplier for obj in self.objects)

    @property
    def is_remediated(self) -> bool:
        return all(obj.is_remediated for obj in self.objects)

    @property
    def outstanding(self) -> list[ObjectResult]:
        """Members still to build.

        A member that already has an S/4HANA successor is not work: it
        is the target the others converge into. Pricing the group over
        every member would claim credit for it twice.
        """
        return [
            obj
            for obj in self.objects
            if not obj.is_remediated and not obj.is_decommissioned
        ]

    @property
    def has_built_counterpart(self) -> bool:
        """One side is already in S/4HANA, so there is nothing to choose.

        The remaining implementation still must not be remediated in
        place - it folds into the object that exists - but the merge
        saving was banked when that object was built.
        """
        return len(self.outstanding) < 2 and any(
            obj.is_remediated for obj in self.objects
        )


@dataclass
class ScanResult:
    objects: list[ObjectResult] = field(default_factory=list)
    # Everything scanned, before a view filter such as `--system`
    # narrowed `objects`. A convergence group is cross-system by
    # definition, so grouping over the narrowed list would dissolve
    # every group.
    estate: list[ObjectResult] | None = None

    @property
    def is_filtered(self) -> bool:
        return self.estate is not None

    def restrict_to(self, objects: list[ObjectResult]) -> None:
        """Narrow the view, remembering the estate it was taken from."""
        if self.estate is None:
            self.estate = list(self.objects)
        self.objects = objects

    @property
    def findings(self) -> list[Finding]:
        return [finding for obj in self.objects for finding in obj.findings]

    @property
    def scanned_loc(self) -> int:
        return sum(obj.loc for obj in self.objects)

    def objects_with_findings(self) -> list[ObjectResult]:
        return [obj for obj in self.objects if obj.findings]

    def outstanding(self) -> list[ObjectResult]:
        """Objects still to remediate.

        Excludes objects with an S/4HANA successor, and objects the
        merge decommissions - those are never remediated, so counting
        them as backlog overstates the programme.
        """
        return [
            obj
            for obj in self.objects_with_findings()
            if not obj.is_remediated and not obj.is_decommissioned
        ]

    def remediated(self) -> list[ObjectResult]:
        return [obj for obj in self.objects if obj.is_remediated]

    def decommissioned(self) -> list[ObjectResult]:
        """Objects that stop existing when the two systems become one."""
        return [obj for obj in self.objects if obj.is_decommissioned]

    def by_source_system(self) -> dict[str, list[ObjectResult]]:
        grouped: dict[str, list[ObjectResult]] = {}
        for obj in self.objects:
            grouped.setdefault(obj.source_system, []).append(obj)
        return dict(sorted(grouped.items()))

    def convergence_groups(self) -> list[ConvergenceGroup]:
        """Cross-system duplicates, in wave then group order.

        Grouped over the whole estate, then narrowed to the groups the
        current view can see. Grouping over a `--system` view instead
        would leave one member in every group, so nothing would be
        cross-system and the report would flag each object as a
        duplicate while stating that no duplicates exist.
        """
        visible = {obj.path for obj in self.objects}
        grouped: dict[str, ConvergenceGroup] = {}
        for obj in self.estate if self.estate is not None else self.objects:
            if not obj.convergence_group:
                continue
            group = grouped.setdefault(
                obj.convergence_group, ConvergenceGroup(obj.convergence_group)
            )
            group.objects.append(obj)
        return sorted(
            (
                group
                for group in grouped.values()
                if group.is_cross_system
                and any(obj.path in visible for obj in group.objects)
            ),
            key=lambda group: (group.wave, group.group_id),
        )

    def has_severity(self, severity: Severity) -> bool:
        """Gate on outstanding work only; remediated objects are done."""
        return any(
            finding.severity.rank <= severity.rank
            for obj in self.outstanding()
            for finding in obj.findings
        )


def object_name_for(path: Path) -> str:
    """Derive the ABAP object name from the file name."""
    name = path.name
    for suffix in (".prog.abap", ".fugr.abap", ".clas.abap", ".incl.abap", ".exit.abap"):
        if name.endswith(suffix):
            return name[: -len(suffix)].upper()
    return path.stem.upper()


def discover(root: str | Path) -> list[Path]:
    """Find scannable ABAP sources, skipping test classes."""
    root_path = Path(root)
    if root_path.is_file():
        return [root_path]
    found = [
        path
        for path in sorted(root_path.rglob("*"))
        if path.suffix in ABAP_SUFFIXES and not path.name.endswith(TEST_SUFFIX)
    ]
    return found


def has_test_class(path: Path, test_roots: list[Path]) -> bool:
    """Test evidence is the file named after the object, and only that.

    Prefix matching would let ZGSK_MM_STOCK.testclasses.abap stand as
    the evidence for ZGSK_MM_STOCK_OVERVIEW, which is exactly the kind
    of claim a GxP audit rejects.
    """
    expected = f"{object_name_for(path).lower()}{TEST_SUFFIX}"
    return any(
        candidate.name.lower() == expected
        for root in test_roots
        if root.exists()
        for candidate in root.rglob(f"*{TEST_SUFFIX}")
    )


def scan_file(
    path: str | Path,
    inventory: Inventory | None = None,
    rule_filter: RuleFilter | None = None,
    test_roots: list[Path] | None = None,
) -> ObjectResult:
    file_path = Path(path)
    source = parser.read(str(file_path))
    entry = inventory.for_path(file_path) if inventory else None
    rule_filter = rule_filter or RuleFilter()

    result = ObjectResult(
        path=file_path.as_posix(),
        object_name=object_name_for(file_path),
        entry=entry,
        loc=source.effective_loc,
    )

    for statement in source.statements:
        for rule in RULES:
            if not rule_filter.applies(rule):
                continue
            evidence = rule.evidence(statement)
            if evidence is None:
                continue
            result.findings.append(
                Finding(
                    rule=rule,
                    path=result.path,
                    line=statement.line,
                    evidence=evidence,
                    statement=_truncate(statement.text),
                )
            )

    _apply_object_rules(result, file_path, rule_filter, test_roots or [], inventory)
    result.findings.sort(key=lambda finding: (finding.line, finding.rule_id))
    return result


def _apply_object_rules(
    result: ObjectResult,
    file_path: Path,
    rule_filter: RuleFilter,
    test_roots: list[Path],
    inventory: Inventory | None = None,
) -> None:
    for rule in OBJECT_RULES:
        if not rule_filter.applies(rule):
            continue
        if rule.id == "SI-CONV-001":
            if result.entry is None or not result.entry.converges:
                continue
            # `converges` and `is_decommissioned` are mutually
            # exclusive dispositions today, but relying on that leaves
            # the invariant somewhere else in the file.
            if result.is_remediated or result.is_decommissioned:
                continue
            # Only a group with a member in the other system is a
            # duplication. Without this the finding would contradict
            # the convergence backlog, which drops single-system
            # groups.
            if inventory is not None and not inventory.is_cross_system_group(
                result.entry.convergence_group
            ):
                continue
            result.findings.append(
                Finding(
                    rule=rule,
                    path=result.path,
                    line=1,
                    evidence=result.entry.convergence_group,
                    statement=(
                        f"{result.object_name} ({result.entry.source_system}) "
                        f"duplicates convergence group "
                        f"{result.entry.convergence_group}"
                    ),
                )
            )
        if rule.id == "SI-GXP-001":
            if result.entry is None or not result.entry.is_gxp:
                continue
            if has_test_class(file_path, test_roots):
                continue
            result.findings.append(
                Finding(
                    rule=rule,
                    path=result.path,
                    line=1,
                    evidence=result.gxp_class,
                    statement=f"{result.object_name} ({result.entry.validation_package})",
                )
            )


def scan(
    roots: list[str | Path],
    inventory: Inventory | None = None,
    rule_filter: RuleFilter | None = None,
    test_roots: list[str | Path] | None = None,
) -> ScanResult:
    resolved_test_roots = [Path(root) for root in (test_roots or roots)]
    result = ScanResult()
    for root in roots:
        for path in discover(root):
            result.objects.append(
                scan_file(
                    path,
                    inventory=inventory,
                    rule_filter=rule_filter,
                    test_roots=resolved_test_roots,
                )
            )
    return result


def _truncate(text: str, limit: int = 160) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3] + "..."
