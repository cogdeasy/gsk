"""Cleansing layer: data quality rules applied before mapping.

Rules either repair a value in place (``FIX``), keep the record but
raise an exception for the data steward (``WARN``), or hold the record
back from the load (``REJECT``). Nothing is silently dropped: every
rejected record appears in the exception file and in the reconciliation
report, which is what the cutover sign-off needs.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum

ISO_COUNTRIES = {
    "GB", "DE", "FR", "BE", "IE", "US", "DK", "TZ", "SG", "CH",
    "MX", "CN", "IT", "ES", "NL", "PL", "JP", "IN", "BR", "CA",
    "AU", "ZA", "KE", "CO", "SE", "NO", "FI", "AT", "PT", "GR",
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


def cleanse_materials(rows: list[dict[str, str]]) -> CleanseResult:
    result = CleanseResult(object_name="materials")
    descriptions: dict[str, list[str]] = defaultdict(list)

    for row in rows:
        key = row["MATNR"]
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

    for description, keys in descriptions.items():
        if len(keys) > 1:
            result.issues.append(
                _issue("DQ-MAT-008", Action.WARN, "materials", ", ".join(keys),
                       "MAKTX",
                       f"duplicate material description '{description}'")
            )

    return result


def cleanse_partners(
    rows: list[dict[str, str]], object_name: str, key_field: str
) -> CleanseResult:
    result = CleanseResult(object_name=object_name)
    prefix = "DQ-CUS" if object_name == "customers" else "DQ-VEN"
    seen: dict[tuple[str, str, str], list[str]] = defaultdict(list)

    for row in rows:
        key = row[key_field]
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

        seen[(row["NAME1"], row["LAND1"], row["PSTLZ"])].append(key)

        if reject:
            result.rejected.append(row)
        else:
            result.accepted.append(row)

    for identity, keys in seen.items():
        if len(keys) > 1:
            result.issues.append(
                _issue(f"{prefix}-007", Action.WARN, object_name, ", ".join(keys),
                       "NAME1",
                       f"records merge into one business partner: {identity[0]}")
            )

    return result


def cleanse_open_items(
    rows: list[dict[str, str]], known_partners: set[str]
) -> CleanseResult:
    result = CleanseResult(object_name="open_items")
    documents: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)

    for row in rows:
        documents[(row["BUKRS"], row["BELNR"], row["GJAHR"])].append(row)

    for (bukrs, belnr, gjahr), lines in documents.items():
        key = f"{bukrs}/{belnr}/{gjahr}"
        reject_document = False

        debit = sum(float(line["DMBTR"]) for line in lines if line["SHKZG"] == "S")
        credit = sum(float(line["DMBTR"]) for line in lines if line["SHKZG"] == "H")
        if round(debit - credit, 2) != 0:
            reject_document = True
            result.issues.append(
                _issue("DQ-FI-001", Action.REJECT, "open_items", key, "DMBTR",
                       f"document does not balance: debit {debit:.2f} "
                       f"credit {credit:.2f}")
            )

        for line in lines:
            partner = line["PARTNER"]
            if partner and partner not in known_partners:
                reject_document = True
                result.issues.append(
                    _issue("DQ-FI-002", Action.REJECT, "open_items", key, "PARTNER",
                           f"partner {partner} is not in the migrated master data")
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
    rows: list[dict[str, str]], materials: dict[str, dict[str, str]]
) -> CleanseResult:
    result = CleanseResult(object_name="batch_stock")

    for row in rows:
        key = f"{row['WERKS']}/{row['MATNR']}/{row['CHARG']}"
        reject = False
        material = materials.get(row["MATNR"])

        if material is None:
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
