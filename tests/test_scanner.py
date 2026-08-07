import json
from pathlib import Path

import pytest

from s4scan import report
from s4scan.inventory import Inventory, InventoryError, is_a_duplication, wave_rank
from s4scan.rules import RuleFilter, Severity
from s4scan.scanner import has_test_class, object_name_for, scan, scan_file

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY = REPO_ROOT / "abap" / "ecc"
REMEDIATED = REPO_ROOT / "abap" / "remediated"
INVENTORY = REPO_ROOT / "estate" / "inventory.csv"


def load_inventory() -> Inventory:
    return Inventory.load(INVENTORY)


def test_a_convergence_group_split_across_waves_is_refused(tmp_path):
    """`--wave` narrows the estate, so a split group would vanish.

    Both wave views would drop the group from the convergence backlog
    while SI-CONV-001 still fired on the member each could see - the
    report calling an object duplicated and denying the duplication in
    the same breath.
    """
    rows = INVENTORY.read_text(encoding="utf-8").splitlines()
    members = [index for index, row in enumerate(rows) if ",CG-MM-STOCK," in row]
    assert len(members) > 1
    rows[members[0]] = rows[members[0]].replace(",wave0,", ",wave1,")
    split = tmp_path / "inventory.csv"
    split.write_text("\n".join(rows) + "\n", encoding="utf-8")

    with pytest.raises(InventoryError, match="CG-MM-STOCK spans"):
        Inventory.load(split)


def test_a_counterpart_being_switched_off_is_not_a_duplication(tmp_path):
    """Nothing to converge with, so SI-CONV-001 must not fire.

    The group would price no work - `outstanding` drops decommissioned
    members - and would not appear as already built either, leaving the
    finding on the survivor contradicted by both tables.
    """
    rows = INVENTORY.read_text(encoding="utf-8").splitlines()
    members = [index for index, row in enumerate(rows) if ",CG-MM-STOCK," in row]
    assert len(members) > 1
    rows[members[-1]] = rows[members[-1]].replace(
        ",CG-MM-STOCK,converge,", ",CG-MM-STOCK,decommission,"
    )
    mixed = tmp_path / "inventory.csv"
    mixed.write_text("\n".join(rows) + "\n", encoding="utf-8")

    assert not Inventory.load(mixed).is_cross_system_group("CG-MM-STOCK")
    assert Inventory.load(INVENTORY).is_cross_system_group("CG-MM-STOCK")


def test_the_two_duplication_predicates_agree():
    """One rule, two callers.

    The inventory answer gates SI-CONV-001 and the scanner answer gates
    whether the group is reported at all, so they cannot be allowed to
    drift: a group that is a duplication to one and not to the other
    leaves a finding on an object whose group appears in no table.
    """
    inventory = load_inventory()
    result = scan([LEGACY], inventory=inventory, test_roots=[REPO_ROOT / "abap"])
    groups = {group.group_id: group for group in result.convergence_groups()}
    assert groups

    for group_id in {
        entry.convergence_group
        for entry in inventory.entries
        if entry.convergence_group
    }:
        assert inventory.is_cross_system_group(group_id) == (group_id in groups)


def test_a_pair_that_both_sides_switch_off_is_still_a_duplication():
    """It is why the interface disappears - that saving is the point."""
    assert is_a_duplication([("GEP", True), ("GVP", True)])
    assert not is_a_duplication([("GEP", False), ("GVP", True)])
    assert not is_a_duplication([("GEP", False), ("GEP", False)])
    assert is_a_duplication([("GEP", False), ("GVP", False)])


def test_object_name_is_derived_from_the_file_name():
    assert object_name_for(Path("a/zgsk_mm_stock_overview.prog.abap")) == (
        "ZGSK_MM_STOCK_OVERVIEW"
    )
    assert object_name_for(Path("a/zgsk_if_label_print.fugr.abap")) == (
        "ZGSK_IF_LABEL_PRINT"
    )


def test_test_evidence_is_not_satisfied_by_a_similarly_named_class(tmp_path):
    (tmp_path / "zgsk_mm_stock.testclasses.abap").write_text("CLASS ltcl DEFINITION.")
    overview = tmp_path / "zgsk_mm_stock_overview.prog.abap"
    overview.write_text("REPORT zgsk_mm_stock_overview.")

    assert not has_test_class(overview, [tmp_path])

    (tmp_path / "zgsk_mm_stock_overview.testclasses.abap").write_text("CLASS ltcl.")
    assert has_test_class(overview, [tmp_path])


def test_every_inventory_entry_points_at_a_real_file():
    for entry in load_inventory():
        assert (REPO_ROOT / entry.path).exists(), entry.path


