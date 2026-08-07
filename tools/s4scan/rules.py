"""Simplification and clean-core rules applied to the ABAP estate.

Each rule maps a pattern in ECC-era custom code to the S/4HANA target
pattern. Rule identifiers are GSK programme identifiers, not SAP note
numbers: the ``sap_reference`` field names the SAP simplification topic
so the finding can be traced to the relevant SAP simplification item
during fit-gap.

``effort_points`` is a relative sizing unit consumed by the backlog
report; it is calibrated in ``report.EFFORT_POINT_HOURS`` and inflated
per object by the GxP validation multiplier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

_DB_STATEMENT = re.compile(
    r"^\s*(SELECT|WITH|UPDATE|MODIFY|INSERT|DELETE|TABLES)\b", re.IGNORECASE
)
_WRITE_STATEMENT = re.compile(r"^\s*(UPDATE|MODIFY|INSERT|DELETE)\b", re.IGNORECASE)


class Severity(str, Enum):
    """Impact of leaving the finding unremediated at cutover."""

    BLOCKER = "blocker"
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {
    Severity.BLOCKER: 0,
    Severity.CRITICAL: 1,
    Severity.MAJOR: 2,
    Severity.MINOR: 3,
}


class Category(str, Enum):
    DATA_MODEL = "data_model"
    FUNCTIONAL_SCOPE = "functional_scope"
    MASTER_DATA = "master_data"
    TECHNICAL_DEBT = "technical_debt"
    VALIDATION = "validation"
    CONVERGENCE = "convergence"


@dataclass(frozen=True)
class Rule:
    """A single detectable simplification or clean-core issue."""

    id: str
    title: str
    category: Category
    severity: Severity
    effort_points: int
    guidance: str
    sap_reference: str
    tables: tuple[str, ...] = ()
    write_only: bool = False
    patterns: tuple[re.Pattern[str], ...] = ()
    requires_loop: bool = False

    def evidence(self, statement) -> str | None:
        """Return the matched text if the statement violates this rule."""
        text = statement.text
        if self.requires_loop and not statement.in_loop:
            return None

        if self.tables:
            if not _DB_STATEMENT.match(text):
                return None
            if self.write_only and not _WRITE_STATEMENT.match(text):
                return None
            for table in self.tables:
                if re.search(rf"\b{table}\b", text, re.IGNORECASE):
                    return table.upper()

        for pattern in self.patterns:
            match = pattern.search(text)
            if match:
                return match.group(0).strip()

        return None


def _pat(*expressions: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(expression, re.IGNORECASE) for expression in expressions)


RULES: tuple[Rule, ...] = (
    Rule(
        id="SI-MM-001",
        title="Aggregate stock table accessed directly",
        category=Category.DATA_MODEL,
        severity=Severity.BLOCKER,
        effort_points=8,
        guidance=(
            "Stock quantity fields in the aggregate tables are not "
            "maintained on S/4HANA. Read stock from the released CDS "
            "views (I_MaterialStock and the NSDM compatibility views) "
            "which are backed by MATDOC."
        ),
        sap_reference="MM-IM: material inventory management data model",
        tables=("MARD", "MCHB", "MSKA", "MSKU", "MSLB", "MSSA", "MSSQ", "MSPR", "MKOL"),
    ),
    Rule(
        id="SI-MM-002",
        title="Material document tables MKPF/MSEG accessed directly",
        category=Category.DATA_MODEL,
        severity=Severity.BLOCKER,
        effort_points=8,
        guidance=(
            "MKPF and MSEG are replaced by MATDOC. Use "
            "I_MaterialDocumentItem or the NSDM_MIG compatibility views; "
            "do not assume MKPF/MSEG field semantics or indexes."
        ),
        sap_reference="MM-IM: MATDOC single document table",
        tables=("MKPF", "MSEG"),
    ),
    Rule(
        id="SI-MM-003",
        title="Material number hard coded to 18 characters",
        category=Category.DATA_MODEL,
        severity=Severity.CRITICAL,
        effort_points=3,
        guidance=(
            "MATNR is 40 characters on S/4HANA. Replace CHAR18 typing, "
            "LENGTH 18 declarations and (18) offsets with TYPE matnr."
        ),
        sap_reference="Extended material number field length",
        patterns=_pat(
            r"\bCHAR18\b",
            r"\bTYPE\s+C\s+LENGTH\s+18\b",
            r"\bmatnr\s*\(\s*18\s*\)",
            r"\w+\(18\)",
        ),
    ),
    Rule(
        id="SI-FI-001",
        title="FI index or totals table accessed directly",
        category=Category.DATA_MODEL,
        severity=Severity.BLOCKER,
        effort_points=8,
        guidance=(
            "Secondary index and totals tables are replaced by the "
            "universal journal. Read ACDOCA through I_JournalEntryItem "
            "or the compatibility views."
        ),
        sap_reference="FI: universal journal ACDOCA",
        tables=(
            "BSIS", "BSAS", "BSID", "BSAD", "BSIK", "BSAK",
            "GLT0", "FAGLFLEXA", "FAGLFLEXT", "KNC1", "LFC1",
        ),
    ),
    Rule(
        id="SI-FI-002",
        title="BSEG/BKPF read where the universal journal should be used",
        category=Category.DATA_MODEL,
        severity=Severity.MAJOR,
        effort_points=5,
        guidance=(
            "BSEG and BKPF still exist but no longer carry the full "
            "line item picture. Reporting reads must move to ACDOCA."
        ),
        sap_reference="FI: universal journal ACDOCA",
        tables=("BSEG", "BKPF"),
    ),
    Rule(
        id="SI-CO-001",
        title="CO totals or line item table accessed directly",
        category=Category.DATA_MODEL,
        severity=Severity.BLOCKER,
        effort_points=8,
        guidance=(
            "COSP, COSS, COEP and COBK are merged into the universal "
            "journal. Use ACDOCA based CDS views for actual and plan "
            "cost reporting."
        ),
        sap_reference="CO: universal journal ACDOCA",
        tables=("COSP", "COSS", "COEP", "COBK", "COSB"),
    ),
    Rule(
        id="SI-SD-001",
        title="Sales document status tables VBUK/VBUP accessed",
        category=Category.DATA_MODEL,
        severity=Severity.BLOCKER,
        effort_points=5,
        guidance=(
            "VBUK and VBUP are removed. The status fields are now part "
            "of VBAK and VBAP; read them from the sales document CDS "
            "views."
        ),
        sap_reference="SD: status tables removed",
        tables=("VBUK", "VBUP"),
    ),
    Rule(
        id="SI-SD-002",
        title="Classic SD credit management objects used",
        category=Category.FUNCTIONAL_SCOPE,
        severity=Severity.CRITICAL,
        effort_points=13,
        guidance=(
            "Classic credit management (FI-AR-CR) is not available. "
            "Rebuild against SAP Credit Management (FIN-FSCM-CR) using "
            "the UKM master data and exposure APIs."
        ),
        sap_reference="FSCM credit management successor",
        tables=("KNKK", "KNKA", "S066", "S067", "S068"),
    ),
    Rule(
        id="SI-MD-001",
        title="Customer or vendor master written outside Business Partner",
        category=Category.MASTER_DATA,
        severity=Severity.BLOCKER,
        effort_points=13,
        guidance=(
            "The Business Partner is the single entry point for "
            "customer and supplier master data. Direct writes to KNA1, "
            "KNB1, LFA1 or LFB1 break CVI synchronisation; use the BP "
            "API or MDG replication."
        ),
        sap_reference="Business Partner mandate / CVI",
        tables=("KNA1", "KNB1", "LFA1", "LFB1", "KNVV", "LFM1"),
        write_only=True,
    ),
    Rule(
        id="SI-MD-002",
        title="Customer or vendor master read directly from the legacy table",
        category=Category.MASTER_DATA,
        severity=Severity.MINOR,
        effort_points=2,
        guidance=(
            "Reads still work through compatibility views but should "
            "move to I_Customer / I_Supplier so the BP attributes are "
            "available."
        ),
        sap_reference="Business Partner mandate / CVI",
        tables=("KNA1", "LFA1", "KNB1", "LFB1"),
    ),
    Rule(
        id="SI-PP-001",
        title="Classic MRP list tables accessed",
        category=Category.FUNCTIONAL_SCOPE,
        severity=Severity.CRITICAL,
        effort_points=8,
        guidance=(
            "MDKP/MDTB are the classic MRP list. MRP Live does not "
            "persist a list in the same way; move to the MRP Live "
            "result CDS views and the material shortage app data model."
        ),
        sap_reference="PP-MRP: MRP Live",
        tables=("MDKP", "MDTB", "MDVM", "MDVL"),
    ),
    Rule(
        id="SI-OM-001",
        title="NAST based output determination used",
        category=Category.FUNCTIONAL_SCOPE,
        severity=Severity.CRITICAL,
        effort_points=13,
        guidance=(
            "Output control on S/4HANA is BRF+ based. NAST processing "
            "and RSNAST00 reprocessing must be rebuilt on the output "
            "management framework, including the error retry path."
        ),
        sap_reference="Output management (BRF+) successor to NAST",
        tables=("NAST",),
        patterns=_pat(r"\bRSNAST00\b"),
    ),
    Rule(
        id="SI-QM-001",
        title="Batch master table read directly",
        category=Category.DATA_MODEL,
        severity=Severity.MAJOR,
        effort_points=3,
        guidance=(
            "Read batch master through I_Batch / I_BatchCharcValue so "
            "the batch classification stays consistent with the "
            "S/4HANA batch model."
        ),
        sap_reference="Batch management data access",
        tables=("MCHA", "MCH1"),
    ),
    Rule(
        id="SI-TECH-001",
        title="Native SQL used",
        category=Category.TECHNICAL_DEBT,
        severity=Severity.BLOCKER,
        effort_points=8,
        guidance=(
            "EXEC SQL bypasses the database abstraction and will not "
            "survive the move to HANA under RISE. Replace with Open SQL "
            "or an AMDP method."
        ),
        sap_reference="HANA database migration",
        patterns=_pat(r"\bEXEC\s+SQL\b", r"\bENDEXEC\b"),
    ),
    Rule(
        id="SI-TECH-002",
        title="Obsolete function module called",
        category=Category.TECHNICAL_DEBT,
        severity=Severity.CRITICAL,
        effort_points=3,
        guidance=(
            "WS_UPLOAD / WS_DOWNLOAD / UPLOAD / DOWNLOAD are obsolete. "
            "Use cl_gui_frontend_services, or for background interfaces "
            "an application server path or the file adapter."
        ),
        sap_reference="Obsolete frontend services",
        patterns=_pat(
            r"CALL\s+FUNCTION\s+'WS_UPLOAD'",
            r"CALL\s+FUNCTION\s+'WS_DOWNLOAD'",
            r"CALL\s+FUNCTION\s+'UPLOAD'",
            r"CALL\s+FUNCTION\s+'DOWNLOAD'",
        ),
    ),
    Rule(
        id="SI-TECH-003",
        title="Obsolete ABAP syntax",
        category=Category.TECHNICAL_DEBT,
        severity=Severity.MAJOR,
        effort_points=2,
        guidance=(
            "Header lines, OCCURS, MOVE and TABLES work areas are not "
            "permitted in clean-core code and block the move to ABAP "
            "for Cloud. Use inline declarations and work areas."
        ),
        sap_reference="ABAP for Cloud language restrictions",
        patterns=_pat(
            r"\bWITH\s+HEADER\s+LINE\b",
            r"\bOCCURS\s+\d+\b",
            r"^\s*MOVE\s+.+\s+TO\s+",
            r"^\s*TABLES\s*:",
        ),
    ),
    Rule(
        id="SI-TECH-004",
        title="Database read inside a loop",
        category=Category.TECHNICAL_DEBT,
        severity=Severity.CRITICAL,
        effort_points=5,
        guidance=(
            "Nested SELECTs dominate runtime on HANA and will not meet "
            "the wave cutover batch windows. Rewrite as a set based "
            "read with a join or FOR ALL ENTRIES."
        ),
        sap_reference="Code pushdown / HANA performance guidance",
        patterns=_pat(r"^\s*SELECT\b"),
        requires_loop=True,
    ),
    Rule(
        id="SI-TECH-005",
        title="SELECT * used",
        category=Category.TECHNICAL_DEBT,
        severity=Severity.MINOR,
        effort_points=1,
        guidance=(
            "Column stores penalise wide reads. Select only the fields "
            "the program uses."
        ),
        sap_reference="Code pushdown / HANA performance guidance",
        patterns=_pat(r"^\s*SELECT\s+\*"),
    ),
    Rule(
        id="SI-TECH-006",
        title="CLIENT SPECIFIED used",
        category=Category.TECHNICAL_DEBT,
        severity=Severity.MAJOR,
        effort_points=2,
        guidance=(
            "Cross client access is not allowed in ABAP for Cloud and "
            "is a data segregation risk under RISE. Remove the addition "
            "and rely on automatic client handling."
        ),
        sap_reference="ABAP for Cloud language restrictions",
        patterns=_pat(r"\bCLIENT\s+SPECIFIED\b"),
    ),
    Rule(
        id="SI-TECH-007",
        title="COMMIT WORK inside a loop",
        category=Category.TECHNICAL_DEBT,
        severity=Severity.MAJOR,
        effort_points=3,
        guidance=(
            "Committing per iteration leaves partial postings after a "
            "failure, which is not acceptable for a GxP interface. Use "
            "a bounded commit block with restart capability."
        ),
        sap_reference="LUW handling / interface restartability",
        patterns=_pat(r"^\s*COMMIT\s+WORK\b"),
        requires_loop=True,
    ),
)


OBJECT_RULES: tuple[Rule, ...] = (
    Rule(
        id="SI-CONV-001",
        title="Function implemented separately in both ECC systems",
        category=Category.CONVERGENCE,
        severity=Severity.CRITICAL,
        effort_points=8,
        guidance=(
            "The core and Vaccines systems each grew their own "
            "implementation of this function. The target is one object, "
            "so the functional divergence between the two has to be "
            "resolved in fit-gap before either is remediated - "
            "remediating both in place carries the duplication into "
            "S/4HANA and doubles the validation package."
        ),
        sap_reference="System consolidation / selective data transition",
    ),
    Rule(
        id="SI-GXP-001",
        title="GxP object has no automated test evidence",
        category=Category.VALIDATION,
        severity=Severity.CRITICAL,
        effort_points=13,
        guidance=(
            "GxP-relevant and GxP-critical objects need documented test "
            "evidence per wave. Add an ABAP Unit test class and link it "
            "to the validation package so regression evidence is "
            "generated automatically."
        ),
        sap_reference="Computer system validation (GAMP 5 / Annex 11)",
    ),
)


RULES_BY_ID: dict[str, Rule] = {
    rule.id: rule for rule in (*RULES, *OBJECT_RULES)
}


def all_rules() -> tuple[Rule, ...]:
    return (*RULES, *OBJECT_RULES)


@dataclass
class RuleFilter:
    """Selection of rules to run, used by the CLI."""

    include: set[str] = field(default_factory=set)
    exclude: set[str] = field(default_factory=set)

    def applies(self, rule: Rule) -> bool:
        if self.include and rule.id not in self.include:
            return False
        return rule.id not in self.exclude
