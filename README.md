# GSK ERP Evolution - engineering workspace

A working repository for the engineering long-tail of an SAP ECC 6.0 to
S/4HANA programme in a GxP-regulated pharma estate: custom ABAP code
remediation, wave data migration, and the test and validation evidence
that goes with both.

The estate is **two** ECC production systems converging into **one**
S/4HANA client:

| | System | Estate | Wave 0 extracts |
| --- | --- | --- | --- |
| `GEP` | GSK core ECC 6.0 | `abap/ecc/gep` (17 objects) | `data/wave0/gep` |
| `GVP` | GSK Vaccines ECC 6.0 | `abap/ecc/gvp` (8 objects) | `data/wave0/gvp` |

That makes it a consolidation as well as a conversion, which is the
part with no SAP tool to run: the same function exists twice, built by
different teams years apart, and only one implementation survives.
Same again in the data - the same counterparty and the same product are
mastered in both systems under numbers that collide.
`docs/CONVERGENCE.md` is the detail.

Everything here runs. `make check` is the gate.

## Why this shape

The programme decomposes into workstreams; four of them are pattern
heavy, high volume and directly measurable, and those are the ones this
repository models:

| Workstream | In this repo |
| --- | --- |
| Custom code remediation | `abap/ecc` (the two ECC estates), `abap/remediated` (the target pattern), `tools/s4scan` (the scanner), `reports/remediation-backlog.md` |
| Custom code convergence | `convergence_group` in `estate/inventory.csv`, rule `SI-CONV-001`, `docs/CONVERGENCE.md` |
| Data migration engineering | `data/wave0` (ECC extracts from both systems), `tools/datamig` (extract, cleanse, map, load, reconcile), `reports/wave0/reconciliation.md` |
| Test and validation evidence | `abap/remediated/*.testclasses.abap`, rule `SI-GXP-001`, `docs/VALIDATION.md` |

See `docs/PROGRAMME.md` for the programme context and
`docs/DEMO.md` for how to drive the repository in a walkthrough.

## What is real and what stands in

Worth being explicit, because the distinction matters when reading any
number below.

**Representative.** The shape of the estate: two ECC systems with
overlapping number ranges and independently grown duplicates of the
same function; the simplification items the legacy ABAP hits; the
GxP validation multiplier; the data quality and reconciliation
disciplines; the convergence and decommission decisions the merge
forces.

**Standing in.** The ABAP is never compiled or executed here - it is
the subject matter, hand-written to be representative rather than
exported from a system. 25 objects stand in for tens of thousands.
The CSVs stand in for extracts. On a real programme the inputs come
from elsewhere: an abapGit or gCTS export instead of a hand-built
tree, SAP ATC and the Custom Code Migration app plus SCMON/UPL usage
data instead of `s4scan`, and Migration Cockpit or BODS instead of
`datamig`.

**Actually computed.** The Python tooling runs for real over that
fixture data. Every count, every finding and every reconciliation
result in this repository - and in `reports/` - is produced by
executing the code, not written down. Change a source file and the
numbers move; CI fails if the committed reports go stale.

## Quick start

```bash
make setup          # pip install -e ".[dev]"
make scan           # summary of the ECC estate
make migrate        # run the wave 0 pipeline into out/wave0
make check          # ruff + pytest + the readiness gate
```

## The custom code scanner

`s4scan` parses the ABAP sources, applies 22 simplification, clean-core
and convergence rules, joins the findings to the object inventory in
`estate/inventory.csv` (source system, owner, wave, GxP class,
execution volume, disposition) and emits a prioritised backlog with an
effort estimate that carries the GxP validation multiplier.

```bash
s4scan rules                                  # the rule catalogue
s4scan scan abap/ecc                          # summary, both systems
s4scan scan abap/ecc --system GVP             # one ECC system
s4scan scan abap/ecc --wave wave0             # one deployment wave
s4scan scan abap/ecc --format markdown --out reports/remediation-backlog.md
s4scan scan abap/remediated --fail-on minor   # the gate for remediated code
```

Current state of the estate:

| | |
| --- | --- |
| Objects scanned | 25 (17 GEP, 8 GVP) |
| Objects remediated | 2 |
| Objects decommissioned at the merge | 2 |
| Findings outstanding | 279 (46 blocker, 106 critical, 84 major, 43 minor) |
| Estimated effort | 274 engineer-days, of which 93 is GxP validation overhead |
| Cleared so far | 32 engineer-days |
| Avoided by converging duplicates | 46.5 engineer-days across 4 of the 6 groups |
| Avoided by decommissioning cross-system interfaces | 20 engineer-days |

An object leaves the backlog when `estate/inventory.csv` names its
S/4HANA successor in `remediated_path`. The ECC source stays in
`abap/ecc` as the before/after pair the validation package needs, so
its findings are reported as cleared rather than disappearing. Objects
marked `decommission` also leave the backlog - they are still scanned
and still reported, but no effort is estimated for work on something
that will not exist after the merge.

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

It reads both systems in one run. Every source key is qualified with
its system (`GEP/0000210045`, `GVP/0000210045`) because the two ECC
systems share number ranges and the same number usually means two
different companies.

The wave 0 extracts carry deliberate defects - a batch-managed material
with no shelf life, an unbalanced FI document, an open item for a
partner that does not exist, batch stock for a material that is not
batch managed, batch stock whose unit contradicts the material master,
an invalid ISO country. Each one is caught by a named
data quality rule, held back from the load, and reported.

The merge is where two sources become one client:

```
object         extracted  rejected  merged  loaded   warn
materials             30         4       3      23      6
customers             25         2       0      23      9
vendors               21         1       0      20     11
open_items            42         6       0      36      1
batch_stock           31         9       0      22     10

business partners created: 33 (merged 10 source records, 7 held in both systems)
products created: 23 (harmonised 3 duplicate materials away)
```

The customer/vendor to business partner conversion is the interesting
mapping. GSK Ireland Manufacturing is both a customer and a supplier
and becomes one BP with all four roles; Lonza AG is a supplier three
times over across both systems and becomes one BP with three company
code segments; UNICEF Supply Division is a customer in each system
under a different number and becomes one BP with both in the
cross-reference.

Materials merge only where `data/wave0/material_harmonisation.csv` says
so - a governed decision, not a description match - and the `REC-MRG-*`
checks prove the arithmetic, because with two sources loading into one
client a smaller target count is both the intended outcome and what
data loss looks like.

## Layout

```
abap/ecc/gep/       GSK core ECC custom code estate, by module
abap/ecc/gvp/       GSK Vaccines ECC custom code estate, by module
abap/remediated/    S/4HANA target pattern with ABAP Unit tests
estate/             object inventory (system, owner, wave, GxP class, volumes, disposition)
tools/s4scan/       custom code readiness scanner
tools/datamig/      wave migration pipeline
data/wave0/gep/     core ECC extracts for wave 0
data/wave0/gvp/     Vaccines ECC extracts for wave 0
reports/            committed scanner and reconciliation output
tests/              pytest suite for both tools
docs/               programme, convergence, clean core, validation, demo notes
```

## Contributing

`AGENTS.md` has the conventions. Two rules matter most: remediated ABAP
must scan clean, and any change to the tooling must leave the committed
reports in `reports/` regenerated - CI fails if they are stale.