def test_every_remediated_path_points_at_a_real_file():
    for entry in load_inventory():
        if entry.is_remediated:
            assert (REPO_ROOT / entry.remediated_path).exists(), entry.remediated_path


def test_remediated_objects_leave_the_backlog():
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    remediated = {obj.object_name for obj in result.remediated()}
    assert "ZGSK_MM_STOCK_OVERVIEW" in remediated
    assert remediated & {obj.object_name for obj in result.objects_with_findings()}
    assert not remediated & {obj.object_name for obj in report.build_backlog(result)}


def test_remediation_moves_findings_from_outstanding_to_cleared():
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    payload = json.loads(report.to_json(result))
    summary = payload["summary"]

    cleared = [obj for obj in result.remediated() if obj.findings]
    # An object with findings is either still to do, already remediated,
    # or dropped at the merge - the three are exhaustive and disjoint.
    decommissioned = [
        obj for obj in result.decommissioned()
        if obj.findings and not obj.is_remediated
    ]
    assert summary["outstanding_findings"] < summary["findings"]
    assert summary["objects_outstanding"] + len(cleared) + len(decommissioned) == (
        summary["objects_with_findings"]
    )
    assert payload["cleared_effort"]["engineer_days"] > 0
    assert {item["object_name"] for item in payload["remediated"]} == {
        obj.object_name for obj in result.remediated()
    }


def test_every_object_belongs_to_a_source_system():
    inventory = load_inventory()
    assert set(inventory.source_systems()) == {"GEP", "GVP"}
    for entry in inventory:
        expected = f"abap/ecc/{entry.source_system.lower()}/"
        assert entry.path.startswith(expected), entry.object_name


def test_scan_carries_the_source_system_through():
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    by_system = result.by_source_system()
    assert set(by_system) == {"GEP", "GVP"}
    assert all(by_system.values())
    assert sum(len(objects) for objects in by_system.values()) == len(result.objects)


def test_convergence_groups_pair_the_two_systems():
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    groups = result.convergence_groups()
    assert groups
    for group in groups:
        assert group.source_systems == ["GEP", "GVP"]
        assert len(group.objects) > 1


def test_duplicated_function_is_raised_against_both_implementations():
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    flagged = {
        obj.object_name: obj
        for obj in result.objects
        if any(finding.rule.id == "SI-CONV-001" for finding in obj.findings)
    }
    assert flagged

    # Every member outstanding, not merely the group as a whole: the
    # rule skips a member that is already rebuilt, so a group with one
    # side built would fail this for the right reason and read as a
    # bug. Picking on `is_remediated` alone passes only while the
    # fully-outstanding group happens to sort first.
    group = next(
        group for group in result.convergence_groups()
        if len(group.outstanding) == len(group.objects)
    )
    for obj in group.objects:
        assert obj.object_name in flagged


def test_a_view_filter_leaves_the_wave_it_was_taken_from_whole():
    """The two filters have to land on different lists.

    A wave narrows what is scanned; a system narrows what is shown of
    it. Both were mutators once and only composed in one order, so
    applying the view first set the estate to one system's objects and
    dissolved every group. They are predicates now and `filter` orders
    them itself - what is asserted here is the result: the view is one
    system, the estate behind it is the whole wave.
    """
    result = scan(
        [LEGACY],
        inventory=load_inventory(),
        test_roots=[REPO_ROOT / "abap"],
    )
    result.filter(
        estate=lambda obj: obj.wave == "wave0",
        view=lambda obj: obj.source_system == "GVP",
    )

    assert {obj.source_system for obj in result.objects} == {"GVP"}
    assert {obj.source_system for obj in result.estate} == {"GEP", "GVP"}
    assert {obj.wave for obj in result.estate} == {"wave0"}
    # The groups survive the view, which is the whole point of keeping
    # the estate: a group is cross-system by definition.
    assert result.convergence_groups()


def test_a_pair_that_disappears_at_the_merge_is_not_a_fit_gap():
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    dropped = [
        group for group in result.convergence_groups() if group.is_decommissioned
    ]
    assert dropped
    for group in dropped:
        for obj in group.objects:
            rule_ids = {finding.rule.id for finding in obj.findings}
            assert "SI-CONV-001" not in rule_ids


def test_objects_dropped_at_the_merge_are_not_in_the_backlog():
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    decommissioned = result.decommissioned()
    assert decommissioned
    assert all(obj.findings for obj in decommissioned)

    backlog = {obj.object_name for obj in report.build_backlog(result)}
    outstanding = {obj.object_name for obj in result.outstanding()}
    for obj in decommissioned:
        assert obj.object_name not in backlog
        assert obj.object_name not in outstanding


