"""Scan engine: apply the rule set to the ABAP estate."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import parser
from .inventory import Inventory, InventoryEntry
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
class ScanResult:
    objects: list[ObjectResult] = field(default_factory=list)

    @property
    def findings(self) -> list[Finding]:
        return [finding for obj in self.objects for finding in obj.findings]

    @property
    def scanned_loc(self) -> int:
        return sum(obj.loc for obj in self.objects)

    def count_by_severity(self) -> dict[str, int]:
        counts = {severity.value: 0 for severity in Severity}
        for finding in self.findings:
            counts[finding.severity.value] += 1
        return counts

    def count_by_rule(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.rule_id] = counts.get(finding.rule_id, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: -item[1]))

    def count_by_wave(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for obj in self.objects:
            counts[obj.wave] = counts.get(obj.wave, 0) + len(obj.findings)
        return dict(sorted(counts.items()))

    def objects_with_findings(self) -> list[ObjectResult]:
        return [obj for obj in self.objects if obj.findings]

    def outstanding(self) -> list[ObjectResult]:
        """Objects still to remediate: findings and no S/4HANA successor."""
        return [obj for obj in self.objects_with_findings() if not obj.is_remediated]

    def remediated(self) -> list[ObjectResult]:
        return [obj for obj in self.objects if obj.is_remediated]

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
    stem = object_name_for(path).lower()
    for root in test_roots:
        if not root.exists():
            continue
        for candidate in root.rglob(f"*{TEST_SUFFIX}"):
            if candidate.name.lower().startswith(stem):
                return True
            # A remediated class may carry the tests for its report.
            if stem.startswith(candidate.name.lower().split(".")[0]):
                return True
    return False


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

    _apply_object_rules(result, file_path, rule_filter, test_roots or [])
    result.findings.sort(key=lambda finding: (finding.line, finding.rule_id))
    return result


def _apply_object_rules(
    result: ObjectResult,
    file_path: Path,
    rule_filter: RuleFilter,
    test_roots: list[Path],
) -> None:
    for rule in OBJECT_RULES:
        if not rule_filter.applies(rule):
            continue
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
