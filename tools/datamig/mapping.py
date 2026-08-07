"""Mapping layer: ECC structures to the S/4HANA target model.

The two substantive conversions here are the ones that carry the
programme risk: the extended material number, and the customer/vendor
to business partner conversion, where a customer and a supplier that
are the same legal entity must collapse into a single BP carrying both
role sets.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cleanse import UOM_ISO

BP_NUMBER_START = 1000000
BP_GROUPING = "BPGS"

MATERIAL_TYPE_TO_PRODUCT_TYPE = {
    "FERT": "FERT",
    "HALB": "HALB",
    "ROH": "ROH",
    "VERP": "VERP",
}

CUSTOMER_ROLES = ("FLCU00", "FLCU01")
VENDOR_ROLES = ("FLVN00", "FLVN01")


def strip_leading_zeros(material: str) -> str:
    """ECC stores MATNR zero padded to 18; S/4HANA keeps it unpadded."""
    return material.lstrip("0") or "0"


def map_material(row: dict[str, str]) -> dict[str, str]:
    return {
        "Product": strip_leading_zeros(row["MATNR"]),
        "ProductType": MATERIAL_TYPE_TO_PRODUCT_TYPE.get(row["MTART"], row["MTART"]),
        "ProductGroup": row["MATKL"],
        "BaseUnit": UOM_ISO[row["MEINS"]],
        "GrossWeight": row["BRGEW"],
        "WeightUnit": UOM_ISO.get(row["GEWEI"], row["GEWEI"]),
        "Division": row["SPART"],
        "BatchManagement": "true" if row["XCHPF"] == "X" else "false",
        "ShelfLifeDays": row["MHDHB"],
        "StorageConditionClass": row["ZZ_TEMP_CLASS"],
        "ProductDescription": row["MAKTX"],
        "Plant": row["WERKS"],
        "MRPController": row["DISPO"],
    }


@dataclass
class BusinessPartner:
    bp_number: str
    name: str
    country: str
    city: str
    postal_code: str
    street: str
    vat_number: str
    roles: set[str] = field(default_factory=set)
    company_codes: set[str] = field(default_factory=set)
    source_customers: list[str] = field(default_factory=list)
    source_vendors: list[str] = field(default_factory=list)

    def as_row(self) -> dict[str, str]:
        return {
            "BusinessPartner": self.bp_number,
            "BusinessPartnerGrouping": BP_GROUPING,
            "BusinessPartnerName": self.name,
            "Country": self.country,
            "CityName": self.city,
            "PostalCode": self.postal_code,
            "StreetName": self.street,
            "VATRegistration": self.vat_number,
            "BusinessPartnerRoles": ";".join(sorted(self.roles)),
            "CompanyCodes": ";".join(sorted(self.company_codes)),
            "SourceCustomers": ";".join(self.source_customers),
            "SourceVendors": ";".join(self.source_vendors),
        }


@dataclass
class BusinessPartnerResult:
    partners: list[BusinessPartner] = field(default_factory=list)
    xref: dict[str, str] = field(default_factory=dict)

    @property
    def merged_count(self) -> int:
        """Source records that were absorbed into a shared BP."""
        sources = sum(
            len(partner.source_customers) + len(partner.source_vendors)
            for partner in self.partners
        )
        return sources - len(self.partners)

    def xref_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for partner in self.partners:
            for customer in partner.source_customers:
                rows.append(
                    {
                        "SourceType": "KNA1",
                        "SourceId": customer,
                        "BusinessPartner": partner.bp_number,
                    }
                )
            for vendor in partner.source_vendors:
                rows.append(
                    {
                        "SourceType": "LFA1",
                        "SourceId": vendor,
                        "BusinessPartner": partner.bp_number,
                    }
                )
        return sorted(rows, key=lambda row: (row["SourceType"], row["SourceId"]))


def _identity(row: dict[str, str]) -> tuple[str, str, str, str]:
    """Records sharing this identity become one business partner."""
    return (
        row["NAME1"].upper(),
        row["LAND1"].upper(),
        row["PSTLZ"].upper(),
        row.get("STCEG", "").upper(),
    )


def convert_to_business_partners(
    customers: list[dict[str, str]], vendors: list[dict[str, str]]
) -> BusinessPartnerResult:
    """Customer/vendor integration: one BP per legal entity."""
    result = BusinessPartnerResult()
    index: dict[tuple[str, str, str, str], BusinessPartner] = {}
    next_number = BP_NUMBER_START

    def get_partner(row: dict[str, str]) -> BusinessPartner:
        nonlocal next_number
        identity = _identity(row)
        partner = index.get(identity)
        if partner is None:
            partner = BusinessPartner(
                bp_number=str(next_number),
                name=row["NAME1"],
                country=row["LAND1"],
                city=row["ORT01"],
                postal_code=row["PSTLZ"],
                street=row["STRAS"],
                vat_number=row.get("STCEG", ""),
            )
            next_number += 1
            index[identity] = partner
            result.partners.append(partner)
        return partner

    for row in customers:
        partner = get_partner(row)
        partner.roles.update(CUSTOMER_ROLES)
        partner.company_codes.add(row["BUKRS"])
        partner.source_customers.append(row["KUNNR"])
        result.xref[row["KUNNR"]] = partner.bp_number

    for row in vendors:
        partner = get_partner(row)
        partner.roles.update(VENDOR_ROLES)
        partner.company_codes.add(row["BUKRS"])
        partner.source_vendors.append(row["LIFNR"])
        result.xref[row["LIFNR"]] = partner.bp_number

    return result


def map_open_item(row: dict[str, str], xref: dict[str, str]) -> dict[str, str]:
    return {
        "CompanyCode": row["BUKRS"],
        "AccountingDocument": row["BELNR"],
        "FiscalYear": row["GJAHR"],
        "AccountingDocumentItem": row["BUZEI"],
        "AccountingDocumentType": row["BLART"],
        "GLAccount": row["HKONT"],
        "BusinessPartner": xref.get(row["PARTNER"], ""),
        "SourcePartner": row["PARTNER"],
        "DebitCreditCode": row["SHKZG"],
        "AmountInCompanyCodeCurrency": row["DMBTR"],
        "CompanyCodeCurrency": row["WAERS"],
        "PostingDate": row["BUDAT"],
        "NetDueDate": row["ZFBDT"],
    }


def map_stock(row: dict[str, str], materials: dict[str, dict[str, str]]) -> dict[str, str]:
    material = materials.get(row["MATNR"], {})
    base_unit = UOM_ISO.get(row["MEINS"], row["MEINS"])
    return {
        "Product": strip_leading_zeros(row["MATNR"]),
        "Plant": row["WERKS"],
        "StorageLocation": row["LGORT"],
        "Batch": row["CHARG"],
        "UnrestrictedQuantity": row["CLABS"],
        "QualityInspectionQuantity": row["CINSM"],
        "BlockedQuantity": row["CSPEM"],
        "BaseUnit": base_unit,
        "ShelfLifeExpirationDate": row["VFDAT"],
        "ManufactureDate": row["HSDAT"],
        "BatchStatus": row["ZUSTD"],
        "StorageConditionClass": material.get("ZZ_TEMP_CLASS", ""),
    }