def test_convergence_estimate_is_cheaper_than_remediating_both():
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    estimates = report.convergence_estimates(result)
    assert estimates
    assert {estimate.group_id for estimate in estimates} == {
        group.group_id
        for group in result.convergence_groups()
        if not group.is_decommissioned and len(group.outstanding) > 1
    }
    for estimate in estimates:
        assert estimate.source_systems == ("GEP", "GVP")
        assert estimate.converged_days < estimate.independent_days
        assert estimate.avoided_days > 0


def test_a_group_whose_counterpart_is_built_claims_no_saving():
    """The saving was banked when the first object was rebuilt."""
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    settled = report.groups_with_built_counterpart(result)
    assert settled

    priced = {estimate.group_id for estimate in report.convergence_estimates(result)}
    for group in settled:
        assert group.group_id not in priced
        assert any(obj.is_remediated for obj in group.objects)


def test_convergence_estimate_ignores_an_already_remediated_member():
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    for estimate in report.convergence_estimates(result):
        group = next(
            group for group in result.convergence_groups()
            if group.group_id == estimate.group_id
        )
        outstanding_days = round(
            sum(report._days(obj.weighted_effort_points) for obj in group.outstanding),
            1,
        )
        assert estimate.independent_days == outstanding_days


def test_the_object_left_over_still_must_not_be_remediated_alone():
    """Its counterpart exists in S/4HANA, so it folds into that."""
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    for group in report.groups_with_built_counterpart(result):
        for obj in group.outstanding:
            assert "SI-CONV-001" in {finding.rule.id for finding in obj.findings}


def test_every_legacy_source_is_in_the_inventory():
    inventory = load_inventory()
    for path in LEGACY.rglob("*.abap"):
        relative = path.relative_to(REPO_ROOT).as_posix()
        assert inventory.for_path(relative) is not None, relative


def test_legacy_estate_has_blocking_findings():
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    assert result.has_severity(Severity.BLOCKER)
    assert len(result.objects_with_findings()) == len(result.objects)


def test_remediated_reference_is_clean():
    result = scan(
        [REMEDIATED], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"]
    )
    assert result.findings == []


def test_stock_overview_findings_name_the_expected_rules():
    result = scan_file(
        LEGACY / "gep" / "mm" / "zgsk_mm_stock_overview.prog.abap",
        inventory=load_inventory(),
        test_roots=[REPO_ROOT / "abap"],
    )
    rule_ids = {finding.rule_id for finding in result.findings}
    assert {"SI-MM-001", "SI-TECH-003", "SI-TECH-004"} <= rule_ids
    assert result.entry is not None
    assert result.entry.wave == "wave0"


def test_gxp_rule_only_fires_for_gxp_objects_without_tests():
    inventory = load_inventory()
    result = scan([LEGACY], inventory=inventory, test_roots=[REPO_ROOT / "abap"])
    flagged = {
        obj.object_name
        for obj in result.objects
        if any(finding.rule_id == "SI-GXP-001" for finding in obj.findings)
    }
    for name in flagged:
        entry = inventory.for_name(name)
        assert entry is not None and entry.is_gxp
    assert "ZGSK_FI_AP_AGEING" not in flagged


def test_validation_multiplier_inflates_gxp_effort():
    inventory = load_inventory()
    result = scan([LEGACY], inventory=inventory, test_roots=[REPO_ROOT / "abap"])
    gxp_objects = [obj for obj in result.objects if obj.gxp_class == "gxp_critical"]
    assert gxp_objects
    for obj in gxp_objects:
        assert obj.weighted_effort_points == round(obj.raw_effort_points * 2.0, 1)


def test_rule_filter_restricts_the_scan():
    result = scan(
        [LEGACY],
        inventory=load_inventory(),
        rule_filter=RuleFilter(include={"SI-MM-001"}),
        test_roots=[REPO_ROOT / "abap"],
    )
    assert {finding.rule_id for finding in result.findings} == {"SI-MM-001"}


def test_backlog_is_ordered_by_wave_then_severity():
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    backlog = report.build_backlog(result)
    waves = [obj.wave for obj in backlog]
    assert waves == sorted(waves, key=wave_rank)
    assert backlog[0].wave == "wave0"


def test_markdown_report_contains_the_key_sections():
    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    markdown = report.to_markdown(result)
    for heading in (
        "# Custom code remediation backlog",
        "## Summary",
        "## Findings by wave",
        "## Prioritised backlog",
        "## Target patterns",
    ):
        assert heading in markdown


def test_json_report_is_machine_readable():
    import json

    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    payload = json.loads(report.to_json(result))
    assert payload["summary"]["findings"] == len(result.findings)
    assert payload["effort"]["engineer_days"] > 0
    assert payload["objects"][0]["wave"] == "wave0"
