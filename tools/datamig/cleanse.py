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
    material_key,
    material_lookup_key,
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
class HarmonisationHold:
    """Why a material that was to be merged is not in the load.

    Three rules hold a merged material back and they are not the same
    problem: DQ-MAT-010 means the surviving product was itself
    rejected, DQ-MAT-011 that the decision points at a number another
    decision retires, DQ-MAT-012 that the two are held in different
    base units. Stock behind the material is rejected in turn, and the
    steward reading that reject needs the rule that actually fired -
    naming the wrong one sends them looking for an exception that was
    never raised.
    """

    target_product: str
    rule: str
    reason: str


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
    #: Source key -> why a harmonised material is not in the load.
    #: Downstream objects need the reason, not just the absence, to
    #: report their own rejects usefully.
    harmonisation_holds: dict[str, HarmonisationHold] = field(default_factory=dict)
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

    def held_keys(self) -> set[str]:
        """Every key a reject names, as the exception pack spells it."""
        return {
            key.strip()
            for issue in self.issues
            if issue.action is Action.REJECT
            for key in issue.key.split(",")
        }

    def warnings_on_loaded(self) -> list[Issue]:
        """Warnings against records that actually reach the target.

        A warning on a held record is still true and still shipped in
        the exception pack - it comes back the day the reject is
        settled - but it is not something anyone can do anything about
        in this wave, and counting it as outstanding tells a steward
        there is work on data that does not exist yet.
        """
        held = self.held_keys()
        return [
            issue
            for issue in self.issues
            if issue.action is Action.WARN
            and not all(key.strip() in held for key in issue.key.split(","))
        ]


def _row_key(row: dict[str, str]) -> tuple[str, str]:
    """The key a harmonisation decision is matched on. See `identity`."""
    return material_key(row["SOURCE_SYSTEM"], row["MATNR"])


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
    ruled_separate: set[tuple[str, str]] | None = None,
) -> CleanseResult:
    """Cleanse the material master from both systems.

    ``harmonisation_targets`` maps (source system, material) to the
    product number the material is to be merged into. It is needed here
    rather than only in mapping because a merge inherits the quality of
    its target: if the surviving record is rejected, the record that
    was to be retired has nowhere to land.
    """
    # Re-keyed on `material_key` rather than trusting the caller to
    # have done it. Whether a governed merge is applied must not depend
    # on whether the number arrived padded: get that wrong and the
    # decision silently does not happen.
    harmonisation_targets = {
        material_key(system, material): target
        for (system, material), target in (harmonisation_targets or {}).items()
    }
    # A ruling that two materials stay separate is a decision like any
    # other, even though mapping has nothing to do with it: the record
    # still cannot load under a number the other record also claims,
    # but the exception has to say that a decision exists.
    ruled_separate = {
        material_key(system, material)
        for system, material in (ruled_separate or set())
    }
    decided = set(harmonisation_targets) | ruled_separate
    result = CleanseResult(object_name="materials")
    descriptions: dict[str, list[dict[str, str]]] = defaultdict(list)
    numbers: dict[str, list[dict[str, str]]] = defaultdict(list)

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

        # Only a real description. Two records that both arrive with
        # none are not duplicates of each other, and an exception
        # reading "duplicate material description ''" is one a steward
        # can neither act on nor close.
        if row["MAKTX"]:
            descriptions[row["MAKTX"]].append(row)
        # Keyed on the number the material would load under, not the
        # one it was extracted with: the target product number is the
        # bare MATNR, so 100801 and 000000000000100801 are the same
        # product and only differ in how each system padded them.
        #
        # Every extracted row, accepted or not. A collision is a fact
        # about the two extracts, not about how cleansing happened to
        # treat them: recording only accepted rows would let the
        # survivor load under the bare number whenever the other side
        # was rejected for something unrelated, which is exactly what
        # DQ-MAT-009 exists to stop.
        numbers[strip_leading_zeros(row["MATNR"])].append(row)

        if reject:
            result.rejected.append(row)
        else:
            result.accepted.append(row)

    for description, duplicates in descriptions.items():
        # A pair the data council has already ruled on is not an
        # exception. Asking a steward to confirm a decision that exists
        # is how an evidence pack fills up with items nobody can close,
        # and the decision is the confirmation. Counted the same way as
        # DQ-MAT-009: one record left undecided means the rest are
        # being merged into it, and there is nothing outstanding.
        undecided = [row for row in duplicates if _row_key(row) not in decided]
        if len(undecided) > 1:
            systems = {row["SOURCE_SYSTEM"] for row in undecided}
            scope = (
                "in both source systems" if len(systems) > 1
                else f"within {next(iter(systems))}"
            )
            keys = [source_key(row, "MATNR") for row in undecided]
            result.issues.append(
                _issue("DQ-MAT-008", Action.WARN, "materials", ", ".join(keys),
                       "MAKTX",
                       f"duplicate material description '{description}' "
                       f"{scope}, confirm the harmonisation decision")
            )

    # The order is load-bearing, not incidental. Each stage removes its
    # rejects from `result.accepted` before the next one reads it, which
    # is what stops a record being rejected twice and counted twice in
    # the evidence pack, and what decides which rule the steward is sent
    # after: the collision is a fact about the extracts and outranks
    # anything a decision says about the record, and a merge that cannot
    # be performed at all (DQ-MAT-012) is a better answer than one whose
    # survivor is missing (DQ-MAT-010) because the record it was already
    # holding back is why it is missing.
    _reject_undecided_collisions(
        result, numbers, harmonisation_targets or {}, ruled_separate
    )

    if harmonisation_targets:
        _reject_unit_mismatches(result, harmonisation_targets)
        _reject_orphaned_merges(result, harmonisation_targets)

    return result


