import pytest

from s4scan import parser
from s4scan.rules import RULES_BY_ID, Severity, all_rules


def statement_for(source: str):
    parsed = parser.parse("x.abap", source)
    return parsed.statements[0]


@pytest.mark.parametrize(
    ("rule_id", "source"),
    [
        ("SI-MM-001", "SELECT * FROM mard INTO TABLE gt_stock."),
        ("SI-MM-002", "SELECT mblnr FROM mseg INTO gv_mblnr."),
        ("SI-MM-003", "DATA: gv_matnr TYPE char18."),
        ("SI-FI-001", "SELECT * FROM bsis INTO TABLE gt_lines."),
        ("SI-FI-002", "SELECT SINGLE prctr FROM bseg INTO gv_prctr."),
        ("SI-CO-001", "SELECT * FROM cosp INTO TABLE gt_cosp."),
        ("SI-SD-001", "SELECT * FROM vbuk INTO TABLE gt_vbuk."),
        ("SI-SD-002", "SELECT SINGLE klimk FROM knkk INTO gv_limit."),
        ("SI-MD-001", "MODIFY kna1 FROM ls_kna1."),
        ("SI-PP-001", "SELECT * FROM mdtb INTO TABLE gt_mdtb."),
        ("SI-OM-001", "UPDATE nast SET vstat = '2'."),
        ("SI-QM-001", "SELECT * FROM mcha INTO TABLE gt_batch."),
        ("SI-TECH-001", "EXEC SQL."),
        ("SI-TECH-002", "CALL FUNCTION 'WS_DOWNLOAD' EXPORTING filename = p_file."),
        ("SI-TECH-003", "DATA: gt_x TYPE STANDARD TABLE OF mard WITH HEADER LINE."),
        ("SI-TECH-005", "SELECT * FROM t001w INTO TABLE gt_plants."),
        ("SI-TECH-006", "SELECT * FROM nast CLIENT SPECIFIED INTO TABLE gt_nast."),
    ],
)
def test_rule_matches_its_pattern(rule_id, source):
    rule = RULES_BY_ID[rule_id]
    assert rule.evidence(statement_for(source)) is not None


def test_marc_read_is_not_flagged_as_aggregate_stock():
    rule = RULES_BY_ID["SI-MM-001"]
    statement = statement_for("SELECT SINGLE meins FROM marc INTO gv_meins.")
    assert rule.evidence(statement) is None


def test_business_partner_rule_is_write_only():
    rule = RULES_BY_ID["SI-MD-001"]
    assert rule.evidence(statement_for("SELECT SINGLE name1 FROM kna1 INTO gv_n.")) is None
    assert rule.evidence(statement_for("UPDATE lfa1 FROM ls_lfa1.")) == "LFA1"


def test_loop_only_rules_need_a_loop_context():
    rule = RULES_BY_ID["SI-TECH-004"]
    source = "\n".join(
        [
            "SELECT SINGLE meins FROM marc INTO gv_meins.",
            "LOOP AT gt_stock.",
            "  SELECT SINGLE meins FROM marc INTO gv_meins.",
            "ENDLOOP.",
        ]
    )
    parsed = parser.parse("x.abap", source)
    assert rule.evidence(parsed.statements[0]) is None
    assert rule.evidence(parsed.statements[2]) is not None


def test_commented_code_is_never_flagged():
    parsed = parser.parse("x.abap", "* SELECT * FROM mseg INTO TABLE gt_mseg.")
    assert parsed.statements == []


def test_rule_ids_are_unique_and_documented():
    rules = all_rules()
    assert len({rule.id for rule in rules}) == len(rules)
    for rule in rules:
        assert rule.guidance.strip()
        assert rule.sap_reference.strip()
        assert rule.effort_points > 0
        assert isinstance(rule.severity, Severity)
