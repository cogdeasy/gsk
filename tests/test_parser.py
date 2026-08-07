from s4scan import parser


def test_full_line_comment_is_removed():
    assert parser.strip_comments("* SELECT * FROM mard.") == ""


def test_inline_comment_is_removed():
    line = "  SELECT * FROM mard. \" legacy read"
    assert parser.strip_comments(line).strip() == "SELECT * FROM mard."


def test_quote_inside_literal_is_not_a_comment():
    line = "  lv_text = 'a \" b'."
    assert parser.strip_comments(line).strip() == "lv_text = 'a \" b'."


def test_statements_are_joined_until_the_period():
    source = "\n".join(
        [
            "SELECT matnr werks",
            "  FROM mard",
            "  INTO TABLE gt_stock",
            "  WHERE werks IN s_werks.",
        ]
    )
    parsed = parser.parse("x.abap", source)
    assert len(parsed.statements) == 1
    statement = parsed.statements[0]
    assert statement.line == 1
    assert "FROM mard" in statement.text


def test_loop_depth_is_tracked():
    source = "\n".join(
        [
            "LOOP AT gt_stock.",
            "  SELECT SINGLE meins FROM marc INTO gv_meins WHERE matnr = gv_matnr.",
            "ENDLOOP.",
            "SELECT SINGLE meins FROM mara INTO gv_meins WHERE matnr = gv_matnr.",
        ]
    )
    parsed = parser.parse("x.abap", source)
    inside, outside = parsed.statements[1], parsed.statements[3]
    assert inside.in_loop is True
    assert outside.in_loop is False


def test_effective_loc_skips_blanks_and_comments():
    source = "\n".join(["* header", "", "REPORT z.", "  WRITE 'x'."])
    parsed = parser.parse("x.abap", source)
    assert parsed.loc == 4
    assert parsed.effective_loc == 2
