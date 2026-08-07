"""Command line entry point for the custom code readiness scanner."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .inventory import SOURCE_SYSTEMS, Inventory
from .report import (
    build_backlog,
    by_source_system,
    convergence_estimates,
    count_by_rule,
    count_by_severity,
    to_json,
    to_markdown,
)
from .rules import RuleFilter, Severity, all_rules
from .scanner import scan

DEFAULT_SOURCE = "abap/ecc"
DEFAULT_INVENTORY = "estate/inventory.csv"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="s4scan",
        description=(
            "Scan the ABAP custom code estate for S/4HANA simplification "
            "items and clean-core violations."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="scan sources and report")
    scan_parser.add_argument(
        "paths", nargs="*", default=[DEFAULT_SOURCE],
        help=f"source roots to scan (default: {DEFAULT_SOURCE})",
    )
    scan_parser.add_argument(
        "--inventory", default=DEFAULT_INVENTORY,
        help=f"object inventory CSV (default: {DEFAULT_INVENTORY})",
    )
    scan_parser.add_argument(
        "--test-root", action="append", default=[],
        help="directory searched for ABAP Unit test classes (repeatable)",
    )
    scan_parser.add_argument(
        "--format", choices=("markdown", "json", "summary"), default="summary",
    )
    scan_parser.add_argument("--out", help="write the report to this file")
    scan_parser.add_argument(
        "--wave", help="restrict the scan to objects in this wave",
    )
    scan_parser.add_argument(
        "--system", choices=sorted(SOURCE_SYSTEMS),
        help="restrict the scan to one ECC source system",
    )
    scan_parser.add_argument(
        "--rule", action="append", default=[], help="only run these rule ids",
    )
    scan_parser.add_argument(
        "--exclude-rule", action="append", default=[], help="skip these rule ids",
    )
    scan_parser.add_argument(
        "--fail-on", choices=[severity.value for severity in Severity],
        help="exit non-zero when a finding of this severity or worse exists",
    )

    subparsers.add_parser("rules", help="list the rule catalogue")

    return parser


def _list_rules() -> int:
    print(f"{'RULE':<12} {'SEVERITY':<9} {'CATEGORY':<18} TITLE")
    for rule in all_rules():
        print(
            f"{rule.id:<12} {rule.severity.value:<9} "
            f"{rule.category.value:<18} {rule.title}"
        )
    return 0


def _run_scan(args: argparse.Namespace) -> int:
    inventory = None
    inventory_path = Path(args.inventory)
    if inventory_path.exists():
        inventory = Inventory.load(inventory_path)
    elif args.inventory != DEFAULT_INVENTORY:
        print(f"inventory not found: {inventory_path}", file=sys.stderr)
        return 2

    rule_filter = RuleFilter(
        include=set(args.rule), exclude=set(args.exclude_rule)
    )
    test_roots = args.test_root or ["abap"]

    result = scan(
        roots=list(args.paths),
        inventory=inventory,
        rule_filter=rule_filter,
        test_roots=list(test_roots),
    )

    # A wave is a plan, and a group is planned as one piece of work, so
    # a group outside the wave is genuinely not this scan's business -
    # narrow the estate itself. A system is not a plan: the same group
    # spans both, so `--system` narrows only the view.
    if args.wave:
        result.objects = [obj for obj in result.objects if obj.wave == args.wave]

    if args.system:
        result.restrict_to(
            [obj for obj in result.objects if obj.source_system == args.system]
        )

    if args.format == "json":
        output = to_json(result)
    elif args.format == "markdown":
        output = to_markdown(result)
    else:
        output = _summary(result)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"report written to {out_path}")
    else:
        print(output)

    if args.fail_on:
        threshold = Severity(args.fail_on)
        if result.has_severity(threshold):
            print(
                f"findings at or above severity '{threshold.value}' present",
                file=sys.stderr,
            )
            return 1

    return 0


def _summary(result) -> str:
    backlog = build_backlog(result)
    counts = count_by_severity(backlog)
    decommissioned = result.decommissioned()
    lines = [
        f"objects scanned       : {len(result.objects)}",
        f"objects remediated    : {len(result.remediated())}",
        f"objects decommissioned: {len(decommissioned)}",
        f"objects outstanding   : {len(backlog)}",
        f"effective LOC         : {result.scanned_loc}",
        f"findings outstanding  : {sum(len(obj.findings) for obj in backlog)}",
    ]
    for severity, count in counts.items():
        lines.append(f"  {severity:<9}: {count}")

    by_system = by_source_system(result)
    if by_system:
        lines.append("")
        lines.append("source systems:")
        for system, objects in by_system.items():
            outstanding = [obj for obj in backlog if obj.source_system == system]
            lines.append(
                f"  {system:<5} {len(objects):>3} objects, "
                f"{len(outstanding):>3} outstanding"
            )

    convergence = convergence_estimates(result)
    if convergence:
        avoided = round(sum(e.avoided_days for e in convergence), 1)
        lines.append("")
        lines.append(
            f"convergence groups    : {len(convergence)} "
            f"({avoided} engineer-days avoided by building one object)"
        )
        if result.is_filtered:
            lines.append(
                "                        whole-group days; the saving is "
                "the programme's, not this view's"
            )

    lines.append("")
    lines.append("top rules:")
    for rule_id, count in list(count_by_rule(backlog).items())[:10]:
        lines.append(f"  {rule_id:<12} {count}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "rules":
        return _list_rules()
    return _run_scan(args)


if __name__ == "__main__":
    raise SystemExit(main())
