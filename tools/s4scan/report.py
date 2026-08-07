"""Backlog reporting for the custom code workstream.

Turns raw findings into the artefacts the programme actually consumes:
a prioritised remediation backlog, an effort estimate that includes the
GxP validation overhead, and a machine readable feed for the programme
dashboard.

The estate spans two ECC source systems that merge into one S/4HANA
target, so the report also prices the merge itself: what convergence
costs against remediating both implementations separately, and what
falls away entirely because the objects only exist to bridge the two
systems.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .inventory import SOURCE_SYSTEMS, wave_rank
from .rules import Severity
from .scanner import ConvergenceGroup, ObjectResult, ScanResult

# One effort point is one engineer-hour of remediation work before the
# GxP validation multiplier is applied. Calibrated against the Wave 0
# pilot objects; revise once the first wave closes.
EFFORT_POINT_HOURS = 1.0
HOURS_PER_DAY = 7.5

# Resolving the functional divergence between two implementations of
# the same function - fit-gap, target design, agreeing one set of
# business rules - before either can be built. Paid once per group.
CONVERGENCE_DESIGN_POINTS = 13


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


@dataclass(frozen=True)
class ConvergenceEstimate:
    """What a convergence group costs, and what the merge saves.

    ``independent_days`` is what remediating every implementation in
    place would cost. ``converged_days`` builds one object instead: the
    largest implementation, plus the fit-gap that reconciles the others
    into it. The difference is only realised if the group is planned as
    one piece of work - remediate them separately and it is lost.

    Both figures cover the members still to build. A member that has
    already been rebuilt in S/4HANA is the target the others converge
    into, not work outstanding, so counting it would claim credit for
    effort the backlog reports as cleared.
    """

    group_id: str
    wave: str
    source_systems: tuple[str, ...]
    independent_days: float
    converged_days: float
    avoided_days: float

    @classmethod
    def from_group(cls, group: ConvergenceGroup) -> ConvergenceEstimate:
        outstanding = group.outstanding
        # A group with nothing left to build has no estimate to give,
        # and a zero would read as a merge that saves nothing rather
        # than as one already taken. Said here rather than left to the
        # caller, where it currently is: without it the failure is
        # `max() arg is an empty sequence`, which names neither the
        # group nor the reason.
        if not outstanding:
            raise ValueError(
                f"{group.group_id} has no outstanding members to estimate; "
                "it is already built or decommissioned"
            )
        member_days = [_days(obj.weighted_effort_points) for obj in outstanding]
        independent = sum(member_days)
        multiplier = max(obj.validation_multiplier for obj in outstanding)
        design = _days(CONVERGENCE_DESIGN_POINTS * multiplier)
        converged = max(member_days) + design
        return cls(
            group_id=group.group_id,
            wave=min((obj.wave for obj in outstanding), key=wave_rank),
            source_systems=tuple(sorted({obj.source_system for obj in outstanding})),
            independent_days=round(independent, 1),
            converged_days=round(converged, 1),
            # Signed. A group of one large implementation and one small
            # one can cost more converged than remediated in place: the
            # fit-gap that reconciles the small one into the large one
            # outweighs building it. Clamping at zero would present that
            # as a merge worth nothing rather than as one worth not
            # doing, which is a decision the table exists to inform.
            avoided_days=round(independent - converged, 1),
        )


def _days(effort_points: float) -> float:
    return effort_points * EFFORT_POINT_HOURS / HOURS_PER_DAY


def priority_score(obj: ObjectResult) -> tuple:
    """Backlog ordering: wave, then severity, then business exposure."""
    worst = obj.worst_severity
    severity_rank = worst.rank if worst else 99
    executions = obj.entry.monthly_executions if obj.entry else 0
    criticality = obj.entry.criticality_weight if obj.entry else 0
    return (
        wave_rank(obj.wave),
        severity_rank,
        -criticality,
        -executions,
        obj.object_name,
    )


def build_backlog(result: ScanResult) -> list[ObjectResult]:
    """Outstanding work, prioritised. Remediated objects drop out."""
    return sorted(result.outstanding(), key=priority_score)


def convergence_estimates(result: ScanResult) -> list[ConvergenceEstimate]:
    # Which groups carry a price is the scanner's answer, not a second
    # copy of the rule here: the caveat about groups reaching outside
    # the view is quoted against the same set, and two spellings of
    # "priced" would eventually disagree about which.
    return [
        ConvergenceEstimate.from_group(group)
        for group in result.priced_convergence_groups()
    ]


def groups_with_built_counterpart(result: ScanResult) -> list[ConvergenceGroup]:
    """Groups where the other system's implementation already exists."""
    return [
        group
        for group in result.convergence_groups()
        if group.has_built_counterpart
    ]


