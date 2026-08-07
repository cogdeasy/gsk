"""Command line entry point for the wave data migration pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import pipeline, reconcile
from .cleanse import Action
from .extract import ExtractError


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
    lines = [f"wave: {result.wave}", ""]
    lines.append(f"{'object':<14}{'extracted':>10}{'rejected':>10}{'loaded':>8}{'warn':>7}")
    for count in result.reconciliation.counts:
        lines.append(
            f"{count.object_name:<14}{count.extracted:>10}{count.rejected:>10}"
            f"{count.loaded:>8}{count.warnings:>7}"
        )
    lines.append("")
    lines.append(
        f"business partners created: {len(result.business_partners.partners)} "
        f"(merged {result.business_partners.merged_count} source records)"
    )
    failed = result.reconciliation.failed_checks
    lines.append(
        f"reconciliation: {'PASS' if result.reconciliation.passed else 'FAIL'} "
        f"({len(failed)} failed of {len(result.reconciliation.checks)} checks)"
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
    except ExtractError as error:
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