def _reject_unit_mismatches(
    result: CleanseResult, harmonisation_targets: dict[tuple[str, str], str]
) -> None:
    """Hold back a merge between materials held in different units.

    Stock follows the harmonised product but keeps the base unit of the
    master it came from, so merging a material held in KG into one held
    in ST would put both quantities on one product with nothing to say
    which is which. The plant total would still reconcile, because it
    sums quantities without regard to unit.
    """
    units = {
        strip_leading_zeros(row["MATNR"]): row["MEINS"]
        for row in result.accepted
        if _row_key(row) not in harmonisation_targets
    }

    def mismatch(row: dict[str, str]) -> str | None:
        target = harmonisation_targets.get(_row_key(row))
        if target is None or target not in units:
            return None
        return None if units[target] == row["MEINS"] else target

    mismatched = [row for row in result.accepted if mismatch(row)]
    result.accepted[:] = [row for row in result.accepted if not mismatch(row)]

    for row in mismatched:
        target = harmonisation_targets[_row_key(row)]
        result.rejected.append(row)
        result.harmonisation_holds[material_lookup_key(row)] = HarmonisationHold(
            target_product=target,
            rule="DQ-MAT-012",
            reason="which is held in a different base unit",
        )
        result.issues.append(
            _issue("DQ-MAT-012", Action.REJECT, "materials",
                   source_key(row, "MATNR"), "MEINS",
                   f"held in {row['MEINS']} but harmonised into product "
                   f"{target}, which is held in {units[target]}; the merge "
                   "needs a conversion the decision does not state")
        )


