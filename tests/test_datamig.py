import copy
import dataclasses
import shutil
from collections import Counter
from pathlib import Path

import pytest

from datamig import cleanse, extract, identity, mapping, pipeline
from datamig.cleanse import Action
from datamig.identity import partner_identity, partner_ref, source_key

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
        result.business_partners.xref[
            partner_ref(row["SOURCE_SYSTEM"], "C", row["KUNNR"])
        ]
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
    # The number is grouped and reported unpadded, as material
    # collisions are, so the two extracts' padding cannot hide a reuse.
    # The key keeps each record as its own extract spells it.
    assert "210045" in issues[0].message
    assert "GEP/0000210045" in issues[0].key
    assert "GVP/0000210045" in issues[0].key
    assert issues[0].action is Action.WARN
    # Each company named against the key it belongs to. Two lists side
    # by side get read positionally, and the steward chases the wrong
    # record in the wrong system.
    assert "GEP/0000210045 NHS SUPPLY CHAIN" in issues[0].message
    assert "GVP/0000210045 INSTITUT PASTEUR DE DAKAR" in issues[0].message


def test_a_number_padded_differently_by_each_system_still_collides():
    """The systems' extract programs need not pad alike.

    Grouping on the number as written would report two unrelated
    companies as distinct records that happen to share nothing, and the
    reuse would surface after cutover instead of before it.
    """
    def customer(system: str, number: str, name: str) -> dict[str, str]:
        return {
            "SOURCE_SYSTEM": system, "KUNNR": number, "NAME1": name,
            "LAND1": "GB", "PSTLZ": "TW8 9GS", "STCEG": "", "ORT01": "London",
            "STRAS": "1 Test Way", "BUKRS": "1000", "SPRAS": "E",
            "KTOKD": "0001", "LOEVM": "", "ZZ_GXP_RELEVANT": "X",
        }

    outcome = cleanse.cleanse_partners(
        [
            customer("GEP", "0000210045", "NHS SUPPLY CHAIN"),
            customer("GVP", "210045", "INSTITUT PASTEUR DE DAKAR"),
        ],
        object_name="customers",
        key_field="KUNNR",
    )

    collisions = outcome.issues_for("DQ-CUS-008")
    assert len(collisions) == 1
    assert "210045" in collisions[0].message


def test_one_number_twice_in_one_extract_holds_both_records():
    """KNA1 is keyed on KUNNR, so the extract is the broken thing.

    Both records carry the same source key, so the cross reference
    holds one entry and the losing company's open items resolve to the
    other company's business partner. A warning would let that load;
    the reconciliation would then fail on a count with no exception
    naming the cause.
    """
    def customer(number: str, name: str) -> dict[str, str]:
        return {
            "SOURCE_SYSTEM": "GEP", "KUNNR": number, "NAME1": name,
            "LAND1": "GB", "PSTLZ": "TW8 9GS", "STCEG": "", "ORT01": "London",
            "STRAS": "1 Test Way", "BUKRS": "1000", "SPRAS": "E",
            "KTOKD": "0001", "LOEVM": "", "ZZ_GXP_RELEVANT": "X",
        }

    outcome = cleanse.cleanse_partners(
        [
            customer("0000210045", "NHS SUPPLY CHAIN"),
            customer("0000210045", "BOOTS UK LTD"),
        ],
        object_name="customers",
        key_field="KUNNR",
    )

    held = outcome.issues_for("DQ-CUS-009")
    assert len(held) == 1
    assert held[0].action is Action.REJECT
    assert "GEP/0000210045 NHS SUPPLY CHAIN" in held[0].message
    assert "GEP/0000210045 BOOTS UK LTD" in held[0].message
    assert outcome.accepted == []
    assert len(outcome.rejected) == 2
    # Two systems is the tolerable case and stays a warning; this is
    # not that, and must not be reported as it.
    assert outcome.issues_for("DQ-CUS-008") == []


def test_a_record_already_rejected_is_not_held_a_second_time():
    """The two rows share a key, so key-based removal counts one twice."""
    def customer(number: str, name: str, country: str = "GB") -> dict[str, str]:
        return {
            "SOURCE_SYSTEM": "GEP", "KUNNR": number, "NAME1": name,
            "LAND1": country, "PSTLZ": "TW8 9GS", "STCEG": "", "ORT01": "London",
            "STRAS": "1 Test Way", "BUKRS": "1000", "SPRAS": "E",
            "KTOKD": "0001", "LOEVM": "", "ZZ_GXP_RELEVANT": "X",
        }

    outcome = cleanse.cleanse_partners(
        [
            customer("0000210045", "NHS SUPPLY CHAIN"),
            customer("0000210045", "BOOTS UK LTD", country="XX"),
        ],
        object_name="customers",
        key_field="KUNNR",
    )

    assert outcome.issues_for("DQ-CUS-009")
    assert len(outcome.rejected) == 2
    assert outcome.source_count == 2


def test_an_open_item_is_told_every_rule_holding_its_partner():
    """Clearing one hold leaves the record held by the other.

    Naming whichever rule fired last sends the steward back a second
    time for a problem that was on the screen the first: the country
    code is repaired, the partner still does not load, and the document
    still does not post.
    """
    def customer(number: str, country: str) -> dict[str, str]:
        return {
            "SOURCE_SYSTEM": "GEP", "KUNNR": number, "NAME1": "NHS SUPPLY CHAIN",
            "LAND1": country, "PSTLZ": "TW8 9GS", "STCEG": "", "ORT01": "London",
            "STRAS": "1 Test Way", "BUKRS": "1000", "SPRAS": "E",
            "KTOKD": "0001", "LOEVM": "", "ZZ_GXP_RELEVANT": "X",
        }

    partners = cleanse.cleanse_partners(
        [customer("0000210045", "XX"), customer("0000210045", "GB")],
        object_name="customers",
        key_field="KUNNR",
    )

    held = cleanse.held_partner_refs(partners, "C")
    assert held == {"GEP/C/0000210045": ("DQ-CUS-003", "DQ-CUS-009")}

    outcome = cleanse.cleanse_open_items(
        [{
            "SOURCE_SYSTEM": "GEP", "BUKRS": "GB01", "BELNR": "1900000001",
            "GJAHR": "2026", "BUZEI": "001", "BLART": "RV", "HKONT": "140000",
            "PARTNER": "0000210045", "PARTNER_TYPE": "C", "SHKZG": shkzg,
            "DMBTR": "100.00", "WAERS": "GBP", "BUDAT": "20260615",
            "ZFBDT": "20260715",
        } for shkzg in ("S", "H")],
        set(),
        held,
    )
    message = outcome.issues_for("DQ-FI-004")[0].message
    assert "DQ-CUS-003, DQ-CUS-009" in message
    assert "once those are resolved" in message


