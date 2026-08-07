# Working in this repository

## What this repository is

The engineering workspace for the ERP Evolution programme: the ECC
custom code estate, the tooling that measures and remediates it, and
the wave data migration pipeline. Two languages: ABAP (not executed
here, it is the subject matter) and Python (the tooling, which must
run).

There are two ECC source systems, `GEP` (GSK core) and `GVP` (GSK
Vaccines), converging into one S/4HANA client. Anything you add - an
object, an inventory row, an extract, a rule - belongs to one of them
and has to say so. `docs/CONVERGENCE.md` explains what that implies.

## Before you start

```bash
make setup
make check
```

`make check` runs ruff, pytest and the readiness gate. It must pass
before any PR.

## Conventions

### Python tooling

- Python 3.10+, standard library only for runtime code. `pytest` and
  `ruff` are the only dev dependencies. Do not add a dependency without
  a stated reason in the PR.
- `ruff check tools tests` is the linter, configured in `pyproject.toml`
  (line length 100). No separate formatter.
- Type annotations on public functions. `from __future__ import
  annotations` at the top of every module.
- Dataclasses for value objects. No dictionaries as ad-hoc records once
  data has been mapped.
- Determinism matters: the reports in `reports/` are committed and CI
  fails if a code change leaves them stale. Never put a timestamp, a
  random value or an absolute path into report output.

### Remediating ABAP

- Legacy sources live in `abap/ecc/gep` and `abap/ecc/gvp` and are the
  *problem statement* - do not tidy them opportunistically. Change them
  only when the task is to remediate them.
- An object in a `convergence_group` has a counterpart in the other
  system. Do not remediate one side of a group on its own: the target
  is a single object, and remediating both in place carries the
  duplication into S/4HANA. Resolve the group, then build once.
- An object with `disposition=decommission` is not remediated at all.
  It leaves the backlog through the inventory, not through code.
- `abap/remediated/` is the reference for the target pattern: released
  CDS views and APIs, set-based selects, no header lines or `OCCURS`,
  data access behind an interface so ABAP Unit can substitute a test
  double.
- Any object you remediate must:
  1. scan clean (`s4scan scan <path> --fail-on minor`);
  2. ship an ABAP Unit test class named `<object>.testclasses.abap`;
  3. keep its inventory row in `estate/inventory.csv` accurate, with
     `source_system` set and `remediated_path` pointing at the S/4HANA
     successor - that is what takes the object out of the backlog;
  4. regenerate the reports (`make scan-report`).
- If a finding cannot be remediated, do not silence the rule. Record
  the deviation in the PR and leave the finding visible.

### Adding a scanner rule

1. Add the `Rule` to `tools/s4scan/rules.py` with a unique id, guidance
   that names the S/4HANA target, and a `sap_reference` naming the SAP
   simplification topic. Rule ids are programme ids, not SAP note
   numbers - do not invent note numbers.
2. Add a positive case to the parametrised test in
   `tests/test_rules.py`, and a negative case if the rule is prone to
   false positives. An object rule - one that fires on the object's
   place in the estate rather than on a statement, like `SI-GXP-001`
   and `SI-CONV-001` - has no statement to match, so it is tested in
   `tests/test_scanner.py` against the inventory instead, and must
   assert in `tests/test_rules.py` that it never matches a statement.
3. Regenerate the reports: `make scan-report`.

### Adding a data quality or reconciliation rule

- Cleansing rules carry an id (`DQ-<OBJ>-<n>`) and an action: `FIX`
  repairs the value, `WARN` keeps the record and raises an exception,
  `REJECT` holds it back from the load. Nothing is ever silently
  dropped.
- Every reject must be reproducible from the committed extracts in
  `data/wave0/gep` and `data/wave0/gvp`, and must appear in the
  reconciliation report.
- Source keys are qualified with the source system (`GEP/0000210045`).
  The two ECC systems share number ranges, so an unqualified key merges
  unrelated records. Use `identity.source_key`, never the raw number.
- Two sources loading into one client means the target count is
  legitimately smaller than the source count. Any such reduction needs
  a merge check that accounts for it (`REC-MRG-*`); never relax a count
  check to absorb it.
- A reconciliation check compares a value counted on the ECC side with
  the same value counted on the S/4HANA side. If a check cannot fail,
  it is not a check.

## Testing

- `pytest` only, no fixtures pulled from a live system.
- Tests assert on behaviour, not on the exact finding count of the
  estate - that number moves whenever a source file changes.
- The suite must stay under a second; it runs on every push.

## Commits and PRs

- Conventional commit subjects (`feat:`, `fix:`, `chore:`).
- One workstream per PR: a code remediation PR does not also change the
  scanner.
- Regenerate `reports/` in the same commit as any change that affects
  them.