def _reject_undecided_collisions(
    result: CleanseResult,
    numbers: dict[str, list[dict[str, str]]],
    harmonisation_targets: dict[tuple[str, str], str],
    ruled_separate: set[tuple[str, str]] | None = None,
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
    held: set[str] = set()
    # Rows are tracked by identity, not by key. A number repeated inside
    # one extract - the case below - gives two rows the same source key,
    # so a key-based test would move a row another rule had already
    # rejected a second time and count it twice in the evidence pack.
    accepted = {id(row) for row in result.accepted}

    for number, rows in numbers.items():
        # A decided record is out of scope: it is being merged away and
        # never claims the number. Unless the extract holds it twice -
        # ECC cannot, MARA is keyed on MATNR, so an extract that does is
        # broken. The decision names the key once and cannot say which
        # of the two records it meant, and mapping would write one
        # cross-reference entry over the other with nothing said.
        repeated = Counter(_row_key(row) for row in rows)
        undecided = [
            row for row in rows
            if _row_key(row) not in harmonisation_targets
            or repeated[_row_key(row)] > 1
        ]
        # Two rows landing on one product number, wherever they came
        # from. Requiring two systems would miss a number repeated
        # within one extract, which lands on the same product just as
        # squarely and is dropped just as silently.
        if len(undecided) < 2:
            continue
        systems = {row["SOURCE_SYSTEM"] for row in undecided}
        scope = (
            "in both source systems" if len(systems) > 1
            else f"more than once within {next(iter(systems))}"
        )
        keys = ", ".join(source_key(row, "MATNR") for row in undecided)
        held.update(material_lookup_key(row) for row in undecided)
        # A ruling that these are two products does not resolve this:
        # the target product number is the bare MATNR and only one
        # record can have it. But saying no decision exists when one
        # does sends a steward to make it a second time.
        if any(_row_key(row) in harmonisation_targets for row in undecided):
            message = (
                f"material number {number} is used {scope} for different "
                "products while the decision table names it once; which "
                "record the merge was for cannot be told from the "
                "extract, and the other would be written over by it"
            )
        elif any(_row_key(row) in (ruled_separate or set()) for row in undecided):
            message = (
                f"material number {number} is used {scope} for different "
                "products, and the decision table rules them separate "
                "without naming the number the other one takes; neither "
                "can load under it until one does"
            )
        else:
            message = (
                f"material number {number} is used {scope} for different "
                "products and no harmonisation decision nominates a "
                "survivor; the target product number cannot be carried "
                "over from either"
            )
        # Only what is still in the load can be held back; a row another
        # rule already rejected is named in the message and left where
        # it is, so it is not counted as rejected twice.
        colliding.extend(row for row in undecided if id(row) in accepted)
        result.issues.append(
            _issue("DQ-MAT-009", Action.REJECT, "materials", keys, "MATNR", message)
        )

    # Every side of every collision, including one already rejected by
    # another rule. Stock hanging off that side is stranded for the
    # same reason and needs the same explanation.
    result.collision_holds.update(held)

    if not colliding:
        return

    rejected = {id(row) for row in colliding}
    result.accepted[:] = [
        row for row in result.accepted if id(row) not in rejected
    ]
    result.rejected.extend(colliding)


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
        if _row_key(row) not in harmonisation_targets
    }

    def is_orphaned(row: dict[str, str]) -> bool:
        key = _row_key(row)
        return (
            key in harmonisation_targets
            and harmonisation_targets[key] not in surviving
        )

    orphaned = [row for row in result.accepted if is_orphaned(row)]
    # Rebuilt rather than removed one by one: list.remove matches on
    # dict equality, so it would drop whichever row happens to compare
    # equal first.
    result.accepted[:] = [row for row in result.accepted if not is_orphaned(row)]

    # A number retired by some other decision. Only consulted when the
    # target is missing from the load anyway: if a record in the other
    # system still carries that number and survives, the product does
    # exist and the decision is fine.
    retired = {
        strip_leading_zeros(material)
        for _, material in harmonisation_targets
    }
    # Numbers the collision rule is already holding. It ran first, so a
    # survivor it took out is missing for a reason the steward can act
    # on, and one it cannot reach by correcting the master.
    collided = {hold.split("/", 1)[1] for hold in result.collision_holds}

    for row in orphaned:
        target = harmonisation_targets[_row_key(row)]
        result.rejected.append(row)
        if target in retired:
            result.harmonisation_holds[material_lookup_key(row)] = HarmonisationHold(
                target_product=target,
                rule="DQ-MAT-011",
                reason="which another decision itself retires",
            )
            result.issues.append(
                _issue("DQ-MAT-011", Action.REJECT, "materials",
                       source_key(row, "MATNR"), "MATNR",
                       f"harmonised into product {target}, which another "
                       "decision itself retires; a chain leaves the "
                       "pipeline to decide what this material really "
                       "became, so name the surviving product directly")
            )
            continue
        # After the chain test: a decision naming a target that another
        # decision retires is wrong wherever the number also collides,
        # and saying so is the fix. A collision is not the record's
        # fault and cannot be answered on the surviving master.
        if target in collided:
            result.harmonisation_holds[material_lookup_key(row)] = HarmonisationHold(
                target_product=target,
                rule="DQ-MAT-009",
                reason="whose number is claimed by two products",
            )
            result.issues.append(
                _issue("DQ-MAT-010", Action.REJECT, "materials",
                       source_key(row, "MATNR"), "MATNR",
                       f"harmonised into product {target}, which is held back "
                       "because two products claim that number (DQ-MAT-009); "
                       "nothing on this record or on the surviving master is "
                       "wrong, and neither loads until that is settled")
            )
            continue
        result.harmonisation_holds[material_lookup_key(row)] = HarmonisationHold(
            target_product=target,
            rule="DQ-MAT-010",
            reason="which cleansing itself held back",
        )
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

        # Recorded for any row whose identity is usable, accepted or
        # not: the collision is a fact about the two extracts, and a
        # record rejected for an unrelated reason would otherwise hide
        # it until the wave that repairs the record. A row rejected
        # *because* its name or country is missing is excluded - its
        # identity is empty, so it would read as a different entity
        # rather than an unknown one.
        if row["NAME1"] and row["LAND1"]:
            # Unpadded, like the material collision rule: KUNNR and
            # LIFNR are CHAR10 and the two extract programs need not
            # pad alike, so grouping on the number as written would
            # miss GEP's 0000210045 against GVP's 210045.
            numbers[strip_leading_zeros(row[key_field])].append(
                (key, partner_identity(row))
            )

        if reject:
            result.rejected.append(row)
        else:
            result.accepted.append(row)
            seen[partner_identity(row)].append(key)

    for identity, keys in seen.items():
        if len(keys) > 1:
            systems = {key.split("/", 1)[0] for key in keys}
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
        if len({key.split("/", 1)[0] for key in keys}) > 1 and len(identities) > 1:
            # Each name carried by its own key rather than as a second
            # list beside them. Two parallel lists get read positionally,
            # and one sorted while the other is in extract order tells
            # the steward the number belongs to the wrong company in the
            # wrong system - the opposite of what this rule is for.
            named = sorted(
                f"{key} {identity[0]}" for key, identity in entries
            )
            result.issues.append(
                _issue(f"{prefix}-008", Action.WARN, object_name, ", ".join(keys),
                       key_field,
                       f"number {number} exists in both source systems as "
                       f"different entities ({'; '.join(named)}); it must "
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
    harmonisation_holds: dict[str, HarmonisationHold] | None = None,
    collision_holds: set[str] | None = None,
) -> CleanseResult:
    result = CleanseResult(object_name="batch_stock")
    holds = harmonisation_holds or {}
    collisions = collision_holds or set()

    for row in rows:
        key = f"{source_key(row, 'WERKS')}/{row['MATNR']}/{row['CHARG']}"
        reject = False
        # Padding-insensitive, like every other material join: the
        # stock extract and the material master are written by
        # different programs, and a batch padded differently from its
        # own master would be held under DQ-STK-001 as stock on a
        # material that was never migrated - the misdiagnosis
        # DQ-STK-006 and DQ-STK-007 exist to prevent.
        stock_material = material_lookup_key(row)
        material = materials.get(stock_material)

        if material is None and stock_material in holds:
            # Naming the missing master would send a steward looking
            # for a record that was deliberately retired. The work is
            # on the surviving product, or on the decision itself.
            reject = True
            hold = holds[stock_material]
            result.issues.append(
                _issue("DQ-STK-006", Action.REJECT, "batch_stock", key, "MATNR",
                       f"material was harmonised into product "
                       f"{hold.target_product}, {hold.reason} ({hold.rule}); "
                       "this stock loads once that is resolved")
            )
        elif material is None and stock_material in collisions:
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

        # Case folded on the stock side because the master side has
        # already been folded by DQ-MAT-001. Comparing the two as
        # written makes 'kg' against 'KG' a unit decision for a steward,
        # and there is no decision to take.
        if material is not None and material["MEINS"] != row["MEINS"].upper():
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
