# GxP validation approach

The ERP is a validated system. Every remediated object, interface and
migrated data object needs documented evidence that it does what it is
specified to do. In pharma programmes this is typically 30-40% of total
effort, which is why it is modelled explicitly here rather than
assumed.

## Classification

`estate/inventory.csv` classifies every object:

| Class | Meaning | Effort multiplier |
| --- | --- | --- |
| `gxp_critical` | Directly supports a GMP decision or record - batch release, batch traceability, labelling, electronic batch record data flow | 2.0 |
| `gxp_relevant` | Feeds or constrains a GxP process without making the decision | 1.5 |
| `non_gxp` | No GxP impact; may still be SOX relevant | 1.0 |

The multiplier is applied to raw remediation effort in the backlog
report, so the plan shows the validation overhead as a separate number
rather than burying it. For the current estate that is 93 of 274
engineer-days.

## Evidence per remediated object

An object is not done until all four exist:

1. **Specification delta** - what changed and why, traceable to a
   simplification item. The scanner finding is the trace: it names the
   rule, the line, and the target pattern.
2. **Automated test evidence** - an ABAP Unit test class named
   `<object>.testclasses.abap`, running against a test double rather
   than client data so the run is reproducible in any client. Rule
   `SI-GXP-001` fails any GxP object without one; 13 outstanding
   objects across the two systems are short of one.
3. **Review record** - the pull request. One remediated object per PR,
   reviewed by the object owner named in the inventory.
4. **Regression run** - the object's tests green in CI on the wave
   branch, plus the wave regression suite.

## Evidence per migrated data object

The reconciliation report (`reports/wave0/reconciliation.md`) is the
evidence pack for a load:

- record counts on both sides, per object, with rejects itemised;
- value totals per company code and currency;
- debit/credit balance per company code on the loaded data;
- quantity totals per plant;
- business partner conversion arithmetic, including merges;
- an exception file per object, naming the data quality rule, the key
  and the reason.

Each check states what a pass is worth. A **compared** check counts
its two sides from different things - the ECC extract and the rows
written to the target - so it can fail on real data. An **asserted**
check reads both sides off the load file and holds it against a rule
the target must satisfy - a key that is unique, a document that
balances, a partner reference that resolves. Bad input is how it
fails, so it is not an invariant, but it never looks at the extract
and is no evidence that the extract arrived whole. An **invariant**
derives both sides from the same data: it holds unless the tooling
itself is broken, which is worth knowing but is not evidence about the
load. All of the record arithmetic is an invariant, because every
mapping emits one row per accepted record or stops - partners
included, where each accepted record is appended to its business
partner unconditionally. The count checks beside it compare key sets
and are the ones that fail on real data. An assessor should read the
column, not the pass count.

A wave cannot be signed off with a failing check. Warnings are allowed
but must be explained in the cutover log - for wave 0 the open ones are
stock sitting in quality inspection at cutover (needs a usage decision
before go-live) and suppliers without a GMP audit flag.

## Data integrity expectations

Aligned with Annex 11 / 21 CFR Part 11 thinking, the pipeline is built
so that:

- **nothing is silently dropped** - every record is loaded, rejected
  with a reason, or flagged, and the three numbers reconcile;
- **runs are deterministic** - same input, same output, byte for byte;
  no timestamps or absolute paths in the artefacts, so a re-run can be
  diffed against the signed evidence;
- **transformations are attributable** - each `FIX` action is recorded
  as an issue with the rule id, so an auditor can see that a base unit
  was upper-cased and by which rule;
- **rejects are reproducible** - the extracts are committed, so any
  reject can be re-created from source.

## What AI-assisted engineering changes here

Not the standard - the standard is set by the regulator. What changes
is who produces the first draft of the evidence: test classes,
specification deltas and reconciliation narratives are generated with
the change and reviewed by the object owner, instead of being written
by hand weeks later. The comparable public data point is Evinova
(AstraZeneca group, 21 CFR Part 11 environment): 8x faster GxP
documentation and test automation compressed from quarters to weeks.
