"""Mapping layer: ECC structures to the S/4HANA target model.

Three conversions carry the programme risk. The extended material
number. The customer/vendor to business partner conversion, where a
customer and a supplier that are the same legal entity collapse into a
single BP carrying both role sets. And the merge itself: two systems
load into one client, so the same counterparty held in both becomes one
BP, and products harmonised by the data council become one product.

Both merges are deliberately asymmetric in how they are decided.
Partners merge on the legal entity, which the pipeline can determine.
Products merge only where the harmonisation table says so, because
deciding that two materials are the same product is a business
decision with a regulatory consequence, not a string comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cleanse import UOM_ISO
from .extract import HarmonisationDecision
from .identity import (
    PartnerIdentity,
    partner_identity,
    source_key,
    strip_leading_zeros,
)


class MappingError(RuntimeError):
    """Raised when mapping is handed data cleansing should have held."""


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


class ProductHarmonisation:
    """The governed decision about which materials become one product.

    Keyed on (source system, material) because the two systems share
    number ranges. A material with no decision keeps its own number.
    """

    def __init__(self, decisions: list[HarmonisationDecision]) -> None:
        self._merges = {
            (decision.source_system, decision.material): decision
            for decision in decisions
            if decision.decision == "merge"
        }

    def target_product(self, row: dict[str, str]) -> str:
        decision = self._merges.get((row["SOURCE_SYSTEM"], row["MATNR"]))
        if decision:
            return decision.target_product
        return strip_leading_zeros(row["MATNR"])

    def is_merged(self, row: dict[str, str]) -> bool:
        return (row["SOURCE_SYSTEM"], row["MATNR"]) in self._merges

    @property
    def merged_materials(self) -> set[tuple[str, str]]:
        return set(self._merges)

    @property
    def targets(self) -> dict[tuple[str, str], str]:
        return {key: decision.target_product for key, decision in self._merges.items()}

    def decision_for(self, key: tuple[str, str]) -> HarmonisationDecision | None:
        return self._merges.get(key)


@dataclass
class ProductResult:
    """Products for the load, plus the material to product cross reference."""

    products: list[dict[str, str]] = field(default_factory=list)
    xref: dict[str, str] = field(default_factory=dict)
    merged_materials: list[tuple[str, str]] = field(default_factory=list)

    @property
    def merged_count(self) -> int:
        return len(self.merged_materials)

    def xref_rows(self) -> list[dict[str, str]]:
        rows = [
            {
                "SourceSystem": key.split("/")[0],
                "SourceMaterial": key.split("/")[1],
                "Product": product,
            }
            for key, product in self.xref.items()
        ]
        return sorted(rows, key=lambda row: (row["SourceSystem"], row["SourceMaterial"]))


def convert_to_products(
    materials: list[dict[str, str]], harmonisation: ProductHarmonisation
) -> ProductResult:
    """One product per target number, whichever system supplied it.

    Where two materials harmonise onto one product the surviving record
    is loaded and the retired one contributes only a cross reference
    row, so the historical number stays resolvable after cutover.
    """
    result = ProductResult()
    by_product: dict[str, dict[str, str]] = {}

    for row in materials:
        product = harmonisation.target_product(row)
        result.xref[source_key(row, "MATNR")] = product

        if harmonisation.is_merged(row):
            result.merged_materials.append((row["SOURCE_SYSTEM"], row["MATNR"]))
            continue

        # Cleansing holds back every undecided collision (DQ-MAT-009),
        # so a second record landing on a product number that is
        # already loaded cannot happen. Keeping the first and skipping
        # the second silently is what this used to do, and it loses a
        # master record with no reject to explain it - the one thing
        # the pipeline must never do.
        if product in by_product:
            raise MappingError(
                f"{source_key(row, 'MATNR')} maps to product {product}, "
                f"already loaded from {by_product[product]['SourceSystem']}; "
                "cleansing should have held both back under DQ-MAT-009"
            )

        mapped = map_material(row)
        mapped["Product"] = product
        by_product[product] = mapped
        result.products.append(mapped)

    return result


def map_material(row: dict[str, str]) -> dict[str, str]:
    return {
        "SourceSystem": row["SOURCE_SYSTEM"],
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
    source_systems: set[str] = field(default_factory=set)
    source_customers: list[str] = field(default_factory=list)
    source_vendors: list[str] = field(default_factory=list)

    @property
    def is_cross_system(self) -> bool:
        """True when the merge combined records from both ECC systems."""
        return len(self.source_systems) > 1

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
            "SourceSystems": ";".join(sorted(self.source_systems)),
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

    @property
    def cross_system_partners(self) -> list[BusinessPartner]:
        """BPs that only exist because the two systems both held them."""
        return [partner for partner in self.partners if partner.is_cross_system]

    def xref_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for partner in self.partners:
            for customer in partner.source_customers:
                system, source_id = customer.split("/")
                rows.append(
                    {
                        "SourceSystem": system,
                        "SourceType": "KNA1",
                        "SourceId": source_id,
                        "BusinessPartner": partner.bp_number,
                    }
                )
            for vendor in partner.source_vendors:
                system, source_id = vendor.split("/")
                rows.append(
                    {
                        "SourceSystem": system,
                        "SourceType": "LFA1",
                        "SourceId": source_id,
                        "BusinessPartner": partner.bp_number,
                    }
                )
        return sorted(
            rows,
            key=lambda row: (row["SourceSystem"], row["SourceType"], row["SourceId"]),
        )


def convert_to_business_partners(
    customers: list[dict[str, str]], vendors: list[dict[str, str]]
) -> BusinessPartnerResult:
    """Customer/vendor integration: one BP per legal entity."""
    result = BusinessPartnerResult()
    index: dict[PartnerIdentity, BusinessPartner] = {}
    next_number = BP_NUMBER_START

    def get_partner(row: dict[str, str]) -> BusinessPartner:
        nonlocal next_number
        identity = partner_identity(row)
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
        partner.source_systems.add(row["SOURCE_SYSTEM"])
        partner.source_customers.append(source_key(row, "KUNNR"))
        result.xref[source_key(row, "KUNNR")] = partner.bp_number

    for row in vendors:
        partner = get_partner(row)
        partner.roles.update(VENDOR_ROLES)
        partner.company_codes.add(row["BUKRS"])
        partner.source_systems.add(row["SOURCE_SYSTEM"])
        partner.source_vendors.append(source_key(row, "LIFNR"))
        result.xref[source_key(row, "LIFNR")] = partner.bp_number

    return result


def map_open_item(row: dict[str, str], xref: dict[str, str]) -> dict[str, str]:
    partner_key = source_key(row, "PARTNER") if row["PARTNER"] else ""
    return {
        "SourceSystem": row["SOURCE_SYSTEM"],
        "CompanyCode": row["BUKRS"],
        "AccountingDocument": row["BELNR"],
        "FiscalYear": row["GJAHR"],
        "AccountingDocumentItem": row["BUZEI"],
        "AccountingDocumentType": row["BLART"],
        "GLAccount": row["HKONT"],
        "BusinessPartner": xref.get(partner_key, ""),
        "SourcePartner": row["PARTNER"],
        "DebitCreditCode": row["SHKZG"],
        "AmountInCompanyCodeCurrency": row["DMBTR"],
        "CompanyCodeCurrency": row["WAERS"],
        "PostingDate": row["BUDAT"],
        "NetDueDate": row["ZFBDT"],
    }


def map_stock(
    row: dict[str, str],
    materials: dict[str, dict[str, str]],
    product_xref: dict[str, str] | None = None,
) -> dict[str, str]:
    material = materials.get(source_key(row, "MATNR"), {})
    # The unit of record is the one on the cleansed material master; the
    # stock extract's own MEINS is not validated against the ISO mapping.
    source_unit = material.get("MEINS") or row["MEINS"]
    base_unit = UOM_ISO.get(source_unit, source_unit)
    # Stock follows the harmonised product, so batches of a material
    # that was merged land on the surviving product number.
    product = (product_xref or {}).get(
        source_key(row, "MATNR"), strip_leading_zeros(row["MATNR"])
    )
    return {
        "SourceSystem": row["SOURCE_SYSTEM"],
        "Product": product,
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
