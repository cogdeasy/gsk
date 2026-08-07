import copy
import shutil
from collections import Counter
from pathlib import Path

import pytest

from datamig import cleanse, extract, mapping, pipeline
from datamig.cleanse import Action
from datamig.identity import partner_identity, source_key

REPO_ROOT = Path(__file__).resolve().parents[1]
WAVE0 = REPO_ROOT / "data" / "wave0"


@pytest.fixture(scope="module")
def result():
    return pipeline.run(
        wave="wave0", source_dir=WAVE0, out_dir=Path("/tmp/unused"), write_files=False
    )


def test_extract_reads_every_wave_object():
    datasets = extract.extract_wave(WAVE0)
    assert set(datasets) == set(extract.EXTRACT_FILES)
    assert all(len(dataset) > 0 for dataset in datasets.values())


def test_extract_reads_both_source_systems():
    datasets = extract.extract_wave(WAVE0)
    for dataset in datasets.values():
        systems = {row["SOURCE_SYSTEM"] for row in dataset.rows}
        assert systems == set(extract.SOURCE_SYSTEMS)
        assert dataset.for_system("GVP")


def test_extract_raises_when_a_source_system_is_absent(tmp_path):
    for filename in extract.EXTRACT_FILES.values():
        path = tmp_path / "gep" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    with pytest.raises(extract.ExtractError, match="GVP"):
        extract.extract_wave(tmp_path)


def test_the_same_number_in_both_systems_is_two_records(result):
    customers = result.cleansing["customers"]
    clashing = [row for row in customers.accepted if row["KUNNR"] == "0000210045"]
    assert {row["SOURCE_SYSTEM"] for row in clashing} == {"GEP", "GVP"}
    assert len({row["NAME1"] for row in clashing}) == 2

    bps = {
        result.business_partners.xref[source_key(row, "KUNNR")]
        for row in clashing
    }
    assert len(bps) == 2


def test_extract_raises_for_a_missing_wave(tmp_path):
    with pytest.raises(extract.ExtractError):
        extract.extract_wave(tmp_path / "nope")


def _material(
    system: str, number: str, description: str = "TEST", unit: str = "ST"
) -> dict[str, str]:
    """A material row that cleanses without incident unless altered."""
    return {
        "SOURCE_SYSTEM": system, "MATNR": number, "MTART": "FERT",
        "MATKL": "X", "MEINS": unit, "BRGEW": "1.0", "GEWEI": "KG",
        "SPART": "01", "XCHPF": "X", "MHDHB": "365",
        "ZZ_TEMP_CLASS": "15-25C", "MAKTX": description,
        "WERKS": "GB21", "DISPO": "101",
    }


def test_lower_case_base_unit_is_repaired():
    outcome = cleanse.cleanse_materials([_material("GEP", "1", unit="st")])
    assert outcome.accepted[0]["MEINS"] == "ST"
    assert outcome.issues_for("DQ-MAT-001")[0].action is Action.FIX


def test_batch_managed_material_without_shelf_life_is_rejected(result):
    materials = result.cleansing["materials"]
    rejected = {row["MATNR"] for row in materials.rejected}
    assert "000000000000100237" in rejected
    assert materials.issues_for("DQ-MAT-006")


def test_invalid_country_code_is_rejected(result):
    customers = result.cleansing["customers"]
    rejected = {
        source_key(row, "KUNNR")
        for row in customers.rejected
        if any(
            issue.rule_id == "DQ-CUS-003"
            and issue.key == source_key(row, "KUNNR")
            for issue in customers.issues
        )
    }
    assert rejected == {"GEP/0000210060"}


def test_unbalanced_document_is_rejected(result):
    issues = result.cleansing["open_items"].issues_for("DQ-FI-001")
    assert sorted(issue.key for issue in issues) == [
        "GEP/IE01/4900000772/2026",
        "GVP/BE02/1900008805/2026",
    ]


def test_open_item_for_an_unknown_partner_is_rejected(result):
    issues = result.cleansing["open_items"].issues_for("DQ-FI-002")
    assert issues and "0000210099" in issues[0].message


def test_stock_for_a_rejected_material_does_not_load(result):
    loaded_products = {row["Product"] for row in result.products}
    for row in result.stock:
        assert row["Product"] in loaded_products


def test_a_partner_held_in_both_systems_becomes_one_business_partner(result):
    unicef = next(
        partner
        for partner in result.business_partners.partners
        if partner.name == "UNICEF SUPPLY DIVISION"
    )
    assert unicef.source_customers == ["GEP/0000210050", "GVP/0000210112"]
    assert unicef.source_systems == {"GEP", "GVP"}
    assert unicef.is_cross_system