def count_by_source_system(objects: list[ObjectResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for obj in objects:
        counts[obj.source_system] = counts.get(obj.source_system, 0) + len(obj.findings)
    return dict(sorted(counts.items()))


def to_json(result: ScanResult) -> str:
    backlog = build_backlog(result)
    convergence = convergence_estimates(result)
    decommissioned = result.decommissioned()
    payload = {
        "summary": {
            "objects_scanned": len(result.objects),
            "objects_with_findings": len(result.objects_with_findings()),
            "objects_remediated": len(result.remediated()),
            "objects_decommissioned": len(decommissioned),
            "objects_outstanding": len(backlog),
            "effective_loc": result.scanned_loc,
            "findings": len(result.findings),
            "outstanding_findings": sum(len(obj.findings) for obj in backlog),
            "by_severity": count_by_severity(backlog),
            "by_rule": count_by_rule(backlog),
            "by_wave": count_by_wave(backlog),
            "by_source_system": count_by_source_system(backlog),
        },
        "effort": EffortEstimate.from_objects(backlog).__dict__,
        "cleared_effort": EffortEstimate.from_objects(result.remediated()).__dict__,
        "merge": {
            "source_systems": {
                system: SOURCE_SYSTEMS[system]
                for system in sorted(by_source_system(result))
            },
            "convergence_groups": [estimate.__dict__ for estimate in convergence],
            "convergence_avoided_days": round(
                sum(estimate.avoided_days for estimate in convergence), 1
            ),
            # Groups this scan flags but cannot cost, because it holds
            # only one side of them. Empty for a scan of the estate.
            "unpriced_convergence_groups": result.groups_beyond_scan(),
            "decommission_avoided_days": round(
                EffortEstimate.from_objects(decommissioned).engineer_days, 1
            ),
            "decommissioned": [
                {
                    "object_name": obj.object_name,
                    "source_system": obj.source_system,
                    "path": obj.path,
                    "convergence_group": obj.convergence_group,
                    "findings_not_remediated": len(obj.findings),
                }
                for obj in decommissioned
            ],
        },
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
                "source_system": obj.source_system,
                "path": obj.path,
                "wave": obj.wave,
                "gxp_class": obj.gxp_class,
                "convergence_group": obj.convergence_group,
                "disposition": obj.disposition,
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
    # Rule id breaks the tie. On count alone the order of equal rules
    # follows the order the files were walked, so adding an unrelated
    # source file reshuffles the table and fails the staleness gate
    # with a diff that says nothing.
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


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
    lines.append(
        "The estate spans two ECC source systems merging into one "
        "S/4HANA target, so an object has one of three dispositions. "
        "`retain` is remediated in place. `converge` is remediated "
        "jointly with its counterpart in the other system, because both "
        "become one object. `decommission` is never remediated - the "
        "object exists only to bridge the two systems and stops "
        "existing when they are one, so it is excluded from the backlog "
        "below and reported as avoided effort instead."
    )
    lines.append("")
    lines.append(
        "Findings found and findings outstanding are different numbers: an "
        "object with a `remediated_path` keeps its findings as cleared "
        "evidence but leaves the backlog. Every breakdown below, and every "
        "breakdown in the JSON, counts outstanding work only - the JSON key "
        "that reconciles with them is `outstanding_findings`, not `findings`."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    remediated = result.remediated()
    cleared = EffortEstimate.from_objects(remediated)
    outstanding_findings = sum(len(obj.findings) for obj in backlog)

    decommissioned = result.decommissioned()
    convergence = convergence_estimates(result)

    lines.append(f"| Objects scanned | {len(result.objects)} |")
    lines.append(f"| Objects remediated | {len(remediated)} |")
    lines.append(f"| Objects decommissioned at merge | {len(decommissioned)} |")
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

    if by_source_system(result):
        lines.extend(_source_system_section(result, backlog))
    lines.extend(
        _convergence_section(
            convergence,
            groups_with_built_counterpart(result),
            filtered=result.groups_extend_beyond_view(),
            unpriced=result.groups_beyond_scan(),
        )
    )
    lines.extend(_decommission_section(decommissioned))

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
    for wave in sorted({obj.wave for obj in backlog}, key=wave_rank):
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
        "| # | Object | System | Wave | GxP | Disposition | Owner | Blocker | "
        "Critical | Major | Minor | Engineer-days |"
    )
    lines.append(
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    for index, obj in enumerate(backlog, start=1):
        counts = obj.count_by_severity()
        days = round(_days(obj.weighted_effort_points), 1)
        owner = obj.entry.owner if obj.entry else "unknown"
        disposition = (
            f"{obj.disposition} ({obj.convergence_group})"
            if obj.convergence_group
            else obj.disposition
        )
        lines.append(
            f"| {index} | {obj.object_name} | {obj.source_system} | {obj.wave} | "
            f"{obj.gxp_class} | {disposition} | {owner} | {counts['blocker']} | "
            f"{counts['critical']} | {counts['major']} | {counts['minor']} | "
            f"{days} |"
        )
    lines.append("")

    lines.append("## Object detail")
    lines.append("")
    for obj in backlog:
        lines.append(f"### {obj.object_name}")
        lines.append("")
        lines.append(f"- Source: `{obj.path}` ({obj.source_system})")
        lines.append(f"- Wave: {obj.wave} | GxP class: {obj.gxp_class}")
        if obj.convergence_group:
            lines.append(
                f"- Disposition: {obj.disposition} | Convergence group: "
                f"{obj.convergence_group}"
            )
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


def by_source_system(result: ScanResult) -> dict[str, list[ObjectResult]]:
    """Only the real ECC systems.

    Scanning a path outside the inventory - `abap/remediated`, say -
    buckets its objects under "unassigned", which is not a system and
    must not be rendered as one.
    """
    return {
        system: objects
        for system, objects in result.by_source_system().items()
        if system in SOURCE_SYSTEMS
    }


def _source_system_section(
    result: ScanResult, backlog: list[ObjectResult]
) -> list[str]:
    lines = ["## Source systems", ""]
    lines.append(
        "Two ECC 6.0 systems converge on one S/4HANA target. Objects and "
        "findings below are the outstanding backlog, per system."
    )
    lines.append("")
    # "Objects scanned", not "in estate": under a filter this counts the
    # view, and the convergence section below it deliberately prices the
    # whole group. Two columns headed as estate figures, one of which is
    # not, is worse than one honest label.
    lines.append("| System | Description | Objects scanned | Outstanding | "
                 "Findings | Engineer-days |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for system, objects in by_source_system(result).items():
        outstanding = [obj for obj in backlog if obj.source_system == system]
        effort = EffortEstimate.from_objects(outstanding)
        findings = sum(len(obj.findings) for obj in outstanding)
        lines.append(
            f"| {system} | {SOURCE_SYSTEMS.get(system, system)} | "
            f"{len(objects)} | {len(outstanding)} | {findings} | "
            f"{effort.engineer_days} |"
        )
    lines.append("")
    return lines


def _convergence_section(
    convergence: list[ConvergenceEstimate],
    already_built: list[ConvergenceGroup] | None = None,
    filtered: bool = False,
    unpriced: list[str] | None = None,
) -> list[str]:
    if not convergence and not already_built and not unpriced:
        return []

    lines = ["## Convergence backlog", ""]
    if filtered:
        lines.append(
            "This is a filtered view. The groups below have a member "
            "outside it, and the days are the whole group's - a "
            "programme saving, realised once, not attributable to "
            "either system on its own."
        )
        lines.append("")
    lines.append(
        "Functions implemented separately in both ECC systems. Each "
        "group becomes one S/4HANA object, so it is planned and "
        "delivered once: `converged` is the largest implementation plus "
        "the fit-gap that reconciles the other into it, against "
        "`independent`, which is what remediating both in place would "
        "cost. The difference is only realised if the group is "
        "sequenced as one piece of work."
    )
    lines.append("")
    lines.append(
        "Both columns cover the implementations still to build. Where "
        "one system's object has already been rebuilt it is the target "
        "the other converges into, not outstanding work, so it is "
        "excluded - the saving was banked when it was built."
    )
    lines.append("")

    # An empty priced table with a zero total reads as "no saving
    # available", which is a different statement from "every group is
    # already settled".
    if convergence:
        lines.append(
            "| Group | Wave | Systems | Independent days | Converged days | Avoided |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for estimate in convergence:
            systems = ", ".join(estimate.source_systems)
            lines.append(
                f"| {estimate.group_id} | {estimate.wave} | {systems} | "
                f"{estimate.independent_days} | {estimate.converged_days} | "
                f"{estimate.avoided_days} |"
            )
        total_avoided = round(sum(e.avoided_days for e in convergence), 1)
        lines.append(f"| **Total** | | | | | **{total_avoided}** |")
        lines.append("")

        costlier = [e for e in convergence if e.avoided_days < 0]
        if costlier:
            lines.append(
                f"{', '.join(f'`{e.group_id}`' for e in costlier)} "
                f"{'costs' if len(costlier) == 1 else 'cost'} more converged "
                "than remediated in place: the smaller implementation is "
                "cheaper to rebuild than to reconcile into the larger one. "
                "The duplication is still real - it is the merge that does "
                "not pay for itself."
            )
            lines.append("")

    # A scan of part of the estate still raises SI-CONV-001, because
    # the duplication is a fact about the inventory rather than about
    # what was scanned. Pricing the merge off the one member in view
    # would be a different claim, and a wrong one.
    if unpriced:
        lines.append(
            f"{', '.join(f'`{group}`' for group in unpriced)} "
            f"{'is' if len(unpriced) == 1 else 'are'} flagged as "
            "duplicated but not priced here: the other implementation is "
            "outside the scanned path. Scan the whole estate to cost the "
            "merge."
        )
        lines.append("")

    if already_built:
        lines.append(
            "These groups have no choice left to make: the other "
            "system's implementation is already in S/4HANA, so the "
            "outstanding object folds into it rather than being "
            "remediated in place. `SI-CONV-001` still fires on it."
        )
        lines.append("")
        lines.append("| Group | Already built | Folds into it |")
        lines.append("| --- | --- | --- |")
        for group in already_built:
            built = ", ".join(
                f"{obj.object_name} ({obj.source_system})"
                for obj in group.objects
                if obj.is_remediated
            )
            folding = ", ".join(
                f"{obj.object_name} ({obj.source_system})"
                for obj in group.outstanding
            )
            lines.append(f"| {group.group_id} | {built} | {folding or '-'} |")
        lines.append("")

    return lines


def _decommission_section(decommissioned: list[ObjectResult]) -> list[str]:
    if not decommissioned:
        return []

    effort = EffortEstimate.from_objects(decommissioned)
    lines = ["## Decommissioned at merge", ""]
    lines.append(
        "These objects exist only because the two companies run on two "
        "systems. In one S/4HANA client the intercompany transfer "
        "becomes an internal movement, so the interface, its partner "
        "profiles and its reconciliation job all go away. They carry "
        f"{sum(len(obj.findings) for obj in decommissioned)} findings "
        f"that will never be remediated - {effort.engineer_days} "
        "engineer-days avoided, provided the estate is sized against "
        "the merged target rather than object by object."
    )
    lines.append("")
    lines.append("| Object | System | Findings dropped | Engineer-days avoided |")
    lines.append("| --- | --- | --- | --- |")
    for obj in decommissioned:
        days = round(_days(obj.weighted_effort_points), 1)
        lines.append(
            f"| {obj.object_name} | {obj.source_system} | "
            f"{len(obj.findings)} | {days} |"
        )
    lines.append("")
    return lines


def _rule_for(result: ScanResult, rule_id: str):
    for finding in result.findings:
        if finding.rule_id == rule_id:
            return finding.rule
    raise KeyError(rule_id)
