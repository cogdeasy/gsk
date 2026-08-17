# GSK ERP Evolution - engineering workspace

A working repository for the engineering long-tail of an SAP ECC 6.0 to
S/4HANA programme in a GxP-regulated pharma estate: custom ABAP code
remediation, wave data migration, and the test and validation evidence
that goes with both.

It contains a representative slice of a GSK-shaped estate (16 custom
objects across MM, FI, SD, CO, PP, QM and the interface layer), the
tooling that turns that estate into a prioritised remediation backlog,
and a wave 0 data migration pipeline that produces load files plus
signed-off reconciliation evidence.

Everything here runs. `make check` is the gate.

## Why this shape

The programme decomposes into workstreams; three of them are pattern
heavy, high volume and directly measurable, and those are the ones this
repository models:

| Workstream | In this repo |
| --- | --- |
| Custom code remediation | `abap/src` (the ECC estate), `abap/remediated` (the target pattern), `tools/s4scan` (the scanner), `reports/remediation-backlog.md` |
| Data migration engineering | `data/wave0` (ECC extracts), `tools/datamig` (extract, cleanse, map, load, reconcile), `reports/wave0/reconciliation.md` |
| Test and validation evidence | `abap/remediated/*.testclasses.abap`, rule `SI-GXP-001`, `docs/VALIDATION.md` |

See `docs/PROGRAMME.md` for the programme context and
`docs/DEMO.md` for how to drive the repository in a walkthrough.

## Quick start

```bash
make setup          # pip install -e ".[dev]"
make scan           # summary of the ECC estate
make migrate        # run the wave 0 pipeline into out/wave0
make check          # ruff + pytest + the readiness gate
```

## The custom code scanner

`s4scan` parses the ABAP sources, applies 21 simplification and
clean-core rules, joins the findings to the object inventory in
`estate/inventory.csv` (owner, wave, GxP class, execution volume) and
emits a prioritised backlog with an effort estimate that carries the
GxP validation multiplier.

```bash
s4scan rules                                  # the rule catalogue
s4scan scan abap/src                          # summary
s4scan scan abap/src --wave wave0             # one deployment wave
s4scan scan abap/src --format markdown --out reports/remediation-backlog.md
s4scan scan abap/remediated --fail-on minor   # the gate for remediated code
```

Current state of the estate:

| | |
| --- | --- |
| Objects scanned | 16 |
| Objects remediated | 3 |
| Findings outstanding | 159 (25 blocker, 55 critical, 49 major, 30 minor) |
| Estimated effort | 134 engineer-days, of which 36 is GxP validation overhead |
| Cleared so far | 46 engineer-days |

An object leaves the backlog when `estate/inventory.csv` names its
S/4HANA successor in `remediated_path`. The ECC source stays in
`abap/src` as the before/after pair the validation package needs, so
its findings are reported as cleared rather than disappearing.

`abap/remediated/` holds those successors: rebuilt against released CDS
views, with ABAP Unit tests over a test double for the data access
layer. They scan clean, which is what "done" looks like for every
object still in the backlog.

## The wave data migration pipeline

`datamig` runs a wave end to end and writes both the load files and the
reconciliation evidence.

```bash
datamig run --wave wave0                      # -> out/wave0
datamig run --wave wave0 --format markdown    # reconciliation report
datamig run --wave wave0 --fail-on-reject     # cutover gate
```

The wave 0 extracts carry deliberate defects - a batch-managed material
with no shelf life, an unbalanced FI document, an open item for a
partner that does not exist, batch stock for a material that is not
batch managed, batch stock whose unit contradicts the material master,
an invalid ISO country. Each one is caught by a named
data quality rule, held back from the load, and reported.

The customer/vendor to business partner conversion is the interesting
mapping: 28 accepted source records collapse into 25 business partners.
GSK Ireland Manufacturing is both a customer and a supplier and becomes
one BP with all four roles; Lonza AG exists twice under two company
codes and becomes one BP with two company code segments.

## Layout

```
abap/src/           ECC custom code estate, by module
abap/remediated/    S/4HANA target pattern with ABAP Unit tests
estate/             object inventory (owner, wave, GxP class, volumes)
tools/s4scan/       custom code readiness scanner
tools/datamig/      wave migration pipeline
data/wave0/         ECC extracts for wave 0
reports/            committed scanner and reconciliation output
tests/              pytest suite for both tools
docs/               programme, clean core, validation, demo notes
```

## Contributing

`AGENTS.md` has the conventions. Two rules matter most: remediated ABAP
must scan clean, and any change to the tooling must leave the committed
reports in `reports/` regenerated - CI fails if they are stale.