def test_the_same_record_listed_twice_is_held_like_any_other_duplicate():
    """Identical details make it harder to spot, not less broken.

    Two rows under one number look like one record: mapping writes the
    cross reference twice under one source key and the wave fails a
    count, with no exception naming what caused it - which is the
    failure this rule exists to replace.
    """
    def customer() -> dict[str, str]:
        return {
            "SOURCE_SYSTEM": "GEP", "KUNNR": "0000210045",
            "NAME1": "NHS SUPPLY CHAIN",
            "LAND1": "GB", "PSTLZ": "TW8 9GS", "STCEG": "GB123456789",
            "ORT01": "London", "STRAS": "1 Test Way", "BUKRS": "1000",
            "SPRAS": "E", "KTOKD": "0001", "LOEVM": "", "ZZ_GXP_RELEVANT": "X",
        }

    outcome = cleanse.cleanse_partners(
        [customer(), customer()], object_name="customers", key_field="KUNNR"
    )

    held = outcome.issues_for("DQ-CUS-009")
    assert len(held) == 1
    assert "for the same company (NHS SUPPLY CHAIN), twice" in held[0].message
    assert outcome.accepted == []
    assert len(outcome.rejected) == 2


def test_a_merge_is_not_announced_for_records_the_collision_holds():
    """One side held is no merge; both sides held is nothing at all.

    The warning is read as work: confirm the two records really are
    one company. Neither is loading, so there is nothing to confirm
    and no business partner for them to become.
    """
    def customer(number: str, name: str) -> dict[str, str]:
        return {
            "SOURCE_SYSTEM": "GEP", "KUNNR": number, "NAME1": name,
            "LAND1": "GB", "PSTLZ": "TW8 9GS", "STCEG": "", "ORT01": "London",
            "STRAS": "1 Test Way", "BUKRS": "1000", "SPRAS": "E",
            "KTOKD": "0001", "LOEVM": "", "ZZ_GXP_RELEVANT": "X",
        }

    outcome = cleanse.cleanse_partners(
        [
            # Same number, two companies: both held.
            customer("0000210045", "NHS SUPPLY CHAIN"),
            customer("0000210045", "BOOTS UK LTD"),
            # The held record's company again, under a sound number -
            # the merge it would have joined loses a side.
            customer("0000210058", "NHS SUPPLY CHAIN"),
        ],
        object_name="customers",
        key_field="KUNNR",
    )

    assert outcome.issues_for("DQ-CUS-009")
    assert outcome.issues_for("DQ-CUS-007") == []
    assert [row["KUNNR"] for row in outcome.accepted] == ["0000210058"]


def test_an_open_item_behind_a_held_partner_is_not_sent_looking_for_it():
    """The master was read and withheld, not missed.

    `DQ-FI-002` tells a steward to go and find it, which is the one
    thing that cannot be done: the record is in the extract and the
    programme decided it may not load.
    """
    def customer(number: str, name: str) -> dict[str, str]:
        return {
            "SOURCE_SYSTEM": "GEP", "KUNNR": number, "NAME1": name,
            "LAND1": "GB", "PSTLZ": "TW8 9GS", "STCEG": "", "ORT01": "London",
            "STRAS": "1 Test Way", "BUKRS": "1000", "SPRAS": "E",
            "KTOKD": "0001", "LOEVM": "", "ZZ_GXP_RELEVANT": "X",
        }

    def line(buzei: str, shkzg: str) -> dict[str, str]:
        return {
            "SOURCE_SYSTEM": "GEP", "BUKRS": "GB01", "BELNR": "1900000001",
            "GJAHR": "2026", "BUZEI": buzei, "BLART": "RV", "HKONT": "140000",
            "PARTNER": "0000210045", "PARTNER_TYPE": "C", "SHKZG": shkzg,
            "DMBTR": "100.00", "WAERS": "GBP", "BUDAT": "20260615",
            "ZFBDT": "20260715",
        }

    partners = cleanse.cleanse_partners(
        [
            customer("0000210045", "NHS SUPPLY CHAIN"),
            customer("0000210045", "BOOTS UK LTD"),
        ],
        object_name="customers",
        key_field="KUNNR",
    )
    held = cleanse.held_partner_refs(partners, "C")
    assert held == {"GEP/C/0000210045": ("DQ-CUS-009",)}

    outcome = cleanse.cleanse_open_items(
        [line("001", "S"), line("002", "H")], set(), held
    )
    cascade = outcome.issues_for("DQ-FI-004")
    assert len(cascade) == 2
    assert "DQ-CUS-009" in cascade[0].message
    assert outcome.issues_for("DQ-FI-002") == []
    assert outcome.accepted == []


