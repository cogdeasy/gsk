"""Command line entry point for the wave data migration pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import pipeline, reconcile
from .cleanse import Action
from .extract import ExtractError
from .mapping import MappingError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datamig",
        description=(
            "Run the ECC to S/4HANA wave migration pipeline and produce "
            "the load files and reconciliation evidence."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run the full pipeline")
    run_parser.add_argument("--wave", default="wave0")
    run_parser.add_argument(
        "--source", help="wave extract directory (default: data/<wave>)"
    )
    run_parser.add_argument(
        "--out", help="output directory (default: out/<wave>)"
    )
    run_parser.add_argument(
        "--format", choices=("summary", "markdown", "json"), default="summary"
    )
    run_parser.add_argument(
        "--dry-run", action="store_true", help="do not write load files"
    )
    run_parser.add_argument(
        "--fail-on-reject", action="store_true",
        help="exit non-zero when any record is held back from the load",
    )

    return parser


def _summary(result: pipeline.PipelineResult) -> str:
    reconciliation = result.reconciliation
    lines = [f"wave: {result.wave}", ""]
    if reconciliation.source_systems:
        lines.append(f"source systems: {', '.join(reconciliation.source_systems)}")
        lines.append("")
    lines.append(
        f"{'object':<14}{'extracted':>10}{'rejected':>10}{'merged':>8}"
        f"{'loaded':>8}{'warn':>7}"
    )
    for count in reconciliation.counts:
        lines.append(
            f"{count.object_name:<14}{count.extracted:>10}{count.rejected:>10}"
            f"{count.merged:>8}{count.loaded:>8}{count.warnings:>7}"
        )
    lines.append("")
    partners = result.business_partners
    lines.append(
        f"business partners created: {len(partners.partners)} "
        f"(merged {partners.merged_count} source records, "
        f"{len(partners.cross_system_partners)} held in both systems)"
    )
    if result.product_result:
        lines.append(
            f"products created: {len(result.product_result.products)} "
            f"(harmonised {result.product_result.merged_count} duplicate "
            "materials away)"
        )
    failed = reconciliation.failed_checks
    lines.append(
        f"reconciliation: {'PASS' if reconciliation.passed else 'FAIL'} "
        f"({len(failed)} failed of {len(reconciliation.checks)} checks)"
    )
    for check in failed:
        lines.append(
            f"  FAIL {check.id}: source={check.source_value} "
            f"target={check.target_value}"
        )
    rejects = [
        issue for issue in result.all_issues if issue.action is Action.REJECT
    ]
    if rejects:
        lines.append("")
        lines.append("held back from the load:")
        for issue in rejects:
            lines.append(f"  {issue.rule_id} {issue.key}: {issue.message}")
    if result.written:
        lines.append("")
        lines.append(f"artefacts written to {result.out_dir}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    source = Path(args.source) if args.source else Path("data") / args.wave
    out_dir = Path(args.out) if args.out else Path("out") / args.wave

    try:
        result = pipeline.run(
            wave=args.wave,
            source_dir=source,
            out_dir=out_dir,
            write_files=not args.dry_run,
        )
    # MappingError means cleansing let through something mapping had to
    # refuse - unreachable while the two agree, and a traceback is the
    # wrong way to tell an operator their wave stopped when it happens.
    except (ExtractError, MappingError) as error:
        print(str(error), file=sys.stderr)
        return 2

    if args.format == "json":
        print(reconcile.to_json(result.reconciliation))
    elif args.format == "markdown":
        print(reconcile.to_markdown(result.reconciliation))
    else:
        print(_summary(result))

    if not result.reconciliation.passed:
        return 1
    if args.fail_on_reject and result.rejected_count:
        print(
            f"{result.rejected_count} records held back from the load",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
