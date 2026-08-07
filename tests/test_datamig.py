from pathlib import Path

import pytest

from datamig import cleanse, extract, mapping, pipeline
from datamig.cleanse import Action
from datamig.identity import partner_identity

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


def test_extract_raises_for_a_missing_wave(tmp_path):
    with pytest.raises(extract.ExtractError):
        extract.extract_wave(tmp_path / "nope")


def test_lower_case_base_unit_is_repaired():
    rows = [
        {
            "MATNR": "1", "MTART": "FERT", "MATKL": "X", "MEINS": "st",
            "BRGEW": "1.0", "GEWEI": "KG", "SPART": "01", "XCHPF": "X",
            "MHDHB": "365", "ZZ_TEMP_CLASS": "15-25C", "MAKTX": "TEST",
            "WERKS": "GB21", "DISPO": "101",
        }
    ]
    outcome = cleanse.cleanse_materials(rows)
    assert outcome.accepted[0]["MEINS"] == "ST"
    assert outcome.issues_for("DQ-MAT-001")[0].action is Action.FIX


def test_batch_managed_material_without_shelf_life_is_rejected(result):
    materials = result.cleansing["materials"]
    rejected = {row["MATNR"] for row in materials.rejected}
    assert "000000000000100237" in rejected
    assert materials.issues_for("DQ-MAT-006")


def test_invalid_country_code_is_rejected(result):
    customers = result.cleansing["customers"]
    assert {row["KUNNR"] for row in customers.rejected} == {"0000210060"}


def test_unbalanced_document_is_rejected(result):
    issues = result.cleansing["open_items"].issues_for("DQ-FI-001")
    assert [issue.key for issue in issues] == ["IE01/4900000772/2026"]


def test_open_item_for_an_unknown_partner_is_rejected(result):
    issues = result.cleansing["open_items"].issues_for("DQ-FI-002")
    assert issues and "0000210099" in issues[0].message


def test_stock_for_a_rejected_material_does_not_load(result):
    loaded_products = {row["Product"] for row in result.products}
    for row in result.stock:
        assert row["Product"] in loaded_products


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
    assert lonza.source_vendors == ["0000510012", "0000510020"]
    assert lonza.company_codes == {"GB01", "BE01"}


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
            row[key_field]
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
        assert row["KUNNR"] in xref
    for row in vendors:
        assert row["LIFNR"] in xref


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
    )
    assert not broken.passed
    assert any(check.id.startswith("REC-FI-VAL") for check in broken.failed_checks)


def test_pipeline_writes_the_expected_artefacts(tmp_path):
    outcome = pipeline.run(wave="wave0", source_dir=WAVE0, out_dir=tmp_path)
    written = {path.name for path in outcome.written}
    assert "s4_product.csv" in written
    assert "s4_business_partner_xref.csv" in written
    assert "reconciliation.md" in written
    assert (tmp_path / "rejected_materials.csv").exists()
