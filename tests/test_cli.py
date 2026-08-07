from pathlib import Path

import pytest

from datamig import cli as datamig_cli
from s4scan import cli as s4scan_cli

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _run_from_repo_root(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)


def test_s4scan_rules_command_lists_the_catalogue(capsys):
    assert s4scan_cli.main(["rules"]) == 0
    output = capsys.readouterr().out
    assert "SI-MM-001" in output
    assert "SI-GXP-001" in output


def test_s4scan_fail_on_blocker_gates_the_legacy_estate(capsys):
    exit_code = s4scan_cli.main(["scan", "abap/ecc", "--fail-on", "blocker"])
    capsys.readouterr()
    assert exit_code == 1


def test_s4scan_passes_on_the_remediated_reference(capsys):
    exit_code = s4scan_cli.main(["scan", "abap/remediated", "--fail-on", "minor"])
    capsys.readouterr()
    assert exit_code == 0


def test_s4scan_system_filter_restricts_the_scan(capsys):
    s4scan_cli.main(["scan", "abap/ecc"])
    both = capsys.readouterr().out

    s4scan_cli.main(["scan", "abap/ecc", "--system", "GVP"])
    vaccines_only = capsys.readouterr().out

    assert "GEP" in both and "GVP" in both
    assert "GVP" in vaccines_only
    assert "GEP" not in vaccines_only


def test_s4scan_summary_reports_the_merge(capsys):
    s4scan_cli.main(["scan", "abap/ecc"])
    output = capsys.readouterr().out
    assert "convergence groups" in output
    assert "decommissioned" in output


def test_s4scan_writes_a_report(tmp_path, capsys):
    out_file = tmp_path / "backlog.md"
    exit_code = s4scan_cli.main(
        ["scan", "abap/ecc", "--format", "markdown", "--out", str(out_file)]
    )
    capsys.readouterr()
    assert exit_code == 0
    assert "Custom code remediation backlog" in out_file.read_text(encoding="utf-8")


def test_datamig_run_writes_load_files(tmp_path, capsys):
    out_dir = tmp_path / "wave0"
    exit_code = datamig_cli.main(
        ["run", "--wave", "wave0", "--out", str(out_dir)]
    )
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "reconciliation: PASS" in output
    assert (out_dir / "s4_business_partner.csv").exists()
    assert (out_dir / "reconciliation.md").exists()


def test_datamig_fail_on_reject_gates_the_wave(tmp_path, capsys):
    exit_code = datamig_cli.main(
        ["run", "--wave", "wave0", "--out", str(tmp_path), "--fail-on-reject"]
    )
    capsys.readouterr()
    assert exit_code == 1


def test_datamig_reports_a_missing_extract(tmp_path, capsys):
    exit_code = datamig_cli.main(
        ["run", "--wave", "wave9", "--source", str(tmp_path / "missing")]
    )
    assert exit_code == 2
    assert "not found" in capsys.readouterr().err
