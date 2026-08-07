"""Wave pipeline: extract, cleanse, map, load, reconcile.

Both ECC systems are processed in one run rather than one after the
other. The merge is the reason: whether two records become one target
record can only be decided with both systems in front of you, and the
reconciliation has to prove the resulting arithmetic - source records
minus merges equals target records - across the pair.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import cleanse, extract, load, mapping, reconcile
from .cleanse import Action, CleanseResult
from .identity import material_key, partner_identity, source_key
from .reconcile import ObjectCounts, Reconciliation


@dataclass
class PipelineResult:
    wave: str
    out_dir: Path
    cleansing: dict[str, CleanseResult] = field(default_factory=dict)
    business_partners: mapping.BusinessPartnerResult | None = None
    product_result: mapping.ProductResult | None = None
    products: list[dict[str, str]] = field(default_factory=list)
    open_items: list[dict[str, str]] = field(default_factory=list)
    stock: list[dict[str, str]] = field(default_factory=list)
    reconciliation: Reconciliation | None = None
    written: list[Path] = field(default_factory=list)

    @property
    def all_issues(self):
        return [
            issue
            for result in self.cleansing.values()
            for issue in result.issues
        ]

    @property
    def rejected_count(self) -> int:
        return sum(len(result.rejected) for result in self.cleansing.values())


def _warnings(result: CleanseResult) -> int:
    return result.counts_by_action()[Action.WARN.value]


def _keys(rows: list[dict[str, str]], *fields: str) -> frozenset[str]:
    return frozenset("/".join(row[field] for field in fields) for row in rows)


def run(
    wave: str,
    source_dir: str | Path,
    out_dir: str | Path,
    write_files: bool = True,
) -> PipelineResult:
    out_path = Path(out_dir)
    result = PipelineResult(wave=wave, out_dir=out_path)

    datasets = extract.extract_wave(source_dir)
    harmonisation = mapping.ProductHarmonisation(
        extract.read_harmonisation(Path(source_dir) / extract.HARMONISATION_FILE)
    )

    materials = cleanse.cleanse_materials(
        datasets["materials"].rows, harmonisation.targets
    )
    customers = cleanse.cleanse_partners(
        datasets["customers"].rows, "customers", "KUNNR"
    )
    vendors = cleanse.cleanse_partners(datasets["vendors"].rows, "vendors", "LIFNR")

    known_partners = {source_key(row, "KUNNR") for row in customers.accepted}
    known_partners |= {source_key(row, "LIFNR") for row in vendors.accepted}
    open_items = cleanse.cleanse_open_items(
        datasets["open_items"].rows, known_partners
    )

    accepted_materials = {
        source_key(row, "MATNR"): row for row in materials.accepted
    }
    batch_stock = cleanse.cleanse_batch_stock(
        datasets["batch_stock"].rows,
        accepted_materials,
        materials.harmonisation_holds,
        materials.collision_holds,
    )

    result.cleansing = {
        "materials": materials,
        "customers": customers,
        "vendors": vendors,
        "open_items": open_items,
        "batch_stock": batch_stock,
    }

    partners = mapping.convert_to_business_partners(
        customers.accepted, vendors.accepted
    )
    result.business_partners = partners
    products = mapping.convert_to_products(materials.accepted, harmonisation)
    result.product_result = products
    result.products = products.products
    result.open_items = [
        mapping.map_open_item(row, partners.xref) for row in open_items.accepted
    ]
    result.stock = [
        mapping.map_stock(row, accepted_materials, products.xref)
        for row in batch_stock.accepted
    ]

    # The target side of each count check is read off the rows that will
    # be written, never inferred from the accepted records, so a mapping
    # that drops, duplicates or invents a record breaks the check.
    bp_rows = [partner.as_row() for partner in partners.partners]
    xref_rows = partners.xref_rows()
    # Counted off the cross reference that will be written rather than
    # off the mapping's own tally. Taking it from BusinessPartnerResult
    # makes REC-MRG-001 compare a number with itself: a record lost
    # between cleansing and load would move both sides together.
    merged_partners = len(xref_rows) - len(
        {row["BusinessPartner"] for row in xref_rows}
    )
    loaded_sources = {
        source_type: frozenset(
            f"{row['SourceSystem']}/{row['SourceId']}"
            for row in xref_rows
            if row["SourceType"] == source_type
        )
        for source_type in ("KNA1", "LFA1")
    }

    counts = [
        ObjectCounts(
            "materials", materials.source_count, len(materials.rejected),
            len(result.products), _warnings(materials),
            # Expected is the set of harmonised product numbers, not
            # the set of source materials: merged materials are
            # deliberately absent from the load file. Derived from the
            # accepted ECC rows and the governed decision table rather
            # than from the mapping's own cross reference, so a defect
            # in the mapping cannot cancel itself out on both sides.
            # A merged material contributes its survivor's key, so this
            # check sees a dropped, duplicated or invented record only
            # for the materials that keep their own number. The merged
            # ones are covered by REC-MRG-002 and REC-MRG-003.
            source_keys=frozenset(
                harmonisation.target_product(row) for row in materials.accepted
            ),
            target_keys=_keys(result.products, "Product"),
            merged=products.merged_count,
        ),
        # `loaded` is the count of rows that will be written, not of
        # records that survived cleansing. For a customer that is the
        # KNA1 side of the cross reference: partners are merged, so
        # there is no one row per record to count, and taking it from
        # `accepted` would make REC-ARI-customers restate its own
        # source side and pass however many records mapping lost.
        ObjectCounts(
            "customers", customers.source_count, len(customers.rejected),
            len(loaded_sources["KNA1"]), _warnings(customers),
            source_keys=frozenset(
                source_key(row, "KUNNR") for row in customers.accepted
            ),
            target_keys=loaded_sources["KNA1"],
        ),
        ObjectCounts(
            "vendors", vendors.source_count, len(vendors.rejected),
            len(loaded_sources["LFA1"]), _warnings(vendors),
            source_keys=frozenset(
                source_key(row, "LIFNR") for row in vendors.accepted
            ),
            target_keys=loaded_sources["LFA1"],
        ),
        ObjectCounts(
            "open_items", open_items.source_count, len(open_items.rejected),
            len(result.open_items), _warnings(open_items),
            source_keys=_keys(
                open_items.accepted,
                "SOURCE_SYSTEM", "BUKRS", "BELNR", "GJAHR", "BUZEI",
            ),
            target_keys=_keys(
                result.open_items, "SourceSystem", "CompanyCode",
                "AccountingDocument", "FiscalYear", "AccountingDocumentItem",
            ),
        ),
        ObjectCounts(
            "batch_stock", batch_stock.source_count, len(batch_stock.rejected),
            len(result.stock), _warnings(batch_stock),
            # Derived from the governed decision table for the same
            # reason as the materials check above: map_stock resolves
            # the product through products.xref, so reading the ECC
            # side out of that same cross reference would move both
            # sides together and a batch put onto the wrong survivor
            # would reconcile clean.
            source_keys=frozenset(
                "/".join(
                    (
                        row["SOURCE_SYSTEM"],
                        row["WERKS"],
                        harmonisation.target_product(row),
                        row["LGORT"],
                        row["CHARG"],
                    )
                )
                for row in batch_stock.accepted
            ),
            target_keys=_keys(
                result.stock, "SourceSystem", "Plant", "Product",
                "StorageLocation", "Batch",
            ),
        ),
    ]

    accepted_partner_rows = customers.accepted + vendors.accepted
    result.reconciliation = reconcile.build(
        wave=wave,
        counts=counts,
        accepted_open_items=open_items.accepted,
        loaded_open_items=result.open_items,
        accepted_stock=batch_stock.accepted,
        loaded_stock=result.stock,
        accepted_partners=len(accepted_partner_rows),
        partner_identities=len(
            {partner_identity(row) for row in accepted_partner_rows}
        ),
        business_partners=len({row["BusinessPartner"] for row in bp_rows}),
        merged_partners=merged_partners,
        xref=partners.xref,
        cross_system_partners=len(partners.cross_system_partners),
        source_systems=sorted(extract.SOURCE_SYSTEMS),
        accepted_by_system=_accepted_by_system(result.cleansing),
        products=products,
        harmonisation=harmonisation,
        # Same key the decisions are held under, or a decision written
        # with an unpadded number would look unapplied rather than held.
        rejected_materials={
            material_key(row["SOURCE_SYSTEM"], row["MATNR"])
            for row in materials.rejected
        },
        accepted_materials=materials.accepted,
        # Every number the extract knows about, accepted or not. A
        # harmonisation decision naming a product outside this set names
        # a product that exists in neither system.
        extracted_products={
            mapping.strip_leading_zeros(row["MATNR"])
            for row in datasets["materials"].rows
        },
    )

    if write_files:
        _write(result, partners)

    return result


def _accepted_by_system(
    cleansing: dict[str, CleanseResult],
) -> dict[str, dict[str, int]]:
    """Accepted record counts per object per source system."""
    counts: dict[str, dict[str, int]] = {}
    for name, cleanse_result in cleansing.items():
        per_system: dict[str, int] = {}
        for row in cleanse_result.accepted:
            system = row["SOURCE_SYSTEM"]
            per_system[system] = per_system.get(system, 0) + 1
        counts[name] = dict(sorted(per_system.items()))
    return counts


def _write(result: PipelineResult, partners: mapping.BusinessPartnerResult) -> None:
    out_dir = result.out_dir
    result.written.append(load.write_load_file(out_dir, "products", result.products))
    result.written.append(
        load.write_load_file(
            out_dir, "product_xref", result.product_result.xref_rows()
        )
    )
    result.written.append(
        load.write_load_file(
            out_dir, "business_partners",
            [partner.as_row() for partner in partners.partners],
        )
    )
    result.written.append(
        load.write_load_file(out_dir, "bp_xref", partners.xref_rows())
    )
    result.written.append(
        load.write_load_file(out_dir, "open_items", result.open_items)
    )
    result.written.append(load.write_load_file(out_dir, "stock", result.stock))

    for name, cleanse_result in result.cleansing.items():
        result.written.append(
            load.write_exceptions(out_dir, name, cleanse_result.issues)
        )
        result.written.append(
            load.write_rejects(out_dir, name, cleanse_result.rejected)
        )

    reconciliation_path = out_dir / "reconciliation.md"
    reconciliation_path.write_text(
        reconcile.to_markdown(result.reconciliation), encoding="utf-8"
    )
    result.written.append(reconciliation_path)

    json_path = out_dir / "reconciliation.json"
    json_path.write_text(reconcile.to_json(result.reconciliation), encoding="utf-8")
    result.written.append(json_path)
