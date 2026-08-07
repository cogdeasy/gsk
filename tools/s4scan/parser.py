"""Minimal ABAP source reader.

The scanner does not need a full ABAP grammar. It needs comment-free,
case-normalised logical statements with the line number they start on,
plus enough block tracking to know whether a statement sits inside a
LOOP. That is what this module provides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_LINE_COMMENT = re.compile(r'"[^"]*$')
_STRING_LITERAL = re.compile(r"'[^']*'")
_LOOP_START = re.compile(r"^(LOOP\s+AT|DO\b|WHILE\b|SELECT\b.*\bENDSELECT)", re.IGNORECASE)
_LOOP_END = re.compile(r"^(ENDLOOP|ENDDO|ENDWHILE)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Statement:
    """A single ABAP statement, normalised for pattern matching."""

    text: str
    line: int
    loop_depth: int

    @property
    def upper(self) -> str:
        return self.text.upper()

    @property
    def in_loop(self) -> bool:
        return self.loop_depth > 0


@dataclass
class AbapSource:
    """Parsed representation of one ABAP source file."""

    path: str
    raw_lines: list[str] = field(default_factory=list)
    statements: list[Statement] = field(default_factory=list)

    @property
    def loc(self) -> int:
        return len(self.raw_lines)

    @property
    def effective_loc(self) -> int:
        """Lines of code excluding blank lines and full-line comments."""
        count = 0
        for line in self.raw_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("*"):
                continue
            count += 1
        return count


def strip_comments(line: str) -> str:
    """Remove ABAP comments from a physical line.

    A ``*`` in the first column comments out the whole line; a double
    quote starts a comment that runs to the end of the line, unless it
    is inside a character literal.
    """
    if line.lstrip().startswith("*"):
        return ""
    masked = _STRING_LITERAL.sub(lambda m: "\x00" * len(m.group()), line)
    match = _LINE_COMMENT.search(masked)
    if match:
        line = line[: match.start()]
    return line.rstrip()


def parse(path: str, source: str) -> AbapSource:
    """Split ABAP source into logical statements terminated by a period."""
    raw_lines = source.splitlines()
    parsed = AbapSource(path=path, raw_lines=raw_lines)

    buffer: list[str] = []
    start_line = 0
    loop_depth = 0

    for number, raw in enumerate(raw_lines, start=1):
        code = strip_comments(raw)
        if not code.strip():
            continue
        if not buffer:
            start_line = number
        buffer.append(code.strip())

        if not code.rstrip().endswith("."):
            continue

        text = " ".join(buffer).strip()
        buffer = []

        if _LOOP_END.match(text):
            loop_depth = max(0, loop_depth - 1)

        parsed.statements.append(
            Statement(text=text, line=start_line, loop_depth=loop_depth)
        )

        if _LOOP_START.match(text) and not text.upper().startswith("SELECT"):
            loop_depth += 1

    if buffer:
        parsed.statements.append(
            Statement(text=" ".join(buffer).strip(), line=start_line, loop_depth=loop_depth)
        )

    return parsed


def read(path: str) -> AbapSource:
    with open(path, encoding="utf-8") as handle:
        return parse(path, handle.read())
