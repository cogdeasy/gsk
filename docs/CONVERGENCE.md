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
example when a workstream owns only one of them.

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
and applies exactly that. Descriptions that match without a decision
are raised as `DQ-MAT-008` for a steward to look at.

**A merge inherits the quality of its target.** `DQ-MAT-010` is the
consequence: if the surviving product is rejected by cleansing, the
record that was to be retired has nowhere to land, and loading it under
its own number instead would quietly reverse a governed decision and
split the product's stock across two numbers. It is held back until the
surviving master is corrected, and the batches sitting on that material
are held with it under `DQ-STK-006`, which names the harmonisation
rather than reporting a missing master the steward would go looking
for.

**The merge is reconciled, not assumed.** With two sources loading into
one client, fewer target records than source records is the intended
outcome - which is also exactly what data loss looks like. So:

| Check | Proves |
| --- | --- |
| `REC-MRG-001` | partner records - merges = business partners |
| `REC-MRG-002` | material records - harmonisations = products |
| `REC-MRG-003` | every harmonised material resolves to a product that is actually in the load |
| `REC-MRG-004` | every harmonisation decision was applied, or the material it names was rejected |

The reconciliation report also breaks accepted records down by source
system, so each side can see its own contribution to the merged total.
