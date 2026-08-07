"""Reconciliation layer: the evidence pack for a wave load.

Every check compares something counted on the ECC side with the same
thing counted on the S/4HANA side. A wave cannot be signed off with a
failing check; warnings are permitted but must be explained in the
cutover log.

With two source systems loading into one, record counts no longer
match by construction: fewer target records than source records is the
intended outcome wherever a merge happened. So the merge is
reconciled explicitly - source records minus merges equals target
records - and every merge has to be attributable to either a legal
entity held in both systems or a harmonisation decision. An
unexplained shortfall is data loss wearing a merge's clothes.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mapping import ProductHarmonisation, ProductResult


# A check whose two sides are counted from different things: the ECC
# extract on one side, the rows written to the target on the other. It
# can fail on real data, and it is the only kind that is evidence about
# the load.
COMPARED = "compared"

# A check whose two sides are derived from the same data, so it holds
# unless the tooling itself is broken. Worth running - it is how a
# mis-set counter or a mapping that starts dropping records gets caught
# - but it says nothing about whether the extract was right, and an
# evidence pack that does not distinguish the two overstates what it
# proves. `AGENTS.md`: a check that cannot fail is not a check.
INVARIANT = "invariant"

# A check with both sides read off the load file, holding it against a
# rule the target must satisfy: a key that is unique, a document that
# balances, a reference that resolves. Bad input is how it fails, so it
# is not an invariant - but it never looks at the extract, so it is no
# evidence that the extract arrived whole either.
ASSERTED = "asserted"


@dataclass(frozen=True)
class Check:
    id: str
    description: str
    source_value: str
    target_value: str
    passed: bool
    note: str = ""
    evidence: str = COMPARED

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
            "evidence": self.evidence,
            "note": self.note,
        }


@dataclass
class ObjectCounts:
    """Record counts for one migration object.

    ``source_keys`` are the keys of the records accepted for the load,
    counted on the ECC extract. ``target_keys`` are the keys actually
    present in the emitted target rows. Comparing the two is what makes
    the count check capable of failing: a mapping that drops, duplicates
    or invents a record breaks it.

    ``loaded_independently`` says whether ``loaded`` was counted off
    something other than the accepted records - for partners, the
    cross-reference rows that get written. Where it was not, mapping
    emits one row per accepted record by construction, so the record
    arithmetic restates its own source side and is reported as an
    invariant rather than as evidence.
    """

    object_name: str
    extracted: int
    rejected: int
    loaded: int
    warnings: int = 0
    source_keys: frozenset[str] = frozenset()
    target_keys: frozenset[str] = frozenset()
    merged: int = 0
    loaded_independently: bool = False

    @property
    def missing(self) -> frozenset[str]:
        """Accepted on the ECC side but absent from the load file."""
        return self.source_keys - self.target_keys

    @property
    def unexpected(self) -> frozenset[str]:
        """Present in the load file with no accepted ECC record."""
        return self.target_keys - self.source_keys

    @property
    def duplicated(self) -> int:
        return self.loaded - len(self.target_keys)

    @property
    def balanced(self) -> bool:
        return not self.missing and not self.unexpected and self.duplicated == 0


@dataclass
class Reconciliation:
    wave: str
    counts: list[ObjectCounts] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    source_systems: list[str] = field(default_factory=list)
    accepted_by_system: dict[str, dict[str, int]] = field(default_factory=dict)

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


def _sample(keys: frozenset[str], limit: int = 3) -> str:
    ordered = sorted(keys)
    shown = ", ".join(ordered[:limit])
    return shown if len(ordered) <= limit else f"{shown}, ..."


def _merge_checks(
    counts: list[ObjectCounts],
    accepted_partners: int,
    business_partners: int,
    merged_partners: int,
    cross_system_partners: int,
    products: ProductResult | None,
    harmonisation: ProductHarmonisation | None,
    rejected_materials: set[tuple[str, str]],
    accepted_materials: list[dict[str, str]],
    extracted_products: set[str],
) -> list[Check]:
    """Prove that every record the merge removed was meant to go."""
    checks: list[Check] = []

    checks.append(
        Check(
            id="REC-MRG-001",
            description=(
                "partner records minus merges equals business partners"
            ),
            # ``accepted_partners`` is counted on the ECC side, after
            # cleansing. ``merged_partners`` and ``business_partners``
            # are both read off the files that will be loaded, so a
            # record lost, duplicated or invented between the two
            # breaks the equality.
            source_value=f"{accepted_partners} records - {merged_partners} merged",
            target_value=f"{business_partners} BPs",
            passed=accepted_partners - merged_partners == business_partners,
            note=(
                f"{cross_system_partners} BPs are held in both source systems"
            ),
        )
    )

    if products is not None:
        material_counts = next(
            (count for count in counts if count.object_name == "materials"), None
        )
        # Counted on the ECC side, after cleansing. Taking it from
        # products.xref instead would compare the mapping with itself:
        # every accepted row contributes exactly one xref entry and
        # then either a product or a merge, so the equality holds by
        # construction and a row the mapping skipped entirely drops out
        # of both sides.
        mapped_materials = len(accepted_materials)
        checks.append(
            Check(
                # Still an invariant, for the reason the comment above
                # gives about the other direction: `convert_to_products`
                # turns every accepted row into one product or one
                # merge, and raises rather than skipping. REC-MRG-003
                # is the one that goes and looks at the load file.
                evidence=INVARIANT,
                id="REC-MRG-002",
                description="material records minus harmonisations equals products",
                source_value=(
                    f"{mapped_materials} materials - "
                    f"{products.merged_count} harmonised"
                ),
                target_value=f"{len(products.products)} products",
                passed=(
                    mapped_materials - products.merged_count
                    == len(products.products)
                ),
                note=(
                    "" if material_counts is None
                    else f"{material_counts.rejected} rejected before mapping"
                ),
            )
        )

    if products is not None and harmonisation is not None:
        # The survivor of each merge is named by the governed decision
        # table and looked up against the load file, never read back off
        # the mapping's own cross reference: a mapping that loses the
        # surviving product would otherwise lose it from both sides of
        # the check and still balance. Cleansing holds back a merge
        # whose survivor was rejected (DQ-MAT-010), so on clean data
        # this is the mapping's guarantee rather than the extract's.
        merge_targets = {
            harmonisation.target_product(row)
            for row in accepted_materials
            if harmonisation.is_merged(row)
        }
        loaded_products = {row["Product"] for row in products.products}
        stranded = sorted(merge_targets - loaded_products)
        checks.append(
            Check(
                id="REC-MRG-003",
                description="every harmonised material resolves to a loaded product",
                source_value=f"{len(merge_targets)} survivors named by decisions",
                target_value=(
                    f"{len(merge_targets) - len(stranded)} in the load file"
                ),
                passed=not stranded,
                note=(
                    "" if not stranded
                    else f"{len(stranded)} stranded: {', '.join(stranded[:3])}"
                ),
            )
        )

    if harmonisation is not None and products is not None:
        applied = {
            (system, material) for system, material in products.merged_materials
        }
        unapplied = set(harmonisation.merged_materials) - applied
        targets = harmonisation.targets
        # A decision naming a material that cleansing rejected is
        # accounted for: the record is held back and visible in the
        # exception report. Two other outcomes look the same from the
        # load file and are not accounted for at all - a decision whose
        # material is not in the extract, and one whose surviving
        # product does not exist in either system. The second is the
        # more dangerous, because holding the record back is exactly
        # what a legitimate hold looks like.
        def _as_written(key: tuple[str, str]) -> str:
            decision = harmonisation.decision_for(key)
            material = decision.material if decision else key[1]
            return f"{key[0]}/{material}"

        held: list[tuple[str, str]] = []
        stale: list[tuple[str, str]] = []
        invalid: list[tuple[str, str]] = []
        for key in sorted(unapplied):
            if key not in rejected_materials:
                stale.append(key)
            elif targets[key] not in extracted_products:
                invalid.append(key)
            else:
                held.append(key)

        def _named(keys: list[tuple[str, str]]) -> str:
            # The number as the decision table writes it, not the
            # unpadded form the lookup uses: this note is a list of
            # rows for a steward to go and correct.
            return ", ".join(_as_written(key) for key in keys)

        notes = []
        if held:
            notes.append("held back by cleansing: " + _named(held))
        if stale:
            notes.append("stale, no such material in the extract: " + _named(stale))
        if invalid:
            notes.append(
                "names a surviving product that is in neither system: "
                + ", ".join(
                    f"{_as_written(key)} -> {targets[key]}"
                    for key in invalid
                )
            )
        checks.append(
            Check(
                id="REC-MRG-004",
                description="every harmonisation decision was applied or rejected",
                source_value=f"{len(harmonisation.merged_materials)} decisions",
                target_value=f"{len(applied)} applied, {len(held)} rejected",
                passed=not stale and not invalid,
                note="; ".join(notes),
            )
        )

    return checks


def build(
    wave: str,
    counts: list[ObjectCounts],
    accepted_open_items: list[dict[str, str]],
    loaded_open_items: list[dict[str, str]],
    accepted_stock: list[dict[str, str]],
    loaded_stock: list[dict[str, str]],
    accepted_partners: int,
    partner_identities: int,
    business_partners: int,
    merged_partners: int,
    xref: dict[str, str],
    cross_system_partners: int = 0,
    source_systems: list[str] | None = None,
    accepted_by_system: dict[str, dict[str, int]] | None = None,
    products: ProductResult | None = None,
    harmonisation: ProductHarmonisation | None = None,
    rejected_materials: set[tuple[str, str]] | None = None,
    accepted_materials: list[dict[str, str]] | None = None,
    extracted_products: set[str] | None = None,
) -> Reconciliation:
    # The merge checks read their source side off the ECC records, so a
    # caller supplying only the load file would get a check failing on
    # nothing - zero materials against a full load file. A fabricated
    # failure is as bad as one that cannot fail: it is a red evidence
    # pack that says nothing about the data.
    if products is not None and accepted_materials is None:
        raise ValueError(
            "products needs accepted_materials: REC-MRG-002 counts its "
            "source side on the ECC side"
        )

    reconciliation = Reconciliation(
        wave=wave,
        counts=counts,
        source_systems=source_systems or [],
        accepted_by_system=accepted_by_system or {},
    )

    for count in counts:
        notes: list[str] = []
        if count.missing:
            notes.append(f"{len(count.missing)} not loaded: {_sample(count.missing)}")
        if count.unexpected:
            notes.append(f"{len(count.unexpected)} unknown: {_sample(count.unexpected)}")
        if count.duplicated:
            notes.append(f"{count.duplicated} duplicate rows")
        reconciliation.checks.append(
            Check(
                id=f"REC-CNT-{count.object_name}",
                description=f"{count.object_name}: every accepted record loaded once",
                source_value=f"{len(count.source_keys)} accepted keys",
                target_value=f"{len(count.target_keys)} keys in the load file",
                passed=count.balanced,
                note="; ".join(notes),
            )
        )
        # The report states this arithmetic under the record-count
        # table. Printing it without checking it makes the table a
        # claim rather than evidence, and a mis-set `merged` would
        # leave it silently describing a different load file.
        #
        # Only evidence where `loaded` was counted off the target. For
        # the rest, mapping emits one row per accepted record or raises,
        # so `extracted - rejected` is `len(accepted)` is `loaded` - the
        # check catches a tooling defect, not a data one, and is
        # labelled as the invariant it is.
        expected = count.extracted - count.rejected - count.merged
        reconciliation.checks.append(
            Check(
                evidence=COMPARED if count.loaded_independently else INVARIANT,
                id=f"REC-ARI-{count.object_name}",
                description=(
                    f"{count.object_name}: extracted - rejected - merged "
                    "equals the load file"
                ),
                source_value=(
                    f"{count.extracted} - {count.rejected} - "
                    f"{count.merged} = {expected}"
                ),
                target_value=f"{count.loaded} rows loaded",
                passed=expected == count.loaded,
            )
        )

    reconciliation.checks.append(
        Check(
            id="REC-BP-001",
            description="one business partner per distinct legal entity",
            source_value=f"{partner_identities} identities in {accepted_partners} records",
            target_value=f"{business_partners} BPs in the load file",
            passed=partner_identities == business_partners,
            note=f"{merged_partners} records merged into a shared BP",
        )
    )

    unmapped = [
        row for row in loaded_open_items
        if row["SourcePartner"] and not row["BusinessPartner"]
    ]
    reconciliation.checks.append(
        Check(
            evidence=ASSERTED,
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

    reconciliation.checks.extend(
        _merge_checks(
            counts=counts,
            accepted_partners=accepted_partners,
            business_partners=business_partners,
            merged_partners=merged_partners,
            cross_system_partners=cross_system_partners,
            products=products,
            harmonisation=harmonisation,
            rejected_materials=rejected_materials or set(),
            accepted_materials=accepted_materials or [],
            extracted_products=extracted_products or set(),
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
                evidence=ASSERTED,
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

    # The count check keys stock by source system so a batch cannot be
    # lost in the merge, but the target system has no such column: the
    # real key of initial stock is product, plant, storage location and
    # batch. If both systems ever supplied the same batch on the same
    # harmonised product, the count check would still balance and the
    # load would carry two rows the target cannot tell apart.
    target_keys = [
        "/".join(
            (row["Product"], row["Plant"], row["StorageLocation"], row["Batch"])
        )
        for row in loaded_stock
    ]
    duplicated = sorted(
        key for key, seen in Counter(target_keys).items() if seen > 1
    )
    reconciliation.checks.append(
        Check(
            evidence=ASSERTED,
            id="REC-STK-KEY",
            description="initial stock is unique on the S/4HANA key",
            source_value=f"{len(target_keys)} rows",
            target_value=f"{len(set(target_keys))} distinct product/plant/sloc/batch",
            passed=not duplicated,
            note=(
                f"{len(duplicated)} collide after the merge: {_sample(duplicated)}"
                if duplicated
                else ""
            ),
        )
    )

    return reconciliation


def to_json(reconciliation: Reconciliation) -> str:
    payload = {
        "wave": reconciliation.wave,
        "passed": reconciliation.passed,
        "source_systems": reconciliation.source_systems,
        "accepted_by_system": reconciliation.accepted_by_system,
        "counts": [
            {
                "object": count.object_name,
                "extracted": count.extracted,
                "rejected": count.rejected,
                "merged": count.merged,
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
    lines.append(
        "`Extracted` spans both source systems. `Merged` is records "
        "that were deliberately absorbed into another record by the "
        "consolidation, so `extracted - rejected - merged` is what the "
        "load file should contain."
    )
    lines.append("")
    lines.append(
        "`Merged` is zero for customers and vendors because their load "
        "file is the cross reference, which keeps one row per source "
        "record. Partner merges collapse business partners, not "
        "records, and are counted in `REC-MRG-001` below."
    )
    lines.append("")
    lines.append("| Object | Extracted | Rejected | Merged | Loaded | Warnings |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for count in reconciliation.counts:
        lines.append(
            f"| {count.object_name} | {count.extracted} | {count.rejected} | "
            f"{count.merged} | {count.loaded} | {count.warnings} |"
        )
    lines.append("")

    if reconciliation.accepted_by_system:
        systems = reconciliation.source_systems or sorted(
            {
                system
                for per_object in reconciliation.accepted_by_system.values()
                for system in per_object
            }
        )
        lines.append("## Accepted records by source system")
        lines.append("")
        lines.append(
            "Both ECC systems load into one S/4HANA client. These are "
            "the records each contributed after cleansing, before the "
            "merge collapsed the duplicates."
        )
        lines.append("")
        lines.append("| Object | " + " | ".join(systems) + " | Total |")
        lines.append("| --- |" + " --- |" * (len(systems) + 1))
        for object_name, per_system in reconciliation.accepted_by_system.items():
            values = [per_system.get(system, 0) for system in systems]
            cells = " | ".join(str(value) for value in values)
            lines.append(f"| {object_name} | {cells} | {sum(values)} |")
        lines.append("")

    lines.append("## Checks")
    lines.append("")
    lines.append(
        "`Evidence` says what a pass is worth. **compared** counts the "
        "two sides from different things - the ECC extract and the rows "
        "written to the target - so it can fail on real data. "
        "**asserted** reads both sides off the load file and holds it "
        "against a rule the target must satisfy: it fails on bad input, "
        "but never looks at the extract. **invariant** derives both "
        "sides from the same data: it catches the tooling breaking, not "
        "the data being wrong, and proves nothing about the load on its "
        "own."
    )
    lines.append("")
    lines.append(
        "| Check | Description | Source | Target | Evidence | Result | Note |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for check in reconciliation.checks:
        lines.append(
            f"| {check.id} | {check.description} | {check.source_value} | "
            f"{check.target_value} | {check.evidence} | {check.status} | "
            f"{check.note} |"
        )
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"
