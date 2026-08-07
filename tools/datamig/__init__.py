"""Wave data migration pipeline for the GSK ERP Evolution programme.

Extract, cleanse, map, load and reconcile per wave. The pipeline is
deliberately deterministic and file based: every run produces the load
files plus the reconciliation evidence that the cutover and validation
packages require.
"""

__all__ = ["extract", "cleanse", "mapping", "load", "reconcile", "pipeline"]

__version__ = "0.1.0"
