"""Partner identity: the key that decides which records become one BP.

Cleansing warns that records will merge and mapping performs the merge.
If the two key on different fields the exception report describes a
conversion the load never makes, so both import the key from here.
"""

from __future__ import annotations

PartnerIdentity = tuple[str, str, str, str]


def partner_identity(row: dict[str, str]) -> PartnerIdentity:
    """Name, country, postal code and VAT number, case normalised."""
    return (
        row["NAME1"].upper(),
        row["LAND1"].upper(),
        row["PSTLZ"].upper(),
        row.get("STCEG", "").upper(),
    )