def test_one_undated_document_raises_one_warning():
    """Two lines of one document with no baseline date are one gap."""
    def line(buzei: str, shkzg: str) -> dict[str, str]:
        return {
            "SOURCE_SYSTEM": "GEP", "BUKRS": "GB01", "BELNR": "1900000001",
            "GJAHR": "2026", "BUZEI": buzei, "BLART": "RV", "HKONT": "140000",
            "PARTNER": "0000210045", "PARTNER_TYPE": "C", "SHKZG": shkzg,
            "DMBTR": "100.00", "WAERS": "GBP", "BUDAT": "20260615", "ZFBDT": "",
        }

    outcome = cleanse.cleanse_open_items(
        [line("001", "S"), line("002", "H")], {"GEP/C/0000210045"}
    )
    assert len(outcome.issues_for("DQ-FI-003")) == 1
    assert len(outcome.accepted) == 2


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
    # Repointed, not appended: a second row for the same material is a
    # different defect, and the extract now refuses it outright.
    table = source / extract.HARMONISATION_FILE
    table.write_text(
        table.read_text(encoding="utf-8").replace(
            "GVP,000000000000700310,100244,merge,",
            "GVP,000000000000700310,999999,merge,",
        ),
        encoding="utf-8",
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


def test_a_decision_written_without_padding_is_still_applied():
    """ECC pads MATNR to 18; a steward writing the table does not.

    Whether a governed merge happens must not depend on that. It used
    to: the decision silently did not apply, the duplicate loaded under
    its own number with its stock, and REC-MRG-004 reported it as a
    material that is not in the extract - which is the one thing it is
    not.
    """
    decisions = [
        extract.HarmonisationDecision(
            source_system="GVP",
            material="700301",
            target_product="100251",
            decision="merge",
            note="Signed off",
        )
    ]
    harmonisation = mapping.ProductHarmonisation(decisions)
    retired = _material("GVP", "000000000000700301", "ADJUVANT WAVRE")

    assert harmonisation.is_merged(retired)
    assert harmonisation.target_product(retired) == "100251"

    materials = cleanse.cleanse_materials(
        [_material("GEP", "000000000000100251", "CORE ADJUVANT"), retired],
        harmonisation_targets=harmonisation.targets,
    )
    assert materials.issues_for("DQ-MAT-010") == []
    products = mapping.convert_to_products(materials.accepted, harmonisation)
    assert [row["Product"] for row in products.products] == ["100251"]
    assert products.merged_count == 1


def test_a_decision_whose_survivor_is_padded_is_still_applied():
    """The other side of the same defect, and the worse one.

    An unpadded material meant the merge quietly did not happen. A
    padded survivor means the merge is actively refused: nothing
    matches the target, so the retired record is held under
    DQ-MAT-010, its stock follows under DQ-STK-006 and REC-MRG-004
    fails the wave - all of it blaming a surviving master that is
    perfectly fine.
    """
    decisions = [
        extract.HarmonisationDecision(
            source_system="GVP",
            material="000000000000700301",
            target_product="000000000000100251",
            decision="merge",
            note="Signed off",
        )
    ]
    harmonisation = mapping.ProductHarmonisation(decisions)
    retired = _material("GVP", "000000000000700301", "ADJUVANT WAVRE")

    assert harmonisation.target_product(retired) == "100251"

    materials = cleanse.cleanse_materials(
        [_material("GEP", "000000000000100251", "CORE ADJUVANT"), retired],
        harmonisation_targets=harmonisation.targets,
    )
    assert materials.issues_for("DQ-MAT-010") == []
    products = mapping.convert_to_products(materials.accepted, harmonisation)
    assert [row["Product"] for row in products.products] == ["100251"]


def test_a_decided_duplicate_description_is_not_raised_as_an_exception():
    """DQ-MAT-008 asks a steward to confirm a harmonisation decision.

    Where the decision exists, there is nothing to confirm, and an
    exception nobody can close is how an evidence pack stops being
    read.
    """
    rows = [
        _material("GEP", "000000000000100236", "INFLUENZA VACCINE"),
        _material("GVP", "000000000000700302", "INFLUENZA VACCINE"),
    ]
    assert cleanse.cleanse_materials(rows).issues_for("DQ-MAT-008")

    decided = cleanse.cleanse_materials(
        rows, {("GVP", "000000000000700302"): "100236"}
    )
    assert decided.issues_for("DQ-MAT-008") == []


def test_a_decision_naming_a_system_that_does_not_exist_is_refused(tmp_path):
    """A one-character typo, misdiagnosed as a missing material.

    The key matches nothing, so the merge does not happen and
    REC-MRG-004 reports the material as absent from the extract -
    sending a steward to look for a record that is right there.
    """
    table = tmp_path / "material_harmonisation.csv"
    table.write_text(
        "SOURCE_SYSTEM,MATNR,TARGET_PRODUCT,DECISION,NOTE\n"
        "GVB,000000000000700302,100236,merge,Typo in the system column\n",
        encoding="utf-8",
    )
    with pytest.raises(extract.ExtractError) as error:
        extract.read_harmonisation(table)
    assert "GVB" in str(error.value)


def test_a_padded_and_an_unpadded_decision_load_the_same_wave(tmp_path):
    """End to end, because the padding has to agree at every stage."""
    source = tmp_path / "wave0"
    shutil.copytree(WAVE0, source)
    table = source / extract.HARMONISATION_FILE
    padded = pipeline.run(
        wave="wave0", source_dir=source, out_dir=tmp_path / "padded"
    )

    # Both sides at once: the material unpadded, the survivor padded.
    table.write_text(
        table.read_text(encoding="utf-8").replace(
            "GVP,000000000000700302,100236,", "GVP,700302,000000000000100236,"
        ),
        encoding="utf-8",
    )
    unpadded = pipeline.run(
        wave="wave0", source_dir=source, out_dir=tmp_path / "unpadded"
    )

    assert unpadded.reconciliation.passed
    assert [row["Product"] for row in unpadded.products] == [
        row["Product"] for row in padded.products
    ]
    assert unpadded.product_result.merged_count == (
        padded.product_result.merged_count
    )


def test_a_reject_file_keeps_a_column_only_one_system_has(tmp_path):
    """Reject files mix both systems' rows into one evidence file.

    Taking the header from the first row would either drop the column
    or fail the write, depending on which system's row came first.
    """
    from datamig import load

    path = load.write_rejects(
        tmp_path,
        "materials",
        [
            {"SOURCE_SYSTEM": "GEP", "MATNR": "100251"},
            {"SOURCE_SYSTEM": "GVP", "MATNR": "700301", "OCABR_REQUIRED": "X"},
        ],
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "SOURCE_SYSTEM,MATNR,OCABR_REQUIRED"
    assert lines[1] == "GEP,100251,"
    assert lines[2] == "GVP,700301,X"


def test_two_decisions_for_one_material_are_refused(tmp_path):
    """File order must not decide which survivor a steward signed off."""
    table = tmp_path / extract.HARMONISATION_FILE
    table.write_text(
        "SOURCE_SYSTEM,MATNR,TARGET_PRODUCT,DECISION,NOTE\n"
        "GVP,000000000000700301,100251,merge,First\n"
        "GVP,000000000000700301,100999,merge,Second\n",
        encoding="utf-8",
    )
    with pytest.raises(extract.ExtractError, match="more than one decision"):
        extract.read_harmonisation(table)


def test_two_decisions_differing_only_in_padding_are_refused(tmp_path):
    """Same guard, and the padding must not get a decision past it."""
    table = tmp_path / extract.HARMONISATION_FILE
    table.write_text(
        "SOURCE_SYSTEM,MATNR,TARGET_PRODUCT,DECISION,NOTE\n"
        "GVP,000000000000700301,100251,merge,First\n"
        "GVP,700301,100999,merge,Second\n",
        encoding="utf-8",
    )
    with pytest.raises(extract.ExtractError, match="more than one decision"):
        extract.read_harmonisation(table)


def test_a_decision_the_pipeline_cannot_act_on_stops_the_run(tmp_path):
    """Mapping acts on 'merge' and ignores the rest.

    Left unchecked, a typo is indistinguishable from a decision never
    taken: the duplicate simply loads twice under two numbers and no
    check sees a decision to compare against.
    """
    table = tmp_path / extract.HARMONISATION_FILE
    table.write_text(
        "SOURCE_SYSTEM,MATNR,TARGET_PRODUCT,DECISION,NOTE\n"
        "GVP,000000000000700301,100251,mrege,Typo\n",
        encoding="utf-8",
    )
    with pytest.raises(extract.ExtractError, match="does not act on"):
        extract.read_harmonisation(table)


def test_a_decision_is_read_case_insensitively(tmp_path):
    """'Merge' is the same decision as 'merge'."""
    table = tmp_path / extract.HARMONISATION_FILE
    table.write_text(
        "SOURCE_SYSTEM,MATNR,TARGET_PRODUCT,DECISION,NOTE\n"
        "GVP,000000000000700301,100251,Merge,Signed off\n",
        encoding="utf-8",
    )
    harmonisation = mapping.ProductHarmonisation(extract.read_harmonisation(table))
    assert harmonisation.merged_materials


def test_held_stock_names_the_rule_that_actually_held_the_material():
    """A steward reading the reject has to be able to find the rule."""
    targets = {("GVP", "000000000000700301"): "100251"}
    survivor = _material("GEP", "000000000000100251", "CORE ADJUVANT")
    survivor["MEINS"] = "ST"
    retired = _material("GVP", "000000000000700301", "ADJUVANT WAVRE")
    retired["MEINS"] = "KG"

    materials = cleanse.cleanse_materials(
        [survivor, retired], harmonisation_targets=targets
    )
    assert materials.issues_for("DQ-MAT-012")

    stock = cleanse.cleanse_batch_stock(
        [
            {
                "SOURCE_SYSTEM": "GVP",
                "WERKS": "BE33",
                "LGORT": "0001",
                "MATNR": "000000000000700301",
                "CHARG": "AH2600017",
                "CLABS": "10.000",
                "CINSM": "0.000",
                "CSPEM": "0.000",
                "MEINS": "KG",
                "VFDAT": "20290331",
                "HSDAT": "20260331",
                "ZUSTD": "F",
            }
        ],
        materials={},
        harmonisation_holds=materials.harmonisation_holds,
    )
    held = stock.issues_for("DQ-STK-006")
    assert len(held) == 1
    assert "DQ-MAT-012" in held[0].message
    assert "DQ-MAT-010" not in held[0].message


def test_a_merge_onto_a_collided_survivor_says_so():
    """The survivor is missing because two products claim its number.

    "Correct the surviving master" is the wrong instruction: there is
    nothing wrong with it, and the steward cannot make it load. The
    collision has to be settled first, and the exception has to say
    which of the two problems it is.
    """
    outcome = cleanse.cleanse_materials(
        [
            _material("GEP", "000000000000100249", "CORE ANTIGEN"),
            _material("GVP", "000000000000100249", "SOMETHING UNRELATED"),
            _material("GVP", "000000000000100801", "VACCINES ANTIGEN"),
        ],
        harmonisation_targets={("GVP", "000000000000100801"): "100249"},
    )
    orphaned = outcome.issues_for("DQ-MAT-010")
    assert len(orphaned) == 1
    assert "DQ-MAT-009" in orphaned[0].message
    assert "correct the surviving master" not in orphaned[0].message
    # And the stock cascade quotes the collision rather than sending a
    # steward to a master that is fine.
    hold = outcome.harmonisation_holds["GVP/100801"]
    assert hold.rule == "DQ-MAT-009"


def test_a_merge_into_a_retired_material_is_refused():
    """A -> B -> C asks the pipeline to infer that A means C.

    Caught in cleansing rather than on read, because whether 700302
    really disappears depends on the extracts: a record in the other
    system carrying that number and surviving would make the decision
    perfectly sound.
    """
    targets = {
        ("GVP", "000000000000700301"): "700302",
        ("GVP", "000000000000700302"): "100236",
    }
    outcome = cleanse.cleanse_materials(
        [
            _material("GVP", "000000000000700301", "ANTIGEN BULK RSV"),
            _material("GVP", "000000000000700302", "ANTIGEN BULK RSV II"),
            _material("GEP", "000000000000100236", "CORE ANTIGEN"),
        ],
        harmonisation_targets=targets,
    )
    chained = outcome.issues_for("DQ-MAT-011")
    assert [issue.key for issue in chained] == ["GVP/000000000000700301"]
    assert "another decision itself retires" in chained[0].message
    assert not outcome.issues_for("DQ-MAT-010")


def test_a_survivor_in_the_other_system_is_not_a_chain():
    """The same number retired in one system can survive in the other.

    Refusing this on the decision table alone was a false positive: the
    two systems share number ranges, so a retired GEP/100801 says
    nothing about whether product 100801 exists.
    """
    targets = {
        ("GEP", "000000000000100801"): "100236",
        ("GVP", "000000000000700301"): "100801",
    }
    outcome = cleanse.cleanse_materials(
        [
            _material("GEP", "000000000000100801", "CORE ADJUVANT"),
            _material("GVP", "000000000000700301", "ADJUVANT WAVRE"),
            _material("GVP", "000000000000100801", "ADJUVANT SURVIVOR"),
            _material("GEP", "000000000000100236", "CORE ANTIGEN"),
        ],
        harmonisation_targets=targets,
    )
    assert not outcome.issues_for("DQ-MAT-011")
    assert not outcome.issues_for("DQ-MAT-010")


def test_a_target_retired_by_the_other_system_is_still_a_chain():
    """The target product number is not qualified by source system.

    GVP/700301 merges into 100801, which the only record carrying that
    number - GEP's - is itself merging away. Product 100801 will not
    exist, and the reason is the other decision, wherever it was taken.
    """
    targets = {
        ("GEP", "000000000000100801"): "100236",
        ("GVP", "000000000000700301"): "100801",
    }
    outcome = cleanse.cleanse_materials(
        [
            _material("GEP", "000000000000100801", "CORE ADJUVANT"),
            _material("GVP", "000000000000700301", "ADJUVANT WAVRE"),
            _material("GEP", "000000000000100236", "CORE ANTIGEN"),
        ],
        harmonisation_targets=targets,
    )
    chained = outcome.issues_for("DQ-MAT-011")
    assert [issue.key for issue in chained] == ["GVP/000000000000700301"]
    assert not outcome.issues_for("DQ-MAT-010")


def test_a_master_record_held_twice_is_not_saved_by_a_decision():
    """A decision names the key once; the extract holds it twice.

    Excluding decided records from the collision rule is right - they
    are merged away and never claim the number - but with two records
    under one key mapping writes one cross reference over the other and
    a master disappears with nothing raised. MARA cannot hold MATNR
    twice, so the extract is what is wrong, and it must be said.
    """
    targets = {("GEP", "000000000000100801"): "100236"}
    outcome = cleanse.cleanse_materials(
        [
            _material("GEP", "000000000000100801", "CORE ADJUVANT"),
            _material("GEP", "000000000000100801", "SOMETHING ELSE ENTIRELY"),
            _material("GEP", "000000000000100236", "CORE ANTIGEN"),
        ],
        harmonisation_targets=targets,
    )
    collisions = outcome.issues_for("DQ-MAT-009")
    assert len(collisions) == 1
    assert "the decision table names it once" in collisions[0].message
    # Neither record loads, and neither is counted twice.
    assert [row["MATNR"] for row in outcome.accepted] == [
        "000000000000100236"
    ]
    assert len(outcome.rejected) == 2


def test_two_materials_without_a_description_are_not_duplicates():
    """An exception naming '' is one nobody can act on or close."""
    outcome = cleanse.cleanse_materials(
        [
            _material("GEP", "000000000000100801", ""),
            _material("GVP", "000000000000700301", ""),
        ]
    )
    assert not outcome.issues_for("DQ-MAT-008")


def test_a_merge_across_two_base_units_is_refused():
    """Stock keeps its own master's unit but follows the survivor."""
    targets = {("GVP", "000000000000700301"): "100251"}
    survivor = _material("GEP", "000000000000100251", "CORE ADJUVANT")
    survivor["MEINS"] = "ST"
    retired = _material("GVP", "000000000000700301", "ADJUVANT WAVRE")
    retired["MEINS"] = "KG"

    outcome = cleanse.cleanse_materials(
        [survivor, retired], harmonisation_targets=targets
    )
    mismatch = outcome.issues_for("DQ-MAT-012")
    assert [issue.key for issue in mismatch] == ["GVP/000000000000700301"]
    assert "held in KG" in mismatch[0].message
    assert "held in ST" in mismatch[0].message
    assert [row["MATNR"] for row in outcome.accepted] == ["000000000000100251"]


def test_differently_padded_numbers_are_the_same_collision():
    """The collision is on the number the product loads under.

    Only the padding differs between these two, and the target product
    number is the bare MATNR, so both would land on product 100801 and
    the mapping would keep whichever it saw first.
    """
    outcome = cleanse.cleanse_materials(
        [
            _material("GEP", "000000000000100801", "CORE ADJUVANT"),
            _material("GVP", "100801", "ANTIGEN BULK RSV"),
        ]
    )
    assert len(outcome.issues_for("DQ-MAT-009")) == 1
    assert outcome.accepted == []


def test_a_number_repeated_within_one_extract_is_a_collision():
    """One system is enough: both rows still land on one product."""
    outcome = cleanse.cleanse_materials(
        [
            _material("GVP", "000000000000700401", "ANTIGEN BULK A"),
            _material("GVP", "000000000000700401", "ANTIGEN BULK B"),
        ]
    )
    collisions = outcome.issues_for("DQ-MAT-009")
    assert len(collisions) == 1
    assert "more than once within GVP" in collisions[0].message
    assert outcome.accepted == []


def test_mapping_refuses_to_drop_a_second_record_for_one_product():
    """Cleansing should have held these; mapping must not paper over it.

    Skipping the second record loses a master with no reject naming it,
    which is the one outcome the pipeline is not allowed to produce.
    """
    harmonisation = mapping.ProductHarmonisation([])
    rows = [
        _material("GEP", "000000000000100801", "CORE ADJUVANT"),
        _material("GVP", "000000000000100801", "ANTIGEN BULK RSV"),
    ]
    with pytest.raises(mapping.MappingError, match="DQ-MAT-009"):
        mapping.convert_to_products(rows, harmonisation)


def test_a_collision_is_reported_even_if_one_side_is_rejected():
    """The collision is a fact about the extracts, not about cleansing.

    If seeing it depended on both sides surviving, an unrelated reject
    on one side would let the other load under the bare number - the
    outcome DQ-MAT-009 exists to prevent, deferred to whichever wave
    repairs the rejected record.
    """
    core = _material("GEP", "000000000000100801", "CORE ADJUVANT")
    vaccines = _material("GVP", "000000000000100801", "ANTIGEN BULK RSV")
    vaccines["MHDHB"] = ""  # batch managed without shelf life: DQ-MAT-006

    outcome = cleanse.cleanse_materials([core, vaccines])

    collisions = outcome.issues_for("DQ-MAT-009")
    assert len(collisions) == 1
    assert "GEP/000000000000100801" in collisions[0].key
    assert "GVP/000000000000100801" in collisions[0].key
    # The surviving side is held; the other is already out on its own
    # reject and must not be counted as rejected twice. Both are named
    # as holds, because stock hangs off either one.
    assert outcome.accepted == []
    assert len(outcome.rejected) == 2
    # Holds are keyed for the stock join, so unpadded; the exception a
    # steward reads keeps the number as their extract spells it.
    assert outcome.collision_holds == {"GEP/100801", "GVP/100801"}


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


def _keep_separate(system: str, material: str) -> extract.HarmonisationDecision:
    return extract.HarmonisationDecision(
        source_system=system,
        material=material,
        target_product="",
        decision="keep_separate",
        note="ruled distinct products by the data council",
    )


def test_a_ruling_that_two_products_stay_separate_is_not_an_open_question():
    """The council answered; the exception pack must not re-ask.

    Nothing merges, so mapping never sees the ruling - but cleansing
    warns on a duplicate description precisely to prompt the decision
    that has already been taken.
    """
    harmonisation = mapping.ProductHarmonisation(
        [_keep_separate("GVP", "000000000000700311")]
    )
    outcome = cleanse.cleanse_materials(
        [
            _material("GEP", "000000000000100260", "ADJUVANT AS01B BULK"),
            _material("GVP", "000000000000700311", "ADJUVANT AS01B BULK"),
        ],
        harmonisation.targets,
        harmonisation.ruled_separate,
    )

    assert not outcome.issues_for("DQ-MAT-008")
    assert len(outcome.accepted) == 2


def test_a_collision_the_council_ruled_separate_says_so():
    """Two products, one number: the ruling does not settle that.

    Only one record can hold the bare number in the target, so both are
    still held - but a message denying the decision exists sends a
    steward to take it again.
    """
    harmonisation = mapping.ProductHarmonisation(
        [_keep_separate("GVP", "000000000000100261")]
    )
    outcome = cleanse.cleanse_materials(
        [
            _material("GEP", "000000000000100261", "SALBUTAMOL SULPHATE"),
            _material("GVP", "000000000000100261", "ALUMINIUM HYDROXIDE"),
        ],
        harmonisation.targets,
        harmonisation.ruled_separate,
    )

    collision = outcome.issues_for("DQ-MAT-009")
    assert len(collision) == 1
    assert not outcome.accepted
    assert "rules them separate" in collision[0].message
    assert "no harmonisation decision" not in collision[0].message


def test_a_decision_table_missing_a_column_is_an_operator_error(tmp_path):
    """The CLI turns ExtractError into exit code 2 and a message.

    Anything else reaches whoever maintains the governed table as a
    traceback about a dictionary key.
    """
    table = tmp_path / "material_harmonisation.csv"
    table.write_text("SOURCE_SYSTEM,MATNR,DECISION\nGVP,700301,merge\n")

    with pytest.raises(extract.ExtractError) as error:
        extract.read_harmonisation(table)
    assert "TARGET_PRODUCT" in str(error.value)


def test_a_decision_naming_no_material_is_an_operator_error(tmp_path):
    table = tmp_path / "material_harmonisation.csv"
    table.write_text(
        "SOURCE_SYSTEM,MATNR,TARGET_PRODUCT,DECISION\nGVP,,100251,merge\n"
    )

    with pytest.raises(extract.ExtractError) as error:
        extract.read_harmonisation(table)
    assert "row 2" in str(error.value)
    assert "MATNR" in str(error.value)


def test_a_merge_naming_no_surviving_product_is_refused(tmp_path):
    """An empty target strips to product '0', which exists nowhere."""
    table = tmp_path / "material_harmonisation.csv"
    table.write_text(
        "SOURCE_SYSTEM,MATNR,TARGET_PRODUCT,DECISION\nGVP,700301,,merge\n"
    )

    with pytest.raises(extract.ExtractError) as error:
        extract.read_harmonisation(table)
    assert "surviving product" in str(error.value)


def test_a_record_held_by_two_rules_is_rejected_once():
    """The evidence pack has to count each physical record once.

    Two rows carrying one number inside a single extract share a source
    key, so keying the "is this still in the load" test on it moves a
    row another rule already rejected a second time. Extracted and
    rejected both come out one too high and a steward gets the same
    record twice.
    """
    clean = _material("GVP", "000000000000700401", "ANTIGEN BULK A")
    already_rejected = _material("GVP", "000000000000700401", "ANTIGEN BULK B")
    already_rejected["MHDHB"] = ""

    outcome = cleanse.cleanse_materials([clean, already_rejected])

    assert outcome.issues_for("DQ-MAT-006")
    assert outcome.issues_for("DQ-MAT-009")
    assert outcome.source_count == 2
    assert len(outcome.rejected) == 2
    assert [id(row) for row in outcome.rejected].count(id(already_rejected)) == 1


def test_stock_finds_its_master_however_the_extract_padded_it():
    """Two extracts, two programs, no guarantee they pad alike.

    A batch whose MATNR is spelled differently from its own material
    master would be held under DQ-STK-001 as stock on a material that
    was never migrated - while the material sits in the load file. The
    same defect as the harmonisation decision, one join further on.
    """
    padded = _material("GVP", "000000000000700305", "ANTIGEN BULK RSV")
    materials = cleanse.cleanse_materials([padded])
    assert materials.accepted == [padded]

    stock = cleanse.cleanse_batch_stock(
        [
            {
                "SOURCE_SYSTEM": "GVP", "WERKS": "BE32",
                "MATNR": "700305", "CHARG": "AB2600099",
                "LGORT": "0001", "CLABS": "10.000", "CINSM": "0.000",
                "CSPEM": "0.000", "MEINS": "ST",
                "VFDAT": "20270101", "HSDAT": "20260101", "ZUSTD": "",
            }
        ],
        materials={
            identity.material_lookup_key(row): row for row in materials.accepted
        },
    )

    assert not stock.issues_for("DQ-STK-001")
    assert len(stock.accepted) == 1


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


def test_an_extract_that_names_another_system_is_refused(tmp_path):
    """The folder is the source of truth, so it must not be the only one.

    An extract dropped into the wrong system's folder would otherwise
    be relabelled on read, and every stage keys on the answer: GVP's
    records would migrate as GEP's, under GEP's numbers.
    """
    path = tmp_path / "ecc_mara_material_master.csv"
    path.write_text(
        "SOURCE_SYSTEM,MATNR\nGVP,000000000000100001\n", encoding="utf-8"
    )
    with pytest.raises(extract.ExtractError, match="extracted from GVP"):
        extract.read_csv(path, "materials", "GEP")

    # And an extract naming the folder it is in reads as itself.
    assert extract.read_csv(path, "materials", "GVP").rows[0]["SOURCE_SYSTEM"] == "GVP"


def test_a_warning_on_a_held_record_is_not_counted_as_outstanding(result):
    """The exception pack keeps it; the wave table does not count it.

    Quality inspection stock needs a usage decision before go-live -
    but not on a batch the wave is holding back, where the decision to
    take is the one that releases the material. Counted, the table
    reads as work on data that will not exist at cutover.
    """
    stock = result.cleansing["batch_stock"]
    held = stock.held_keys()
    assert held

    warnings = stock.issues_for("DQ-STK-004") + stock.issues_for("DQ-STK-003")
    assert any(warning.key in held for warning in warnings), (
        "fixture no longer has a warning on a rejected batch"
    )
    counted = {issue.key for issue in stock.warnings_on_loaded()}
    assert not counted & held
    # And still shipped, so the steward sees it when the reject clears.
    assert {warning.key for warning in warnings} & held

    batch_stock = next(
        count for count in result.reconciliation.counts
        if count.object_name == "batch_stock"
    )
    assert batch_stock.warnings == len(stock.warnings_on_loaded())


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
        assert partner_ref(row["SOURCE_SYSTEM"], "C", row["KUNNR"]) in xref
    for row in vendors:
        assert partner_ref(row["SOURCE_SYSTEM"], "V", row["LIFNR"]) in xref


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
        accepted_materials=result.cleansing["materials"].accepted,
    )
    assert not broken.passed
    # Named exactly: accepting any red check would let an unrelated
    # break satisfy the test. Both of these follow from the one altered
    # amount - the company code total moves, and the document it sits
    # in no longer balances.
    assert {check.id for check in broken.failed_checks} == {
        "REC-FI-VAL-GB01-GBP",
        "REC-FI-BAL-GB01",
    }


def test_stock_on_the_wrong_merged_product_is_caught(tmp_path, monkeypatch):
    """A mapping defect must not cancel itself out on both sides.

    The ECC side of the stock count is derived from the governed
    decision table, so a batch put onto some other product shows up as
    a missing key rather than moving both sides together.
    """
    real_map_stock = mapping.map_stock

    def wrong_product(row, materials, product_xref=None):
        mapped = real_map_stock(row, materials, product_xref)
        if mapped["Batch"] == "B2500112":
            mapped["Product"] = "100236"
        return mapped

    monkeypatch.setattr(mapping, "map_stock", wrong_product)
    outcome = pipeline.run(wave="wave0", source_dir=WAVE0, out_dir=tmp_path)

    assert not outcome.reconciliation.passed
    assert "REC-CNT-batch_stock" in {
        check.id for check in outcome.reconciliation.failed_checks
    }


def test_two_systems_supplying_one_batch_is_caught(result):
    """The count key carries SourceSystem; the S/4HANA key does not.

    Two rows the target cannot tell apart would balance every count
    check, because both sides carry the qualifier that keeps them
    distinct.
    """
    from datamig import reconcile

    collided = [dict(row) for row in result.stock]
    collided[1].update(
        {
            "SourceSystem": "GVP",
            "Product": collided[0]["Product"],
            "Plant": collided[0]["Plant"],
            "StorageLocation": collided[0]["StorageLocation"],
            "Batch": collided[0]["Batch"],
        }
    )

    broken = reconcile.build(
        wave="wave0",
        counts=result.reconciliation.counts,
        accepted_open_items=result.cleansing["open_items"].accepted,
        loaded_open_items=result.open_items,
        accepted_stock=result.cleansing["batch_stock"].accepted,
        loaded_stock=collided,
        accepted_partners=len(result.cleansing["customers"].accepted)
        + len(result.cleansing["vendors"].accepted),
        partner_identities=len(result.business_partners.partners),
        business_partners=len(result.business_partners.partners),
        merged_partners=result.business_partners.merged_count,
        xref=result.business_partners.xref,
    )
    assert "REC-STK-KEY" in {check.id for check in broken.failed_checks}


def test_a_number_reused_across_record_types_stays_two_partners():
    """A customer and a vendor can hold one number in one system.

    The ranges are disjoint by convention, not by constraint. Keyed on
    the number alone, the second write replaced the first and that
    company's open items posted against the other company's business
    partner - wrong money against a real partner, which no count can
    see because both records are accepted and both partners created.
    """
    from datamig import mapping

    def _partner(number_field: str, number: str, name: str) -> dict[str, str]:
        return {
            "SOURCE_SYSTEM": "GEP", number_field: number, "NAME1": name,
            "LAND1": "GB", "PSTLZ": "SW1", "ORT01": "LONDON",
            "STRAS": "1 HIGH ST", "STCEG": "", "BUKRS": "GB01",
        }

    partners = mapping.convert_to_business_partners(
        [_partner("KUNNR", "0000210045", "NHS SUPPLY CHAIN")],
        [_partner("LIFNR", "0000210045", "LONZA AG")],
    )
    assert len(partners.xref) == 2
    customer_bp = partners.xref["GEP/C/0000210045"]
    vendor_bp = partners.xref["GEP/V/0000210045"]
    assert customer_bp != vendor_bp

    def _item(partner_type: str) -> dict[str, str]:
        return {
            "SOURCE_SYSTEM": "GEP", "BUKRS": "GB01", "BELNR": "1900000001",
            "GJAHR": "2026", "BUZEI": "001", "BLART": "RV", "HKONT": "140000",
            "PARTNER": "0000210045", "PARTNER_TYPE": partner_type, "SHKZG": "S",
            "DMBTR": "100.00", "WAERS": "GBP", "BUDAT": "20260615",
            "ZFBDT": "20260715",
        }

    assert mapping.map_open_item(_item("C"), partners.xref)["BusinessPartner"] == (
        customer_bp
    )
    assert mapping.map_open_item(_item("V"), partners.xref)["BusinessPartner"] == (
        vendor_bp
    )


def test_the_printed_record_arithmetic_is_checked(result):
    """The report asserts extracted - rejected - merged = loaded."""
    from datamig import reconcile

    counts = [dataclasses.replace(count) for count in result.reconciliation.counts]
    materials = next(count for count in counts if count.object_name == "materials")
    materials.merged += 1

    broken = reconcile.build(
        wave="wave0",
        counts=counts,
        accepted_open_items=result.cleansing["open_items"].accepted,
        loaded_open_items=result.open_items,
        accepted_stock=result.cleansing["batch_stock"].accepted,
        loaded_stock=result.stock,
        accepted_partners=len(result.cleansing["customers"].accepted)
        + len(result.cleansing["vendors"].accepted),
        partner_identities=len(result.business_partners.partners),
        business_partners=len(result.business_partners.partners),
        merged_partners=result.business_partners.merged_count,
        xref=result.business_partners.xref,
    )
    assert "REC-ARI-materials" in {check.id for check in broken.failed_checks}
    assert "REC-CNT-materials" not in {check.id for check in broken.failed_checks}


def test_the_pack_says_which_checks_could_actually_have_failed(result):
    """`AGENTS.md`: a check that cannot fail is not a check.

    Three of the record-arithmetic checks derive both sides from the
    accepted records, so they hold unless the tooling is broken. They
    are worth running for exactly that reason, but presenting them
    beside checks that compare the extract with the load file
    overstates what the pack proves, so each check says which it is.
    """
    from datamig import reconcile

    evidence = {
        check.id: check.evidence for check in result.reconciliation.checks
    }
    # Every mapping emits one row per accepted record or raises -
    # partners included, where the accepted row is appended to the
    # business partner unconditionally - so no record arithmetic can be
    # separated by bad data, only by a tooling defect.
    assert all(
        check.evidence == reconcile.INVARIANT
        for check in result.reconciliation.checks
        if check.id.startswith("REC-ARI-")
    )
    # Mapping copies the amount, the company code and the plant across
    # untouched, so a value total is the same addition done twice. It
    # reads like the strongest check in the pack and is the weakest.
    totals = [
        check
        for check in result.reconciliation.checks
        if check.description.startswith(
            ("open item value total", "unrestricted stock quantity")
        )
    ]
    assert totals
    assert all(check.evidence == reconcile.INVARIANT for check in totals)
    assert evidence["REC-MRG-002"] == reconcile.INVARIANT
    # Both count the same accepted records through the same identity
    # function, one directly and one through the index mapping
    # deduplicates on.
    assert evidence["REC-MRG-001"] == reconcile.INVARIANT
    assert evidence["REC-BP-001"] == reconcile.INVARIANT
    # One cross reference entry per accepted record, now that the entry
    # is keyed on the account type as well as the number. Fixing the
    # key is what made this an invariant: the collision it used to be
    # able to catch cannot happen any more.
    assert evidence["REC-BP-003"] == reconcile.INVARIANT
    # Goes and looks at the load file for the surviving product.
    assert evidence["REC-MRG-003"] == reconcile.COMPARED
    # Both sides off the load file, held against a rule the target must
    # satisfy. Bad input fails them, so they are not invariants - but
    # they never look at the extract, so they are not comparisons.
    assert evidence["REC-STK-KEY"] == reconcile.ASSERTED
    assert evidence["REC-BP-002"] == reconcile.ASSERTED
    assert all(
        check.evidence == reconcile.ASSERTED
        for check in result.reconciliation.checks
        if check.id.startswith("REC-FI-BAL-")
    )
    assert all(
        check.evidence
        in (reconcile.COMPARED, reconcile.ASSERTED, reconcile.INVARIANT)
        for check in result.reconciliation.checks
    )


def test_a_customer_lost_between_cleansing_and_load_breaks_the_arithmetic(
    tmp_path,
):
    """`loaded` is read off the rows being written, not off the accepted list.

    That is what lets `REC-CNT-customers` see a record written twice.
    It does not make the arithmetic evidence about the data - mapping
    appends one cross-reference entry per accepted row unconditionally,
    so only a change to mapping can separate the two sides, which is
    why the check is labelled an invariant and this test edits the
    count by hand to reach the failure.
    """
    source = tmp_path / "wave0"
    shutil.copytree(WAVE0, source)
    outcome = pipeline.run(
        wave="wave0", source_dir=source, out_dir=tmp_path / "out", write_files=False
    )
    customers = next(
        count
        for count in outcome.reconciliation.counts
        if count.object_name == "customers"
    )
    assert customers.loaded == len(
        [row for row in outcome.business_partners.xref_rows()
         if row["SourceType"] == "KNA1"]
    )

    dropped = dataclasses.replace(customers, loaded=customers.loaded - 1)
    assert (
        dropped.extracted - dropped.rejected - dropped.merged != dropped.loaded
    )


def test_a_customer_loaded_under_two_partners_breaks_the_partner_checks(result):
    """`loaded` counts rows, not distinct source records.

    Counting the set instead hides the failure that matters most here:
    one customer written under two business partners leaves the set the
    same size, so the arithmetic still balances and the target quietly
    holds the customer twice. The `compared` label has to be worth
    something.
    """
    customers = next(
        count
        for count in result.reconciliation.counts
        if count.object_name == "customers"
    )
    assert customers.loaded == len(
        [row for row in result.business_partners.xref_rows()
         if row["SourceType"] == "KNA1"]
    )

    twice = dataclasses.replace(customers, loaded=customers.loaded + 1)
    assert twice.duplicated == 1
    assert not twice.balanced
    assert twice.extracted - twice.rejected - twice.merged != twice.loaded


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
    row = mapping.map_stock(
        stock, {identity.material_lookup_key(material): material}
    )
    assert row["BaseUnit"] == "KGM"


def test_a_lower_case_stock_unit_is_not_a_unit_decision():
    """DQ-MAT-001 folds the master's unit; the stock extract is raw.

    Comparing the two as written turns 'kg' against 'KG' into a reject
    and asks a steward for a decision between a unit and itself.
    """
    materials = cleanse.cleanse_materials(
        [_material("GVP", "000000000000700304", unit="kg")]
    )
    stock = cleanse.cleanse_batch_stock(
        [
            {
                "SOURCE_SYSTEM": "GVP", "WERKS": "BE32",
                "MATNR": "000000000000700304", "CHARG": "AB2600099",
                "LGORT": "0001", "CLABS": "10.000", "CINSM": "0.000",
                "CSPEM": "0.000", "MEINS": "kg",
                "VFDAT": "20270101", "HSDAT": "20260101", "ZUSTD": "",
            }
        ],
        materials={
            identity.material_lookup_key(row): row for row in materials.accepted
        },
    )

    assert not stock.issues_for("DQ-STK-005")
    assert len(stock.accepted) == 1


def test_a_source_number_containing_a_slash_survives_the_cross_reference():
    """External number ranges are not numeric.

    `SYSTEM/NUMBER` is this pipeline's own convention, so only the
    first slash is a separator. Splitting on all of them truncates the
    historical number written to the load file, which is the one thing
    the cross reference exists to preserve.
    """
    material = _material("GEP", "ABC/123", "EXTERNALLY NUMBERED")
    harmonisation = mapping.ProductHarmonisation([])
    products = mapping.convert_to_products([material], harmonisation)

    row = next(iter(products.xref_rows()))
    assert row["SourceSystem"] == "GEP"
    assert row["SourceMaterial"] == "ABC/123"
    assert products.lookup["GEP/ABC/123"] == row["Product"]


def test_stock_in_a_different_unit_from_the_master_is_held_back(result):
    rejected = result.cleansing["batch_stock"].issues_for("DQ-STK-005")
    assert [issue.key for issue in rejected] == [
        "GEP/IE41/000000000000100246/B2500401"
    ]
    assert all(
        row["Product"] != "100246" or row["Plant"] != "IE41" for row in result.stock
    )