def test_cross_system_partners_are_reported_as_merge_evidence(result):
    cross_system = result.business_partners.cross_system_partners
    assert cross_system
    assert all(partner.is_cross_system for partner in cross_system)
    names = {partner.name for partner in cross_system}
    assert {"UNICEF SUPPLY DIVISION", "PAHO REVOLVING FUND"} <= names


def test_a_number_reused_across_systems_raises_a_collision_warning(result):
    issues = result.cleansing["customers"].issues_for("DQ-CUS-008")
    assert issues
    assert "0000210045" in issues[0].message
    assert issues[0].action is Action.WARN


def test_harmonised_materials_collapse_into_one_product(result):
    products = {row["Product"] for row in result.products}
    xref = result.product_result.xref

    # The Wavre record for the same finished vaccine is retired, and
    # resolves to the surviving core product rather than its own number.
    assert xref["GVP/000000000000700302"] == "100236"
    assert "100236" in products
    assert "700302" not in products


def test_every_source_material_stays_resolvable_after_the_merge(result):
    accepted = result.cleansing["materials"].accepted
    xref = result.product_result.xref
    loaded = {row["Product"] for row in result.products}
    for row in accepted:
        assert xref[source_key(row, "MATNR")] in loaded


def test_a_merge_onto_a_rejected_product_is_held_back(result):
    materials = result.cleansing["materials"]
    orphaned = materials.issues_for("DQ-MAT-010")
    assert [issue.key for issue in orphaned] == ["GVP/000000000000700301"]
    assert orphaned[0].action is Action.REJECT
    assert "GVP/000000000000700301" not in result.product_result.xref


def test_stock_from_both_systems_lands_on_the_harmonised_product(result):
    rows = [row for row in result.stock if row["Product"] == "100236"]
    assert {row["SourceSystem"] for row in rows} == {"GEP", "GVP"}


def test_the_merge_arithmetic_is_reconciled(result):
    checks = {check.id: check for check in result.reconciliation.checks}
    for check_id in ("REC-MRG-001", "REC-MRG-002", "REC-MRG-003", "REC-MRG-004"):
        assert checks[check_id].passed, check_id


def test_a_decision_held_back_by_cleansing_is_accounted_for(result):
    """The material was rejected, so the merge legitimately did not run."""
    check = next(
        check for check in result.reconciliation.checks if check.id == "REC-MRG-004"
    )
    assert check.passed
    assert "GVP/000000000000700301" in check.note
    assert "held back by cleansing" in check.note


def test_a_harmonisation_decision_for_an_absent_material_fails_the_wave(tmp_path):
    """A decision nothing else would notice was never carried out."""
    source = tmp_path / "wave0"
    shutil.copytree(WAVE0, source)
    with open(source / extract.HARMONISATION_FILE, "a", encoding="utf-8") as handle:
        handle.write(
            "GVP,000000000000799999,100236,merge,Material is not in the extract\n"
        )

    outcome = pipeline.run(
        wave="wave0", source_dir=source, out_dir=tmp_path / "out", write_files=False
    )
    check = next(
        check for check in outcome.reconciliation.checks if check.id == "REC-MRG-004"
    )
    assert not check.passed
    assert "GVP/000000000000799999" in check.note
    assert not outcome.reconciliation.passed


def test_a_decision_naming_a_product_in_neither_system_fails_the_wave(tmp_path):
    """Not a hold: the survivor does not exist, so the merge cannot run.

    Cleansing holds the record back either way, which is exactly what a
    legitimate hold looks like from the load file. Only the decision
    table says which of the two it is.
    """
    source = tmp_path / "wave0"
    shutil.copytree(WAVE0, source)
    with open(source / extract.HARMONISATION_FILE, "a", encoding="utf-8") as handle:
        handle.write(
            "GVP,000000000000700310,999999,merge,Survivor is in neither system\n"
        )

    outcome = pipeline.run(
        wave="wave0", source_dir=source, out_dir=tmp_path / "out", write_files=False
    )
    check = next(
        check for check in outcome.reconciliation.checks if check.id == "REC-MRG-004"
    )
    assert not check.passed
    assert "in neither system" in check.note
    assert "GVP/000000000000700310 -> 999999" in check.note
    assert not outcome.reconciliation.passed


