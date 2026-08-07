"""Record identity across the two ECC source systems.

Two keys matter and they must not be confused.

``source_key`` identifies a record in its own system. The two systems
share number ranges, so it is only unique when qualified with the
system name - ``GEP/0000210045`` and ``GVP/0000210045`` are different
companies.

``partner_identity`` identifies a legal entity regardless of which
system holds it, and is what decides that two records become one
business partner. It deliberately ignores the source number: keying
the merge on the number would combine the two unrelated companies
above, and would miss the same customer held under two numbers.

Cleansing warns that records will merge and mapping performs the merge.
If the two key on different fields the exception report describes a
conversion the load never makes, so both import the keys from here.
"""

from __future__ import annotations

PartnerIdentity = tuple[str, str, str, str]


def strip_leading_zeros(material: str) -> str:
    """ECC stores MATNR zero padded to 18; S/4HANA keeps it unpadded."""
    return material.lstrip("0") or "0"


def source_key(row: dict[str, str], key_field: str) -> str:
    """The record's key, qualified with its source system."""
    return f"{row['SOURCE_SYSTEM']}/{row[key_field]}"


def split_source_key(key: str) -> tuple[str, str]:
    """The inverse of `source_key`, splitting on the first slash only.

    SAP numbers assigned from an external range may contain a slash -
    a material `ABC/123` is legal - so splitting on every separator
    would raise on the unpack, or silently truncate the number written
    to a cross reference load file. Only the first slash is the one
    this module put there.
    """
    system, _, record = key.partition("/")
    return (system, record)


def material_key(source_system: str, material: str) -> tuple[str, str]:
    """The key a harmonisation decision is matched on.

    Qualified with the system, because the two share number ranges, and
    unpadded, because ECC writes MATNR padded to 18 and a steward
    writing the number into the decision table does not. Matching on
    the raw string would make a governed merge depend on how the
    number was typed: the decision would silently not apply, the
    duplicate would load under its own number with its stock, and
    REC-MRG-004 would report it as naming a material that is not in
    the extract - which is the one thing it is not.
    """
    return (source_system, strip_leading_zeros(material))


def material_lookup_key(row: dict[str, str]) -> str:
    """The key a material row is found by, from any extract.

    `material_key` in string form, for the dictionaries that join stock
    to its master. The join has to be padding-insensitive for the same
    reason the harmonisation table is: the two extracts are written by
    different programs in different systems, and a batch whose MATNR is
    padded differently from its own material master would be reported
    as stock on a material that was never migrated - when it is sitting
    in the load file.

    Exception keys are built with `source_key` instead, so a steward
    sees the number as their extract spells it.
    """
    system, material = material_key(row["SOURCE_SYSTEM"], row["MATNR"])
    return f"{system}/{material}"


def partner_identity(row: dict[str, str]) -> PartnerIdentity:
    """Name, country, postal code and VAT number, case normalised."""
    return (
        row["NAME1"].upper(),
        row["LAND1"].upper(),
        row["PSTLZ"].upper(),
        row.get("STCEG", "").upper(),
    )
