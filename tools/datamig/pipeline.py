"""Wave pipeline: extract, cleanse, map, load, reconcile."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import cleanse, extract, load, mapping, reconcile
from .cleanse import Action, CleanseResult
from .identity import partner_identity
from .reconcile import ObjectCounts, Reconciliation


@dataclass
class PipelineResult:
    wave: str
    out_dir: Path
    cleansing: dict[str, CleanseResult] = field(default_factory=dict)
    business_partners: mapping.BusinessPartnerResult | None = None
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

    materials = cleanse.cleanse_materials(datasets["materials"].rows)
    customers = cleanse.cleanse_partners(
        datasets["customers"].rows, "customers", "KUNNR"
    )
    vendors = cleanse.cleanse_partners(datasets["vendors"].rows, "vendors", "LIFNR")

    known_partners = {row["KUNNR"] for row in customers.accepted}
    known_partners |= {row["LIFNR"] for row in vendors.accepted}
    open_items = cleanse.cleanse_open_items(
        datasets["open_items"].rows, known_partners
    )

    accepted_materials = {row["MATNR"]: row for row in materials.accepted}
    batch_stock = cleanse.cleanse_batch_stock(
        datasets["batch_stock"].rows, accepted_materials
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
    result.products = [mapping.map_material(row) for row in materials.accepted]
    result.open_items = [
        mapping.map_open_item(row, partners.xref) for row in open_items.accepted
    ]
    result.stock = [
        mapping.map_stock(row, accepted_materials) for row in batch_stock.accepted
    ]

    # The target side of each count check is read off the rows that will
    # be written, never inferred from the accepted records, so a mapping
    # that drops, duplicates or invents a record breaks the check.
    bp_rows = [partner.as_row() for partner in partners.partners]
    xref_rows = partners.xref_rows()
    loaded_sources = {
        source_type: frozenset(
            row["SourceId"] for row in xref_rows if row["SourceType"] == source_type
        )
        for source_type in ("KNA1", "LFA1")
    }

    counts = [
        ObjectCounts(
            "materials", materials.source_count, len(materials.rejected),
            len(result.products), _warnings(materials),
            source_keys=frozenset(
                mapping.strip_leading_zeros(row["MATNR"]) for row in materials.accepted
            ),
            target_keys=_keys(result.products, "Product"),
        ),
        ObjectCounts(
            "customers", customers.source_count, len(customers.rejected),
            len(customers.accepted), _warnings(customers),
            source_keys=_keys(customers.accepted, "KUNNR"),
            target_keys=loaded_sources["KNA1"],
        ),
        ObjectCounts(
            "vendors", vendors.source_count, len(vendors.rejected),
            len(vendors.accepted), _warnings(vendors),
            source_keys=_keys(vendors.accepted, "LIFNR"),
            target_keys=loaded_sources["LFA1"],
        ),
        ObjectCounts(
            "open_items", open_items.source_count, len(open_items.rejected),
            len(result.open_items), _warnings(open_items),
            source_keys=_keys(open_items.accepted, "BUKRS", "BELNR", "GJAHR", "BUZEI"),
            target_keys=_keys(
                result.open_items, "CompanyCode", "AccountingDocument",
                "FiscalYear", "AccountingDocumentItem",
            ),
        ),
        ObjectCounts(
            "batch_stock", batch_stock.source_count, len(batch_stock.rejected),
            len(result.stock), _warnings(batch_stock),
            source_keys=frozenset(
                "/".join(
                    (
                        row["WERKS"],
                        mapping.strip_leading_zeros(row["MATNR"]),
                        row["LGORT"],
                        row["CHARG"],
                    )
                )
                for row in batch_stock.accepted
            ),
            target_keys=_keys(
                result.stock, "Plant", "Product", "StorageLocation", "Batch"
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
        merged_partners=partners.merged_count,
        xref=partners.xref,
    )

    if write_files:
        _write(result, partners)

    return result


def _write(result: PipelineResult, partners: mapping.BusinessPartnerResult) -> None:
    out_dir = result.out_dir
    result.written.append(load.write_load_file(out_dir, "products", result.products))
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