def test_a_stranded_merge_survivor_fails_the_wave(result):
    """REC-MRG-003 has to notice a survivor missing from the load file."""
    from datamig import reconcile

    harmonisation = mapping.ProductHarmonisation(
        extract.read_harmonisation(WAVE0 / extract.HARMONISATION_FILE)
    )
    accepted = result.cleansing["materials"].accepted
    survivors = {
        harmonisation.target_product(row)
        for row in accepted
        if harmonisation.is_merged(row)
    }
    assert survivors, "fixture must apply at least one merge"

    dropped = sorted(survivors)[0]
    products = copy.copy(result.product_result)
    products.products = [
        row for row in result.product_result.products if row["Product"] != dropped
    ]

    broken = reconcile.build(
        wave="wave0",
        counts=[],
        accepted_open_items=[],
        loaded_open_items=[],
        accepted_stock=[],
        loaded_stock=[],
        accepted_partners=0,
        partner_identities=0,
        business_partners=0,
        merged_partners=0,
        xref={},
        products=products,
        harmonisation=harmonisation,
        accepted_materials=accepted,
    )
    check = next(c for c in broken.checks if c.id == "REC-MRG-003")
    assert not check.passed
    assert dropped in check.note


def test_a_material_the_mapping_never_saw_fails_the_wave(result):
    """REC-MRG-002 counts its source side on the ECC side, not the load.

    A row the mapping skips outright leaves no xref entry and no
    product, so reading both numbers off the mapping would drop it from
    each side of the equality and still balance.
    """
    from datamig import reconcile

    harmonisation = mapping.ProductHarmonisation(
        extract.read_harmonisation(WAVE0 / extract.HARMONISATION_FILE)
    )
    accepted = result.cleansing["materials"].accepted
    skipped = next(row for row in accepted if not harmonisation.is_merged(row))
    number = mapping.strip_leading_zeros(skipped["MATNR"])

    products = copy.copy(result.product_result)
    products.products = [
        row for row in result.product_result.products if row["Product"] != number
    ]

    broken = reconcile.build(
        wave="wave0",
        counts=[],
        accepted_open_items=[],
        loaded_open_items=[],
        accepted_stock=[],
        loaded_stock=[],
        accepted_partners=0,
        partner_identities=0,
        business_partners=0,
        merged_partners=0,
        xref={},
        products=products,
        harmonisation=harmonisation,
        accepted_materials=accepted,
    )
    check = next(c for c in broken.checks if c.id == "REC-MRG-002")
    assert not check.passed


def test_a_lost_partner_record_fails_the_merge_arithmetic(result):
    """REC-MRG-001 has to notice a record that never reached the load."""
    from datamig import reconcile

    # Drop one source record from a BP that several records share, so
    # the BP itself survives - exactly the loss that is hard to see.
    rows = result.business_partners.xref_rows()
    shared = Counter(row["BusinessPartner"] for row in rows)
    lost = next(row for row in rows if shared[row["BusinessPartner"]] > 1)
    xref_rows = [row for row in rows if row is not lost]
    merged = len(xref_rows) - len({row["BusinessPartner"] for row in xref_rows})

    broken = reconcile.build(
        wave="wave0",
        counts=result.reconciliation.counts,
        accepted_open_items=result.cleansing["open_items"].accepted,
        loaded_open_items=result.open_items,
        accepted_stock=result.cleansing["batch_stock"].accepted,
        loaded_stock=result.stock,
        accepted_partners=len(result.cleansing["customers"].accepted)
        + len(result.cleansing["vendors"].accepted),
        partner_identities=len(result.business_partners.partners),
        business_partners=len(result.business_partners.partners),
        merged_partners=merged,
        xref=result.business_partners.xref,
    )
    check = next(c for c in broken.checks if c.id == "REC-MRG-001")
    assert not check.passed


def test_stock_stranded_by_a_number_collision_says_so():
    """A held-back collision must not read as a missing master.

    Sending a steward to look for a material that was deliberately not
    loaded is the failure DQ-STK-006 exists to prevent; the collision
    hold needs the same treatment.
    """
    materials = cleanse.cleanse_materials(
        [
            _material("GEP", "000000000000100801", "CORE ADJUVANT"),
            _material("GVP", "000000000000100801", "ANTIGEN BULK RSV"),
        ]
    )
    assert materials.collision_holds

    stock = cleanse.cleanse_batch_stock(
        [
            {
                "SOURCE_SYSTEM": "GVP", "WERKS": "BE32",
                "MATNR": "000000000000100801", "CHARG": "AB2600099",
                "LGORT": "0001", "CLABS": "10.000", "CINSM": "0.000",
                "CSPEM": "0.000", "MEINS": "ST",
                "VFDAT": "20270101", "HSDAT": "20260101", "ZUSTD": "",
            }
        ],
        materials={},
        harmonisation_holds=materials.harmonisation_holds,
        collision_holds=materials.collision_holds,
    )

    collision = stock.issues_for("DQ-STK-007")
    assert [issue.key for issue in collision] == [
        "GVP/BE32/000000000000100801/AB2600099"
    ]
    assert "DQ-MAT-009" in collision[0].message
    assert not stock.issues_for("DQ-STK-001")


