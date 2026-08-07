"""Reconciliation layer: the evidence pack for a wave load.

Every check compares something counted on the ECC side with the same
thing counted on the S/4HANA side. A wave cannot be signed off with a
failing check; warnings are permitted but must be explained in the
cutover log.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Check:
    id: str
    description: str
    source_value: str
    target_value: str
    passed: bool
    note: str = ""

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "id": self.id,
            "description": self.description,
            "source_value": self.source_value,
            "target_value": self.target_value,
            "status": self.status,
            "note": self.note,
        }


@dataclass
class ObjectCounts:
    object_name: str
    extracted: int
    rejected: int
    loaded: int
    warnings: int = 0

    @property
    def balanced(self) -> bool:
        return self.extracted - self.rejected == self.loaded


@dataclass
class Reconciliation:
    wave: str
    counts: list[ObjectCounts] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failed_checks(self) -> list[Check]:
        return [check for check in self.checks if not check.passed]


def _decimal(value: str) -> Decimal:
    return Decimal(value or "0")


def _sum_by(rows, key_fields: tuple[str, ...], value_field: str) -> dict[tuple, Decimal]:
    totals: dict[tuple, Decimal] = defaultdict(Decimal)
    for row in rows:
        key = tuple(row[field] for field in key_fields)
        totals[key] += _decimal(row[value_field])
    return dict(totals)


def build(
    wave: str,
    counts: list[ObjectCounts],
    accepted_open_items: list[dict[str, str]],
    loaded_open_items: list[dict[str, str]],
    accepted_stock: list[dict[str, str]],
    loaded_stock: list[dict[str, str]],
    accepted_partners: int,
    business_partners: int,
    merged_partners: int,
    xref: dict[str, str],
) -> Reconciliation:
    reconciliation = Reconciliation(wave=wave, counts=counts)

    for count in counts:
        reconciliation.checks.append(
            Check(
                id=f"REC-CNT-{count.object_name}",
                description=f"{count.object_name}: extracted - rejected = loaded",
                source_value=f"{count.extracted} - {count.rejected}",
                target_value=str(count.loaded),
                passed=count.balanced,
            )
        )

    reconciliation.checks.append(
        Check(
            id="REC-BP-001",
            description="business partners created = accepted partners - merges",
            source_value=f"{accepted_partners} - {merged_partners}",
            target_value=str(business_partners),
            passed=accepted_partners - merged_partners == business_partners,
            note="customer/vendor records for the same legal entity share one BP",
        )
    )

    unmapped = [
        row for row in loaded_open_items
        if row["SourcePartner"] and not row["BusinessPartner"]
    ]
    reconciliation.checks.append(
        Check(
            id="REC-BP-002",
            description="every loaded open item partner resolves to a BP",
            source_value=str(len([r for r in loaded_open_items if r["SourcePartner"]])),
            target_value=str(
                len([r for r in loaded_open_items if r["BusinessPartner"]])
            ),
            passed=not unmapped,
            note="" if not unmapped else f"{len(unmapped)} unmapped partner lines",
        )
    )

    reconciliation.checks.append(
        Check(
            id="REC-BP-003",
            description="cross reference covers every migrated partner",
            source_value=str(accepted_partners),
            target_value=str(len(xref)),
            passed=len(xref) == accepted_partners,
        )
    )

    source_totals = _sum_by(accepted_open_items, ("BUKRS", "WAERS"), "DMBTR")
    target_totals = _sum_by(
        loaded_open_items,
        ("CompanyCode", "CompanyCodeCurrency"),
        "AmountInCompanyCodeCurrency",
    )
    for key in sorted(set(source_totals) | set(target_totals)):
        source_value = source_totals.get(key, Decimal(0))
        target_value = target_totals.get(key, Decimal(0))
        reconciliation.checks.append(
            Check(
                id=f"REC-FI-VAL-{key[0]}-{key[1]}",
                description=f"open item value total {key[0]} {key[1]}",
                source_value=f"{source_value:.2f}",
                target_value=f"{target_value:.2f}",
                passed=source_value == target_value,
            )
        )

    debit_credit: dict[str, list[Decimal]] = defaultdict(
        lambda: [Decimal(0), Decimal(0)]
    )
    for row in loaded_open_items:
        amount = _decimal(row["AmountInCompanyCodeCurrency"])
        index = 0 if row["DebitCreditCode"] == "S" else 1
        debit_credit[row["CompanyCode"]][index] += amount
    for company_code, (debit, credit) in sorted(debit_credit.items()):
        reconciliation.checks.append(
            Check(
                id=f"REC-FI-BAL-{company_code}",
                description=f"loaded open items balance in {company_code}",
                source_value=f"debit {debit:.2f}",
                target_value=f"credit {credit:.2f}",
                passed=debit == credit,
            )
        )

    source_stock = _sum_by(accepted_stock, ("WERKS",), "CLABS")
    target_stock = _sum_by(loaded_stock, ("Plant",), "UnrestrictedQuantity")
    for key in sorted(set(source_stock) | set(target_stock)):
        source_value = source_stock.get(key, Decimal(0))
        target_value = target_stock.get(key, Decimal(0))
        reconciliation.checks.append(
            Check(
                id=f"REC-STK-{key[0]}",
                description=f"unrestricted stock quantity in plant {key[0]}",
                source_value=f"{source_value:.3f}",
                target_value=f"{target_value:.3f}",
                passed=source_value == target_value,
            )
        )

    return reconciliation


def to_json(reconciliation: Reconciliation) -> str:
    payload = {
        "wave": reconciliation.wave,
        "passed": reconciliation.passed,
        "counts": [
            {
                "object": count.object_name,
                "extracted": count.extracted,
                "rejected": count.rejected,
                "loaded": count.loaded,
                "warnings": count.warnings,
            }
            for count in reconciliation.counts
        ],
        "checks": [check.as_dict() for check in reconciliation.checks],
    }
    return json.dumps(payload, indent=2)


def to_markdown(reconciliation: Reconciliation) -> str:
    lines: list[str] = []
    lines.append(f"# Wave load reconciliation - {reconciliation.wave}")
    lines.append("")
    lines.append(
        "Generated by `datamig`. This is the evidence attached to the "
        "cutover log: record counts on both sides, value and quantity "
        "totals, and the exceptions held back from the load."
    )
    lines.append("")
    lines.append(
        f"**Overall result: {'PASS' if reconciliation.passed else 'FAIL'}** "
        f"({len(reconciliation.failed_checks)} failed of "
        f"{len(reconciliation.checks)} checks)"
    )
    lines.append("")

    lines.append("## Record counts")
    lines.append("")
    lines.append("| Object | Extracted | Rejected | Loaded | Warnings |")
    lines.append("| --- | --- | --- | --- | --- |")
    for count in reconciliation.counts:
        lines.append(
            f"| {count.object_name} | {count.extracted} | {count.rejected} | "
            f"{count.loaded} | {count.warnings} |"
        )
    lines.append("")

    lines.append("## Checks")
    lines.append("")
    lines.append("| Check | Description | Source | Target | Result | Note |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for check in reconciliation.checks:
        lines.append(
            f"| {check.id} | {check.description} | {check.source_value} | "
            f"{check.target_value} | {check.status} | {check.note} |"
        )
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"
