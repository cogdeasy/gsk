# Two systems into one

The migration is a conversion and a consolidation at the same time.
`GEP` (the GSK core) and `GVP` (GSK Vaccines) are separate ECC 6.0
production systems, and both land in one S/4HANA client.

SAP has tooling for the conversion half. The Readiness Check and the
Custom Code Migration app will tell you that a program reads MARD and
that MARD no longer holds what it used to. Nothing tells you that the
program has a sibling in the other system doing the same job
differently, and that only one of them can survive.

That is what this document, the `convergence_group` column in
`estate/inventory.csv`, and rule `SI-CONV-001` are for.

## Why there are two systems

Vaccines ran on its own instance long before the ERP unification
programme, and the unification waves of the 2010s never absorbed it.
Both systems were configured from the same late-1990s template, which
has two consequences that shape everything below:

- **The same function was built twice.** Each system grew its own stock
  report, its own batch release program, its own AP ageing report -
  written years apart by different teams against the same underlying
  tables.
- **The number ranges are identical.** Customer 21xxxx and supplier
  51xxxx exist in both systems, denoting different companies. The
  numbers are not unique across the estate, so nothing downstream may
  key on the source number alone.

## What converges

`estate/inventory.csv` assigns every object a `disposition`:

| Disposition | Meaning |
| --- | --- |
| `retain` | Only one system has it. Remediate and migrate as-is. |
| `converge` | Both systems have it. One target object, decided in fit-gap. |
| `decommission` | It only exists because the systems are separate. It goes. |

Objects that converge share a `convergence_group`:

| Group | GEP | GVP | The divergence to resolve |
| --- | --- | --- | --- |
| `CG-MM-STOCK` | `ZGSK_MM_STOCK_OVERVIEW` | `ZBIO_MM_STOCK_REPORT` | Vaccines filters on storage temperature class; the core has no such concept. |
| `CG-MM-BATCHGEN` | `ZGSK_MM_BATCH_MOVEMENTS` | `ZBIO_MM_BATCH_GENEALOGY` | Vaccines walks multi-level genealogy back to antigen bulk; the core reports one level of movements. |
| `CG-QM-RELEASE` | `ZGSK_QM_BATCH_RELEASE` | `ZBIO_QM_LOT_RELEASE` | Vaccines cannot release without an OCABR certificate from a national control laboratory. The core release has no equivalent gate. |
| `CG-MD-PARTNER` | `ZGSK_MD_CUSTOMER_SYNC` | `ZBIO_MD_PARTNER_SYNC` | Both write master tables directly, with different number ranges and different duplicate handling. |
| `CG-IF-LABEL` | `ZGSK_IF_LABEL_PRINT` | `ZBIO_IF_LABEL_PRINT` | The core prints on delivery; Vaccines prints on process-order confirmation and carries serialisation data for FMD aggregation. |
| `CG-FI-APAGE` | `ZGSK_FI_AP_AGEING` | `ZBIO_FI_AP_AGEING` | Different bucket definitions - Vaccines has a fifth bucket and includes cleared items. |
| `CG-IF-ICT` | `ZGSK_IF_ICT_ANTIGEN_IN` | `ZBIO_IF_ICT_ANTIGEN_OUT` | Not a convergence. Both sides are decommissioned. |

`ZBIO_PP_ANTIGEN_YIELD` has no group and no counterpart: antigen bulk
campaign yield does not exist in the core system. It is a genuine
fit-gap item, and the target either grows an extension for it or
Vaccines loses a validated process. Objects like this are the reason
"just adopt the core template" is not a plan.

## Why convergence is scanned, not just documented

`SI-CONV-001` fires on every object in a convergence group that has not
been remediated yet. It is deliberately raised against *both*
implementations rather than nominating a survivor, because the scanner
has no basis to pick one - that decision needs the business.

The rule is severity `critical` and sequenced before remediation for a
practical reason: remediating both objects in place is worse than doing
nothing to them. You pay twice, you validate twice, and you carry the
duplication into the target where it is far more expensive to remove.
The order has to be fit-gap, then one build.

`s4scan scan abap/ecc` reports what that saves:

```
convergence groups    : 4 (46.5 engineer-days avoided by building one object)
groups already built  : 2 (CG-MM-BATCHGEN, CG-MM-STOCK)
                        the saving on these is already taken
```

The estimate is the difference between remediating every member
independently and building the largest member once plus a fit-gap
allowance. It is a planning number, not a quote.

Six groups exist; four carry a saving. `CG-MM-STOCK` and
`CG-MM-BATCHGEN` have a core implementation that is already rebuilt in
S/4HANA, so there is no choice left to make and no saving left to
claim - the Vaccines object folds into the object that exists. Counting
the rebuilt side would claim credit for work the same report counts as
cleared. The backlog lists those two separately, and `SI-CONV-001`
still fires on the object that remains.

Use `--system GEP` or `--system GVP` to scan one estate at a time, for
example when a workstream owns only one of them. The convergence
groups are worked out over the whole estate and then narrowed to the
ones the view can see, so a single-system scan still shows the
duplication its own objects are flagged for. The days shown are the
whole group's - a programme saving realised once, not something either
system can bank on its own - and the report says so.

## Interfaces that disappear