def test_stock_stranded_by_a_harmonisation_says_so(result):
    """Not 'no such material' - the material was deliberately retired."""
    stock = result.cleansing["batch_stock"]
    cascade = stock.issues_for("DQ-STK-006")
    assert [issue.key for issue in cascade] == [
        "GVP/BE32/000000000000700301/AB2600041",
        "GVP/BE32/000000000000700301/AB2600042",
    ]
    assert "100251" in cascade[0].message
    assert "DQ-MAT-010" in cascade[0].message

    stranded = {issue.key for issue in stock.issues_for("DQ-STK-001")}
    assert not any("700301" in key for key in stranded)


def test_a_material_number_used_in_both_systems_is_held_back():
    """The two systems share number ranges, so MATNR alone is ambiguous.

    Both records must wait: the target product number is the bare
    number, so loading them would keep one master, discard the other
    and silently move its batches onto an unrelated product.
    """
    rows = [
        _material("GEP", "000000000000100801", "CORE ADJUVANT"),
        _material("GVP", "000000000000100801", "ANTIGEN BULK RSV"),
    ]
    outcome = cleanse.cleanse_materials(rows)
    collisions = outcome.issues_for("DQ-MAT-009")
    assert len(collisions) == 1
    assert collisions[0].action is Action.REJECT
    assert "GEP/000000000000100801" in collisions[0].key
    assert "GVP/000000000000100801" in collisions[0].key
    assert outcome.accepted == []
    assert len(outcome.rejected) == 2


def test_a_governed_decision_resolves_a_shared_material_number():
    """The collision is only a collision while nobody has decided."""
    rows = [
        _material("GEP", "000000000000100801", "CORE ADJUVANT"),
        _material("GVP", "000000000000100801", "CORE ADJUVANT"),
    ]
    outcome = cleanse.cleanse_materials(
        rows, {("GVP", "000000000000100801"): "100801"}
    )
    assert outcome.issues_for("DQ-MAT-009") == []
    assert len(outcome.accepted) == 2


def test_a_material_number_unique_to_one_system_is_not_flagged():
    rows = [
        _material("GEP", "000000000000100801", "CORE ADJUVANT"),
        _material("GVP", "000000000000700801", "ANTIGEN BULK RSV"),
    ]
    assert cleanse.cleanse_materials(rows).issues_for("DQ-MAT-009") == []


def test_an_extract_must_declare_its_source_system(tmp_path):
    path = tmp_path / "ecc_mara_material_master.csv"
    path.write_text("MATNR\n000000000000100001\n", encoding="utf-8")
    with pytest.raises(extract.ExtractError, match="unknown source system"):
        extract.read_csv(path, "materials", "")


def test_reconciliation_counts_each_source_system(result):
    by_system = result.reconciliation.accepted_by_system
    assert set(result.reconciliation.source_systems) == {"GEP", "GVP"}
    for object_name, counts in by_system.items():
        assert set(counts) == {"GEP", "GVP"}, object_name
        assert sum(counts.values()) == len(
            result.cleansing[object_name].accepted
        )


def test_material_number_loses_its_leading_zeros():
    assert mapping.strip_leading_zeros("000000000000100234") == "100234"
    assert mapping.strip_leading_zeros("0") == "0"


def test_base_unit_is_converted_to_iso(result):
    units = {row["BaseUnit"] for row in result.products}
    assert units <= {"PCE", "KGM", "TNE", "LTR", "EA"}
    assert "ST" not in units


def test_customer_and_vendor_for_one_entity_share_a_business_partner(result):
    partners = result.business_partners
    shared = [
        partner
        for partner in partners.partners
        if partner.source_customers and partner.source_vendors
    ]
    assert len(shared) == 1
    assert shared[0].name == "GSK IRELAND MANUFACTURING"
    assert shared[0].roles == {"FLCU00", "FLCU01", "FLVN00", "FLVN01"}


def test_duplicate_vendor_across_company_codes_is_one_partner(result):
    lonza = next(
        partner
        for partner in result.business_partners.partners
        if partner.name == "LONZA AG"
    )
    assert lonza.source_vendors == [
        "GEP/0000510012", "GEP/0000510020", "GVP/0000510032",
    ]
    assert lonza.company_codes == {"GB01", "BE01", "BE02"}


