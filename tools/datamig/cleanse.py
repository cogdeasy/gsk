"""Cleansing layer: data quality rules applied before mapping.

Rules either repair a value in place (``FIX``), keep the record but
raise an exception for the data steward (``WARN``), or hold the record
back from the load (``REJECT``). Nothing is silently dropped: every
rejected record appears in the exception file and in the reconciliation
report, which is what the cutover sign-off needs.

Records arrive from both ECC systems in one pass, so the rules that
look across records - duplicate descriptions, partners that merge -
see the whole estate rather than one system at a time. That is the
point: the duplicates worth finding are the ones that only exist
because the same counterparty or product is mastered twice.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from .identity import (
    PartnerIdentity,
    partner_identity,
    source_key,
    strip_leading_zeros,
)

ISO_COUNTRIES = {
    "GB", "DE", "FR", "BE", "IE", "US", "DK", "TZ", "SG", "CH",
    "MX", "CN", "IT", "ES", "NL", "PL", "JP", "IN", "BR", "CA",
    "AU", "ZA", "KE", "CO", "SE", "NO", "FI", "AT", "PT", "GR",
    "ID", "PH", "VN", "TH", "NG", "GH", "ET", "SN", "BD", "PK",
}

# ECC base unit -> ISO unit expected by the S/4HANA load.
UOM_ISO = {
    "ST": "PCE",
    "EA": "EA",
    "KG": "KGM",
    "G": "GRM",
    "L": "LTR",
    "ML": "MLT",
    "TO": "TNE",
    "M": "MTR",
    "BOX": "BX",
}


class Action(str, Enum):
    FIX = "fix"
    WARN = "warn"
    REJECT = "reject"


@dataclass(frozen=True)
class Issue:
    rule_id: str
    action: Action
    object_name: str
    key: str
    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "action": self.action.value,
            "object": self.object_name,
            "key": self.key,
            "field": self.field,
            "message": self.message,
        }


@dataclass
class CleanseResult:
    object_name: str
    accepted: list[dict[str, str]] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    #: Source key -> the product it was harmonised into, for records
    #: held back by `DQ-MAT-010`. Downstream objects need the reason,
    #: not just the absence, to report their own rejects usefully.
    harmonisation_holds: dict[str, str] = field(default_factory=dict)
    #: Source keys held back by `DQ-MAT-009` - the number means two
    #: things and nobody has said which survives. Same reason as
    #: above: the absence alone would read as a missing master.
    collision_holds: set[str] = field(default_factory=set)

    @property
    def source_count(self) -> int:
        return len(self.accepted) + len(self.rejected)

    def counts_by_action(self) -> dict[str, int]:
        counter = Counter(issue.action.value for issue in self.issues)
        return {action.value: counter.get(action.value, 0) for action in Action}

    def issues_for(self, rule_id: str) -> list[Issue]:
        return [issue for issue in self.issues if issue.rule_id == rule_id]


def _issue(rule_id, action, object_name, key, field_name, message) -> Issue:
    return Issue(
        rule_id=rule_id,
        action=action,
        object_name=object_name,
        key=key,
        field=field_name,
        message=message,
    )


def cleanse_materials(
    rows: list[dict[str, str]],
    harmonisation_targets: dict[tuple[str, str], str] | None = None,
) -> CleanseResult:
    """Cleanse the material master from both systems.

    ``harmonisation_targets`` maps (source system, material) to the
    product number the material is to be merged into. It is needed here
    rather than only in mapping because a merge inherits the quality of
    its target: if the surviving record is rejected, the record that was
    to be retired has nowhere to land.
    """
    result = CleanseResult(object_name="materials")
    descriptions: dict[str, list[str]] = defaultdict(list)
    numbers: dict[str, list[str]] = defaultdict(list)

    for row in rows:
        key = source_key(row, "MATNR")
        reject = False

        if row["MEINS"] and row["MEINS"] != row["MEINS"].upper():
            result.issues.append(
                _issue("DQ-MAT-001", Action.FIX, "materials", key, "MEINS",
                       f"base unit '{row['MEINS']}' upper-cased")
            )
            row["MEINS"] = row["MEINS"].upper()

        if not row["MEINS"]:
            reject = True
            result.issues.append(
                _issue("DQ-MAT-002", Action.REJECT, "materials", key, "MEINS",
                       "base unit of measure is missing")
            )
        elif row["MEINS"] not in UOM_ISO:
            reject = True
            result.issues.append(
                _issue("DQ-MAT-003", Action.REJECT, "materials", key, "MEINS",
                       f"no ISO mapping for base unit '{row['MEINS']}'")
            )

        if row["BRGEW"] and not row["GEWEI"]:
            reject = True
            result.issues.append(
                _issue("DQ-MAT-004", Action.REJECT, "materials", key, "GEWEI",
                       "gross weight supplied without a weight unit")
            )

        if not row["BRGEW"]:
            result.issues.append(
                _issue("DQ-MAT-005", Action.WARN, "materials", key, "BRGEW",
                       "gross weight is missing, loaded as zero")
            )
            row["BRGEW"] = "0.000"

        if row["XCHPF"] == "X" and not row["MHDHB"]:
            reject = True
            result.issues.append(
                _issue("DQ-MAT-006", Action.REJECT, "materials", key, "MHDHB",
                       "batch managed material without total shelf life (GMP)")
            )

        if row["MAKTX"] and row["MAKTX"] != row["MAKTX"].upper():
            result.issues.append(
                _issue("DQ-MAT-007", Action.FIX, "materials", key, "MAKTX",
                       "description normalised to upper case")
            )
            row["MAKTX"] = row["MAKTX"].upper()

        descriptions[row["MAKTX"]].append(key)

        if reject:
            result.rejected.append(row)
        else:
            result.accepted.append(row)
            numbers[row["MATNR"]].append(row)

    for description, keys in descriptions.items():
        if len(keys) > 1:
            systems = {key.split("/")[0] for key in keys}
            scope = (
                "in both source systems" if len(systems) > 1
                else f"within {next(iter(systems))}"
            )
            result.issues.append(
                _issue("DQ-MAT-008", Action.WARN, "materials", ", ".join(keys),
                       "MAKTX",
                       f"duplicate material description '{description}' "
                       f"{scope}, confirm the harmonisation decision")
            )

    _reject_undecided_collisions(result, numbers, harmonisation_targets or {})

    if harmonisation_targets:
        _reject_orphaned_merges(result, harmonisation_targets)

    return result


def _reject_undecided_collisions(
    result: CleanseResult,
    numbers: dict[str, list[dict[str, str]]],
    harmonisation_targets: dict[tuple[str, str], str],
) -> None:
    """Hold back a material number that means two things.

    The systems were configured from one template and share number
    ranges, so the same MATNR can hold unrelated products. The target
    product number is the bare number, so loading both would keep the
    first record, discard the second's master data and re-point its
    batches at the wrong product. Which one survives is a stewardship
    decision, so both wait for one.
    """
    colliding: list[dict[str, str]] = []

    for number, rows in numbers.items():
        undecided = [
            row for row in rows
            if (row["SOURCE_SYSTEM"], row["MATNR"]) not in harmonisation_targets
        ]
        systems = {row["SOURCE_SYSTEM"] for row in undecided}
        if len(systems) < 2:
            continue
        keys = ", ".join(source_key(row, "MATNR") for row in undecided)
        colliding.extend(undecided)
        result.issues.append(
            _issue("DQ-MAT-009", Action.REJECT, "materials", keys, "MATNR",
                   f"material number {number} is used in both source systems "
                   "for different products and no harmonisation decision "
                   "nominates a survivor; the target product number cannot "
                   "be carried over from either")
        )

    if not colliding:
        return

    rejected = {source_key(row, "MATNR") for row in colliding}
    result.accepted[:] = [
        row for row in result.accepted
        if source_key(row, "MATNR") not in rejected
    ]
    result.rejected.extend(colliding)
    result.collision_holds.update(rejected)


def _reject_orphaned_merges(
    result: CleanseResult, harmonisation_targets: dict[tuple[str, str], str]
) -> None:
    """Hold back merges whose surviving product did not itself survive.

    Loading the retired material under its own number instead would
    quietly reverse a governed decision and split the product's stock
    and history across two numbers in the target, so the record waits
    for the surviving master to be corrected.
    """
    surviving = {
        strip_leading_zeros(row["MATNR"])
        for row in result.accepted
        if (row["SOURCE_SYSTEM"], row["MATNR"]) not in harmonisation_targets
    }

    def is_orphaned(row: dict[str, str]) -> bool:
        key = (row["SOURCE_SYSTEM"], row["MATNR"])
        return (
            key in harmonisation_targets
            and harmonisation_targets[key] not in surviving
        )

    orphaned = [row for row in result.accepted if is_orphaned(row)]
    # Rebuilt rather than removed one by one: list.remove matches on
    # dict equality, so it would drop whichever row happens to compare
    # equal first.
    result.accepted[:] = [row for row in result.accepted if not is_orphaned(row)]

    for row in orphaned:
        target = harmonisation_targets[(row["SOURCE_SYSTEM"], row["MATNR"])]
        result.rejected.append(row)
        result.harmonisation_holds[source_key(row, "MATNR")] = target
        result.issues.append(
            _issue("DQ-MAT-010", Action.REJECT, "materials",
                   source_key(row, "MATNR"), "MATNR",
                   f"harmonised into product {target}, which is not itself "
                   "in the load; correct the surviving master or revisit "
                   "the harmonisation decision")
        )


def cleanse_partners(
    rows: list[dict[str, str]], object_name: str, key_field: str
) -> CleanseResult:
    result = CleanseResult(object_name=object_name)
    prefix = "DQ-CUS" if object_name == "customers" else "DQ-VEN"
    seen: dict[PartnerIdentity, list[str]] = defaultdict(list)
    numbers: dict[str, list[tuple[str, PartnerIdentity]]] = defaultdict(list)

    for row in rows:
        key = source_key(row, key_field)
        reject = False

        if row["LAND1"] and row["LAND1"] != row["LAND1"].upper():
            result.issues.append(
                _issue(f"{prefix}-001", Action.FIX, object_name, key, "LAND1",
                       f"country '{row['LAND1']}' upper-cased")
            )
            row["LAND1"] = row["LAND1"].upper()

        if not row["NAME1"] or not row["LAND1"]:
            reject = True
            result.issues.append(
                _issue(f"{prefix}-002", Action.REJECT, object_name, key, "NAME1",
                       "name or country missing, cannot create a business partner")
            )
        elif row["LAND1"] not in ISO_COUNTRIES:
            reject = True
            result.issues.append(
                _issue(f"{prefix}-003", Action.REJECT, object_name, key, "LAND1",
                       f"'{row['LAND1']}' is not a valid ISO country code")
            )

        if not row["PSTLZ"]:
            result.issues.append(
                _issue(f"{prefix}-004", Action.WARN, object_name, key, "PSTLZ",
                       "postal code missing, address will not be validated")
            )

        if not row["STCEG"] and row["LAND1"] in ("GB", "DE", "BE", "IE", "FR"):
            result.issues.append(
                _issue(f"{prefix}-005", Action.WARN, object_name, key, "STCEG",
                       "VAT registration missing for an EU/UK partner")
            )

        if object_name == "vendors" and row.get("ZZ_GMP_AUDITED") != "X":
            result.issues.append(
                _issue("DQ-VEN-006", Action.WARN, object_name, key,
                       "ZZ_GMP_AUDITED",
                       "supplier has no GMP audit flag, confirm before cutover")
            )

        if reject:
            result.rejected.append(row)
        else:
            result.accepted.append(row)
            seen[partner_identity(row)].append(key)
            numbers[row[key_field]].append((key, partner_identity(row)))

    for identity, keys in seen.items():
        if len(keys) > 1:
            systems = {key.split("/")[0] for key in keys}
            scope = (
                "across both source systems" if len(systems) > 1
                else f"within {next(iter(systems))}"
            )
            result.issues.append(
                _issue(f"{prefix}-007", Action.WARN, object_name, ", ".join(keys),
                       "NAME1",
                       f"records merge into one business partner {scope}: "
                       f"{identity[0]}")
            )

    # The two systems share number ranges. Where the same number holds
    # different entities the merge must key on the entity, not the
    # number, so the collision is reported before the load rather than
    # discovered as a wrongly combined partner afterwards.
    for number, entries in numbers.items():
        keys = [key for key, _ in entries]
        identities = {identity for _, identity in entries}
        if len({key.split("/")[0] for key in keys}) > 1 and len(identities) > 1:
            names = sorted(identity[0] for identity in identities)
            result.issues.append(
                _issue(f"{prefix}-008", Action.WARN, object_name, ", ".join(keys),
                       key_field,
                       f"number {number} exists in both source systems as "
                       f"different entities ({' / '.join(names)}); it must "
                       "not be reused as the business partner number")
            )

    return result


def cleanse_open_items(
    rows: list[dict[str, str]], known_partners: set[str]
) -> CleanseResult:
    result = CleanseResult(object_name="open_items")
    documents: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)

    for row in rows:
        documents[
            (row["SOURCE_SYSTEM"], row["BUKRS"], row["BELNR"], row["GJAHR"])
        ].append(row)

    for (system, bukrs, belnr, gjahr), lines in documents.items():
        key = f"{system}/{bukrs}/{belnr}/{gjahr}"
        reject_document = False

        debit = sum(
            (Decimal(line["DMBTR"]) for line in lines if line["SHKZG"] == "S"),
            Decimal(0),
        )
        credit = sum(
            (Decimal(line["DMBTR"]) for line in lines if line["SHKZG"] == "H"),
            Decimal(0),
        )
        if debit != credit:
            reject_document = True
            result.issues.append(
                _issue("DQ-FI-001", Action.REJECT, "open_items", key, "DMBTR",
                       f"document does not balance: debit {debit:.2f} "
                       f"credit {credit:.2f}")
            )

        for line in lines:
            partner = line["PARTNER"]
            # Resolved within the line's own system: the same number in
            # the other system is a different company.
            if partner and source_key(line, "PARTNER") not in known_partners:
                reject_document = True
                result.issues.append(
                    _issue("DQ-FI-002", Action.REJECT, "open_items", key, "PARTNER",
                           f"partner {partner} is not in the migrated master "
                           f"data for {system}")
                )
            if partner and not line["ZFBDT"]:
                result.issues.append(
                    _issue("DQ-FI-003", Action.WARN, "open_items", key, "ZFBDT",
                           "open item has no baseline date, ageing will be wrong")
                )

        target = result.rejected if reject_document else result.accepted
        target.extend(lines)

    return result


def cleanse_batch_stock(
    rows: list[dict[str, str]],
    materials: dict[str, dict[str, str]],
    harmonisation_holds: dict[str, str] | None = None,
    collision_holds: set[str] | None = None,
) -> CleanseResult:
    result = CleanseResult(object_name="batch_stock")
    holds = harmonisation_holds or {}
    collisions = collision_holds or set()

    for row in rows:
        key = f"{source_key(row, 'WERKS')}/{row['MATNR']}/{row['CHARG']}"
        reject = False
        material_key = source_key(row, "MATNR")
        material = materials.get(material_key)

        if material is None and material_key in holds:
            # Naming the missing master would send a steward looking
            # for a record that was deliberately retired. The work is
            # on the surviving product, or on the decision itself.
            reject = True
            result.issues.append(
                _issue("DQ-STK-006", Action.REJECT, "batch_stock", key, "MATNR",
                       f"material was harmonised into product "
                       f"{holds[material_key]}, which cleansing held back "
                       "(DQ-MAT-010); this stock loads once that product does")
            )
        elif material is None and material_key in collisions:
            # Same reasoning as DQ-STK-006: the master is absent by
            # decision, not by accident, and the steward has nothing to
            # do here until the collision is settled.
            reject = True
            result.issues.append(
                _issue("DQ-STK-007", Action.REJECT, "batch_stock", key, "MATNR",
                       f"material number {strip_leading_zeros(row['MATNR'])} is "
                       "held in both source systems and no decision names a "
                       "survivor (DQ-MAT-009); this stock loads once one does")
            )
        elif material is None:
            reject = True
            result.issues.append(
                _issue("DQ-STK-001", Action.REJECT, "batch_stock", key, "MATNR",
                       "stock for a material that is not in the migrated master")
            )
        elif material.get("XCHPF") != "X":
            reject = True
            result.issues.append(
                _issue("DQ-STK-002", Action.REJECT, "batch_stock", key, "CHARG",
                       "batch stock for a material that is not batch managed")
            )

        if material is not None and material["MEINS"] != row["MEINS"]:
            reject = True
            result.issues.append(
                _issue("DQ-STK-005", Action.REJECT, "batch_stock", key, "MEINS",
                       f"stock is in '{row['MEINS']}' but the material master "
                       f"says '{material['MEINS']}', so the quantity cannot be "
                       "loaded without a unit decision")
            )

        if material is not None and material.get("XCHPF") == "X" and not row["VFDAT"]:
            result.issues.append(
                _issue("DQ-STK-003", Action.WARN, "batch_stock", key, "VFDAT",
                       "batch has no expiry date")
            )

        if float(row["CINSM"] or 0) > 0:
            result.issues.append(
                _issue("DQ-STK-004", Action.WARN, "batch_stock", key, "CINSM",
                       "stock in quality inspection at cutover, needs a usage "
                       "decision before go-live")
            )

        if reject:
            result.rejected.append(row)
        else:
            result.accepted.append(row)

    return result
