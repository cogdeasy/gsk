"""Custom code readiness scanner for the GSK ERP Evolution programme.

Scans the ABAP custom code estate for S/4HANA simplification items and
clean-core violations, joins the findings to the object inventory
(owner, wave, GxP classification) and produces the remediation backlog.
"""

__all__ = ["rules", "parser", "scanner", "inventory", "report"]

__version__ = "0.1.0"