def test_merge_warnings_describe_the_merges_the_load_performs(result):
    for object_name, prefix, key_field in (
        ("customers", "DQ-CUS", "KUNNR"),
        ("vendors", "DQ-VEN", "LIFNR"),
    ):
        cleansed = result.cleansing[object_name]
        warned = {
            key.strip()
            for issue in cleansed.issues_for(f"{prefix}-007")
            for key in issue.key.split(",")
        }
        accepted = cleansed.accepted
        merged = {
            source_key(row, key_field)
            for row in accepted
            if sum(
                1 for other in accepted
                if partner_identity(other) == partner_identity(row)
            ) > 1
        }
        assert warned == merged


def test_every_migrated_partner_has_a_cross_reference(result):
    customers = result.cleansing["customers"].accepted
    vendors = result.cleansing["vendors"].accepted
    xref = result.business_partners.xref
    for row in customers:
        assert source_key(row, "KUNNR") in xref
    for row in vendors:
        assert source_key(row, "LIFNR") in xref


def test_open_items_carry_the_business_partner_number(result):
    for row in result.open_items:
        if row["SourcePartner"]:
            assert row["BusinessPartner"]


def test_reconciliation_passes_for_the_reference_wave(result):
    assert result.reconciliation.passed
    assert result.reconciliation.failed_checks == []


def test_count_check_fails_when_a_record_never_reaches_the_load():
    fresh = pipeline.run(
        wave="wave0", source_dir=WAVE0, out_dir=Path("/tmp/unused"), write_files=False
    )
    materials = next(
        count for count in fresh.reconciliation.counts
        if count.object_name == "materials"
    )
    dropped = sorted(materials.target_keys)[0]
    materials.target_keys = materials.target_keys - {dropped}

    assert materials.missing == frozenset({dropped})
    assert not materials.balanced


def test_reconciliation_detects_a_value_break(result):
    tampered = [dict(row) for row in result.open_items]
    tampered[0]["AmountInCompanyCodeCurrency"] = "1.00"

    from datamig import reconcile

    broken = reconcile.build(
        wave="wave0",
        counts=result.reconciliation.counts,
        accepted_open_items=result.cleansing["open_items"].accepted,
        loaded_open_items=tampered,
        accepted_stock=result.cleansing["batch_stock"].accepted,
        loaded_stock=result.stock,
        accepted_partners=len(result.cleansing["customers"].accepted)
        + len(result.cleansing["vendors"].accepted),
        partner_identities=len(result.business_partners.partners),
        business_partners=len(result.business_partners.partners),
        merged_partners=result.business_partners.merged_count,
        xref=result.business_partners.xref,
        products=result.product_result,
    )
    assert not broken.passed
    assert any(check.id.startswith("REC-FI-VAL") for check in broken.failed_checks)


def test_pipeline_writes_the_expected_artefacts(tmp_path):
    outcome = pipeline.run(wave="wave0", source_dir=WAVE0, out_dir=tmp_path)
    written = {path.name for path in outcome.written}
    assert "s4_product.csv" in written
    assert "s4_product_xref.csv" in written
    assert "s4_business_partner_xref.csv" in written
    assert "reconciliation.md" in written
    assert (tmp_path / "rejected_materials.csv").exists()


def test_stock_base_unit_comes_from_the_material_master():
    material = {
        "SOURCE_SYSTEM": "GEP", "MATNR": "000000000000100001",
        "MEINS": "KG", "ZZ_TEMP_CLASS": "C2",
    }
    stock = {
        "SOURCE_SYSTEM": "GEP",
        "MATNR": "000000000000100001", "WERKS": "GB21", "LGORT": "0001",
        "CHARG": "B1", "CLABS": "1.000", "CINSM": "0.000", "CSPEM": "0.000",
        "MEINS": "st", "VFDAT": "", "HSDAT": "", "ZUSTD": "",
    }
    row = mapping.map_stock(stock, {source_key(material, "MATNR"): material})
    assert row["BaseUnit"] == "KGM"


def test_stock_in_a_different_unit_from_the_master_is_held_back(result):
    rejected = result.cleansing["batch_stock"].issues_for("DQ-STK-005")
    assert [issue.key for issue in rejected] == [
        "GEP/IE41/000000000000100246/B2500401"
    ]
    assert all(
        row["Product"] != "100246" or row["Plant"] != "IE41" for row in result.stock
    )