`CG-IF-ICT` is the clearest saving in the estate and the easiest to
miss. `ZBIO_IF_ICT_ANTIGEN_OUT` sends antigen bulk and finished vaccine
from Vaccines to the core as an intercompany sale, and
`ZGSK_IF_ICT_ANTIGEN_IN` receives the DESADV and posts the goods
receipt against an intercompany purchase order. Both are GxP-relevant,
both are validated, and both exist purely because the stock is in two
systems. In one client the same movement is an internal stock transport
and neither program has a job.

Objects marked `decommission` are excluded from the remediation backlog
and reported separately, so the effort estimate never includes work on
something that will not exist. They are still scanned - the findings
stay visible, because "we are decommissioning it" is a decision that
gets revisited.

## Master data: the merge in the data pipeline

The same problem appears in `tools/datamig`, where it is arithmetic
rather than judgement.

**Source keys are qualified with the system.** `GEP/0000210045` and
`GVP/0000210045` are two different companies (NHS Supply Chain, and
Institut Pasteur de Dakar). `DQ-CUS-008` and `DQ-VEN-008` report every
number that is reused across the two systems for different entities, so
the collision is on the record before cutover rather than discovered
afterwards as a wrongly combined partner.

**Partners merge on the legal entity.** UNICEF Supply Division is a
customer in both systems under different numbers; it becomes one
business partner with both source numbers in the cross-reference.
`DQ-CUS-007` and `DQ-VEN-007` say which records will merge and whether
the merge crosses systems, before the load runs.

**Products merge only where the business says so.** Deciding that two
materials are the same product has a regulatory consequence, so it is
not inferred from matching descriptions. The pipeline reads
`data/wave0/material_harmonisation.csv`, the data council's decision,
and applies exactly that. Descriptions that match *without* a decision
are raised as `DQ-MAT-008` for a steward to look at; where a decision
covers them, the decision is the confirmation and nothing is raised.
An exception list that repeats settled questions is one nobody reads.

**A shared material number without a decision is a reject, not a
warning.** Partners are merged on the legal entity, so a reused
customer number is only ever a reporting problem. Materials have no
such discriminator: the target product number is the bare MATNR, so
the same number in both systems resolves to one product and the second
record would lose its master data and hand its batches to whatever the
first record was. `DQ-MAT-009` holds both records back until a
harmonisation decision nominates the survivor - the one case where the
tooling refuses to guess and stops the load rather than logging it.
The batches on those materials are held with them under `DQ-STK-007`,
which names the collision rather than reporting a missing master.

**A decision has to say one thing.** A second decision row for the same
material used to be resolved by file order, which is not a governed
decision at all, so the extract refuses it - comparing the numbers
unpadded, since `100801` and `000000000000100801` are the same
material. A `DECISION` value the pipeline does not act on is refused
for the same reason: mapping acts on `merge`, so a typo would leave
the duplicate loading twice under two numbers with no decision for any
check to compare against. A decision naming a product
that another decision itself retires is refused too, but during
cleansing rather than on read: whether that number really disappears
depends on the extracts, because a record in the other system carrying
it may well survive. That is `DQ-MAT-011`, and a merge between
materials held in different base units is `DQ-MAT-012` - stock follows
the harmonised product but keeps its own master's unit, so the merge
would put two units of measure under one product and the plant total
would still balance.

**A decision has to name a product that exists.** `REC-MRG-004`
separates a decision held back by cleansing from one naming a survivor
that is in neither extract. Both look identical in the load file - the
record simply is not there - and only the decision table distinguishes
a hold that will clear from a merge that can never run.

**A merge inherits the quality of its target.** `DQ-MAT-010` is the
consequence: if the surviving product is rejected by cleansing, the
record that was to be retired has nowhere to land, and loading it under
its own number instead would quietly reverse a governed decision and
split the product's stock across two numbers. It is held back until the
surviving master is corrected, and the batches sitting on that material
are held with it under `DQ-STK-006`, which names the harmonisation
rather than reporting a missing master the steward would go looking
for. Three rules can hold a merged material - `DQ-MAT-010`, `-011` and
`-012` - and they are three different pieces of work, so the stock
reject quotes whichever one actually fired rather than a fixed one.

**The merge is reconciled, not assumed.** With two sources loading into
one client, fewer target records than source records is the intended
outcome - which is also exactly what data loss looks like. So:

| Check | Proves |
| --- | --- |
| `REC-MRG-001` | partner records - merges = business partners |
| `REC-MRG-002` | material records - harmonisations = products |
| `REC-MRG-003` | every harmonised material resolves to a product that is actually in the load |
| `REC-MRG-004` | every harmonisation decision was applied, or the material it names was rejected |
| `REC-ARI-*` | the record-count table's own arithmetic: extracted - rejected - merged = loaded |
| `REC-STK-KEY` | initial stock is unique on the real S/4HANA key, which has no source system column |

`REC-ARI-*` exists because the report prints that identity under the
count table. Printed and unchecked, it is a claim about the load file
rather than evidence about it.

Of those, only `REC-MRG-003` and `REC-MRG-004` go and look at the load
file for something a decision named. The rest derive both sides from
the accepted records through the same mapping, so they catch the
tooling breaking and nothing else; the report labels them `invariant`
and the evidence column is the thing to read, not the pass count.

`REC-STK-KEY` exists because every count check keys stock by source
system, which is the right ECC-side key and not a column the target
has. Two systems supplying the same batch on the same harmonised
product and plant would balance every count and still load two rows
S/4HANA cannot tell apart. Today the plants are disjoint, so the
question does not arise - which is exactly why it needs a check rather
than an assumption.

The reconciliation report also breaks accepted records down by source
system, so each side can see its own contribution to the merged total.
