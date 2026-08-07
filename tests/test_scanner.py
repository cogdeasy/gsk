from pathlib import Path

from s4scan import report
from s4scan.inventory import Inventory
from s4scan.rules import RuleFilter, Severity
from s4scan.scanner import object_name_for, scan, scan_file

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY = REPO_ROOT / "abap" / "src"
REMEDIATED = REPO_ROOT / "abap" / "remediated"
INVENTORY = REPO_ROOT / "estate" / "inventory.csv"


def load_inventory() -> Inventory:
    return Inventory.load(INVENTORY)


def test_object_name_is_derived_from_the_file_name():
    assert object_name_for(Path("a/zgsk_mm_stock_overview.prog.abap")) == (
        "ZGSK_MM_STOCK_OVERVIEW"
    )
    assert object_name_for(Path("a/zgsk_if_label_print.fugr.abap")) == (
        "ZGSK_IF_LABEL_PRINT"
    )


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
    import json

    result = scan([LEGACY], inventory=load_inventory(), test_roots=[REPO_ROOT / "abap"])
    payload = json.loads(report.to_json(result))
    summary = payload["summary"]

    assert summary["outstanding_findings"] < summary["findings"]
    assert summary["objects_outstanding"] + summary["objects_remediated"] == (
        summary["objects_with_findings"]
    )
    assert payload["cleared_effort"]["engineer_days"] > 0
    assert {item["object_name"] for item in payload["remediated"]} == {
        obj.object_name for obj in result.remediated()
    }


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
        LEGACY / "mm" / "zgsk_mm_stock_overview.prog.abap",
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
    assert waves == sorted(waves, key=lambda wave: report.WAVE_ORDER[wave])
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
