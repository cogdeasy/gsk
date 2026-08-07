"""Backlog reporting for the custom code workstream.

Turns raw findings into the artefacts the programme actually consumes:
a prioritised remediation backlog, an effort estimate that includes the
GxP validation overhead, and a machine readable feed for the programme
dashboard.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .rules import Severity
from .scanner import ObjectResult, ScanResult

# One effort point is one engineer-hour of remediation work before the
# GxP validation multiplier is applied. Calibrated against the Wave 0
# pilot objects; revise once the first wave closes.
EFFORT_POINT_HOURS = 1.0
HOURS_PER_DAY = 7.5

WAVE_ORDER = {"wave0": 0, "wave1": 1, "wave2": 2, "unassigned": 9}


@dataclass(frozen=True)
class EffortEstimate:
    raw_points: float
    weighted_points: float
    engineer_days: float
    validation_overhead_days: float

    @classmethod
    def from_objects(cls, objects: list[ObjectResult]) -> EffortEstimate:
        raw = sum(obj.raw_effort_points for obj in objects)
        weighted = sum(obj.weighted_effort_points for obj in objects)
        days = weighted * EFFORT_POINT_HOURS / HOURS_PER_DAY
        overhead = (weighted - raw) * EFFORT_POINT_HOURS / HOURS_PER_DAY
        return cls(
            raw_points=round(raw, 1),
            weighted_points=round(weighted, 1),
            engineer_days=round(days, 1),
            validation_overhead_days=round(overhead, 1),
        )


def priority_score(obj: ObjectResult) -> tuple:
    """Backlog ordering: wave, then severity, then business exposure."""
    worst = obj.worst_severity
    severity_rank = worst.rank if worst else 99
    executions = obj.entry.monthly_executions if obj.entry else 0
    criticality = obj.entry.criticality_weight if obj.entry else 0
    return (
        WAVE_ORDER.get(obj.wave, 9),
        severity_rank,
        -criticality,
        -executions,
        obj.object_name,
    )


def build_backlog(result: ScanResult) -> list[ObjectResult]:
    """Outstanding work, prioritised. Remediated objects drop out."""
    return sorted(result.outstanding(), key=priority_score)


def to_json(result: ScanResult) -> str:
    backlog = build_backlog(result)
    payload = {
        "summary": {
            "objects_scanned": len(result.objects),
            "objects_with_findings": len(result.objects_with_findings()),
            "objects_remediated": len(result.remediated()),
            "objects_outstanding": len(backlog),
            "effective_loc": result.scanned_loc,
            "findings": len(result.findings),
            "outstanding_findings": sum(len(obj.findings) for obj in backlog),
            "by_severity": count_by_severity(backlog),
            "by_rule": count_by_rule(backlog),
            "by_wave": count_by_wave(backlog),
        },
        "effort": EffortEstimate.from_objects(backlog).__dict__,
        "cleared_effort": EffortEstimate.from_objects(result.remediated()).__dict__,
        "remediated": [
            {
                "object_name": obj.object_name,
                "path": obj.path,
                "remediated_path": obj.remediated_path,
                "wave": obj.wave,
                "cleared_findings": len(obj.findings),
            }
            for obj in result.remediated()
        ],
        "objects": [
            {
                "object_name": obj.object_name,
                "path": obj.path,
                "wave": obj.wave,
                "gxp_class": obj.gxp_class,
                "owner": obj.entry.owner if obj.entry else None,
                "validation_package": (
                    obj.entry.validation_package if obj.entry else None
                ),
                "effective_loc": obj.loc,
                "raw_effort_points": obj.raw_effort_points,
                "weighted_effort_points": obj.weighted_effort_points,
                "by_severity": obj.count_by_severity(),
                "findings": [finding.as_dict() for finding in obj.findings],
            }
            for obj in backlog
        ],
    }
    return json.dumps(payload, indent=2)


def count_by_wave(objects: list[ObjectResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for obj in objects:
        counts[obj.wave] = counts.get(obj.wave, 0) + len(obj.findings)
    return dict(sorted(counts.items()))


def count_by_severity(objects: list[ObjectResult]) -> dict[str, int]:
    counts = {severity.value: 0 for severity in Severity}
    for obj in objects:
        for finding in obj.findings:
            counts[finding.severity.value] += 1
    return counts


def count_by_rule(objects: list[ObjectResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for obj in objects:
        for finding in obj.findings:
            counts[finding.rule_id] = counts.get(finding.rule_id, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def to_markdown(result: ScanResult) -> str:
    backlog = build_backlog(result)
    effort = EffortEstimate.from_objects(backlog)
    severity_counts = count_by_severity(backlog)

    lines: list[str] = []
    lines.append("# Custom code remediation backlog")
    lines.append("")
    lines.append(
        "Generated by `s4scan` from the ABAP estate in this repository. "
        "Every finding names the S/4HANA target pattern; the effort "
        "estimate includes the GxP validation multiplier held in the "
        "object inventory."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    remediated = result.remediated()
    cleared = EffortEstimate.from_objects(remediated)
    outstanding_findings = sum(len(obj.findings) for obj in backlog)

    lines.append(f"| Objects scanned | {len(result.objects)} |")
    lines.append(f"| Objects remediated | {len(remediated)} |")
    lines.append(f"| Objects outstanding | {len(backlog)} |")
    lines.append(f"| Effective lines of code | {result.scanned_loc} |")
    lines.append(f"| Findings outstanding | {outstanding_findings} |")
    for severity in Severity:
        lines.append(
            f"| Findings - {severity.value} | {severity_counts[severity.value]} |"
        )
    lines.append(f"| Raw effort points | {effort.raw_points} |")
    lines.append(
        f"| Effort points incl. validation | {effort.weighted_points} |"
    )
    lines.append(f"| Engineer-days outstanding | {effort.engineer_days} |")
    lines.append(
        f"| of which GxP validation overhead | {effort.validation_overhead_days} |"
    )
    lines.append(f"| Engineer-days cleared | {cleared.engineer_days} |")
    lines.append("")

    if remediated:
        lines.append("## Remediated")
        lines.append("")
        lines.append(
            "Objects with an S/4HANA implementation and ABAP Unit "
            "evidence. The ECC source is retained as the before/after "
            "pair for the validation package; its findings are excluded "
            "from the backlog below."
        )
        lines.append("")
        lines.append("| Object | Wave | S/4HANA implementation | Findings cleared |")
        lines.append("| --- | --- | --- | --- |")
        for obj in remediated:
            lines.append(
                f"| {obj.object_name} | {obj.wave} | `{obj.remediated_path}` | "
                f"{len(obj.findings)} |"
            )
        lines.append("")

    lines.append("## Findings by wave")
    lines.append("")
    lines.append("| Wave | Objects | Findings | Engineer-days |")
    lines.append("| --- | --- | --- | --- |")
    for wave in sorted({obj.wave for obj in backlog}, key=lambda w: WAVE_ORDER.get(w, 9)):
        wave_objects = [obj for obj in backlog if obj.wave == wave]
        wave_effort = EffortEstimate.from_objects(wave_objects)
        wave_findings = sum(len(obj.findings) for obj in wave_objects)
        lines.append(
            f"| {wave} | {len(wave_objects)} | {wave_findings} | "
            f"{wave_effort.engineer_days} |"
        )
    lines.append("")

    lines.append("## Findings by rule")
    lines.append("")
    lines.append("| Rule | Title | Severity | Count |")
    lines.append("| --- | --- | --- | --- |")
    for rule_id, count in count_by_rule(backlog).items():
        rule = _rule_for(result, rule_id)
        lines.append(f"| {rule_id} | {rule.title} | {rule.severity.value} | {count} |")
    lines.append("")

    lines.append("## Prioritised backlog")
    lines.append("")
    lines.append(
        "| # | Object | Wave | GxP | Owner | Blocker | Critical | Major | "
        "Minor | Engineer-days |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for index, obj in enumerate(backlog, start=1):
        counts = obj.count_by_severity()
        days = round(obj.weighted_effort_points * EFFORT_POINT_HOURS / HOURS_PER_DAY, 1)
        owner = obj.entry.owner if obj.entry else "unknown"
        lines.append(
            f"| {index} | {obj.object_name} | {obj.wave} | {obj.gxp_class} | "
            f"{owner} | {counts['blocker']} | {counts['critical']} | "
            f"{counts['major']} | {counts['minor']} | {days} |"
        )
    lines.append("")

    lines.append("## Object detail")
    lines.append("")
    for obj in backlog:
        lines.append(f"### {obj.object_name}")
        lines.append("")
        lines.append(f"- Source: `{obj.path}`")
        lines.append(f"- Wave: {obj.wave} | GxP class: {obj.gxp_class}")
        if obj.entry:
            lines.append(
                f"- Owner: {obj.entry.owner} | Validation package: "
                f"{obj.entry.validation_package} | "
                f"{obj.entry.monthly_executions} executions/month"
            )
        lines.append("")
        lines.append("| Line | Rule | Severity | Evidence | Statement |")
        lines.append("| --- | --- | --- | --- | --- |")
        for finding in obj.findings:
            statement = finding.statement.replace("|", "\\|")
            lines.append(
                f"| {finding.line} | {finding.rule_id} | "
                f"{finding.severity.value} | `{finding.evidence}` | "
                f"`{statement}` |"
            )
        lines.append("")

    lines.append("## Target patterns")
    lines.append("")
    seen: set[str] = set()
    for finding in (f for obj in backlog for f in obj.findings):
        if finding.rule_id in seen:
            continue
        seen.add(finding.rule_id)
        lines.append(f"### {finding.rule_id} - {finding.rule.title}")
        lines.append("")
        lines.append(f"- Severity: {finding.severity.value}")
        lines.append(f"- SAP topic: {finding.rule.sap_reference}")
        lines.append(f"- Target: {finding.rule.guidance}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _rule_for(result: ScanResult, rule_id: str):
    for finding in result.findings:
        if finding.rule_id == rule_id:
            return finding.rule
    raise KeyError(rule_id)
