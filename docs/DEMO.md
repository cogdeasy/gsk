# Walkthrough

A 15-minute path through the repository. Everything below is a real
command with real output; nothing is staged.

## Setup

```bash
make setup
```

## 1. The estate, measured (2 min)

```bash
make scan
```

25 custom objects across two ECC systems - 17 in the GSK core (`GEP`),
8 in Vaccines (`GVP`) - 279 findings outstanding, 46 of them blockers,
plus what has already been cleared. Then the point that matters - it is
not a flat list:

```bash
s4scan scan abap/ecc --format markdown --out /tmp/backlog.md
sed -n '/^## Prioritised backlog/,/^## Object detail/p' /tmp/backlog.md
```

The backlog is ordered by wave, then severity, then business exposure
(monthly execution volume and business criticality from
`estate/inventory.csv`). Effort is sized per object and inflated by the
GxP validation multiplier, so the plan separates 181 days of
engineering from 93 days of validation overhead.

Talking point: an SAP readiness check tells you which simplification
items you hit. This tells you which objects to do first, who owns them,
what the target pattern is for each finding, and what the validation
will cost.

## 1b. Two systems, one target (3 min)

The same `make scan` output carries the part no SAP tool produces,
just above the rule counts:

```
source systems:
  GEP    17 objects,  14 outstanding
  GVP     8 objects,   7 outstanding

convergence groups    : 4 (46.5 engineer-days avoided by building one object)
groups already built  : 2 (CG-MM-BATCHGEN, CG-MM-STOCK)
                        the saving on these is already taken
```

GSK Vaccines runs a separate ECC instance, and both land in one
S/4HANA client. So six functions exist twice - four of them still have
a choice to make, which is what the saving is priced on; the other two
have a core side that is already rebuilt, so the Vaccines object folds
into it and there is nothing left to save:

```bash
s4scan scan abap/ecc --format markdown --out /tmp/backlog.md
sed -n '/Convergence backlog/,/^## /p' /tmp/backlog.md
```

Batch release is the sharpest one. `ZGSK_QM_BATCH_RELEASE` and
`ZBIO_QM_LOT_RELEASE` do the same job, but the Vaccines version cannot
release a batch without an OCABR certificate from a national control
laboratory - a regulatory gate the core system has no concept of.
Rule `SI-CONV-001` fires on *both* objects, because the scanner has no
basis to nominate a survivor; that decision needs the business.

Why it is severity `critical` and sequenced before remediation:
remediating both in place is worse than doing nothing to them. You pay
twice, you validate twice, and you carry the duplication into the
target where removing it costs more.

And the two objects that simply go:

```bash
sed -n '/^## Decommissioned at merge/,/^## Remediated/p' /tmp/backlog.md
```

An intercompany interface moves antigen bulk from Vaccines to the core
as a sale, with an IDoc each way and a validated interface at both
ends. In one client that is an internal stock transport, and both
programs have no job. They leave the backlog but stay scanned - 19.6
engineer-days that were never really in the plan.

Talking point: this is the part of a consolidation that is currently
done by people who know one system but rarely both, one object at a
time, and it is what decides the target design.

## 2. What "done" looks like (3 min)

```bash
s4scan scan abap/remediated --fail-on minor && echo CLEAN
```

Compare `abap/ecc/gep/mm/zgsk_mm_stock_overview.prog.abap` with
`abap/remediated/`:

- MARD aggregate stock read replaced by `I_MaterialStock`;
- `SELECT SINGLE` inside the loop replaced by one set-based read;
- header lines, `MOVE`, `TABLES:` and CHAR18 gone;
- data access behind `zif_gsk_stock_source`, so
  `zcl_gsk_stock_overview.testclasses.abap` runs four ABAP Unit tests
  with no client dependency.

The definition of done is machine-checked, and CI enforces it. That is
what makes remediation at volume reviewable: the mechanical parts are
gated, so review attention goes to the business logic.

The inventory row for the object now names that successor in
`remediated_path`, which is what drops it out of the backlog and moves
its days into "cleared" - so the same command that sizes the programme
also reports its progress.

## 3. Give the work to an agent (5 min, live)

Pick an object from the top of the backlog and ask Devin for it, e.g.:

> Remediate `ZGSK_QM_BATCH_RELEASE` for S/4HANA following the pattern
> in `abap/remediated/`. Clear every finding the scanner reports,
> add an ABAP Unit test class, and open a PR.

`ZGSK_MM_BATCH_MOVEMENTS` is the worked example of exactly that
request: 11 findings cleared, MKPF/MSEG replaced by
`I_MaterialDocumentItem`, the nested `SELECT` collapsed into one
set-based read, eight ABAP Unit tests, and 16 engineer-days moved from
outstanding to cleared in `make scan`.

The loop closes on itself: the scanner defines the task, the remediated
reference defines the pattern, CI verifies both, and the PR is the
review record the validation package needs.

## 4. The data side (4 min)

```bash
make migrate
```

Wave 0, both ECC systems in one run: 151 records extracted, 26 held
back. Nothing is dropped silently - every reject carries a rule id, the
source key and what to do about it. The full list is
`reports/wave0/exceptions_*.csv`; run

```bash
cut -d, -f1,2 reports/wave0/exceptions_*.csv | grep reject | sort | uniq -c
```

for the tally. The ones worth reading out:

- a batch-managed vaccine with no shelf life, `DQ-MAT-006` (GMP data
  rule);
- two FI documents that do not balance, `DQ-FI-001` - one out by 10
  cents, one by 55,000;
- an open item for a customer that does not exist in the master,
  `DQ-FI-002`;
- batch stock for a material that is not batch managed, `DQ-STK-002`;
- batch stock in a unit the material master contradicts, `DQ-STK-005`;
- a customer with country code `XX`, `DQ-CUS-003`;
- a customer and a vendor with no name or country, `DQ-CUS-002` and
  `DQ-VEN-002`;
- a material with a gross weight but no weight unit, `DQ-MAT-004`;
- a Vaccines material whose harmonisation survivor was itself
  rejected, `DQ-MAT-010`, and the two batches held with it,
  `DQ-STK-006`;
- material number 100249 used by both systems for different products
  with no decision naming a survivor, `DQ-MAT-009` - both records are
  held, and the batch behind each is held with them, `DQ-STK-007`;
- stock for a material that never reached the master, `DQ-STK-001`.

The collision to point at first:

```bash
grep 0000210045 reports/wave0/s4_business_partner_xref.csv
```

Customer 210045 exists in both systems - NHS Supply Chain in the core,
Institut Pasteur de Dakar in Vaccines. Both were configured from the
same 1998 template, so the ranges are identical and the numbers mean
nothing across the estate. Every key in the pipeline is qualified with
its system for exactly this reason, and `DQ-CUS-008` reports the
collisions before cutover rather than after.

Then the conversion that always bites:

```bash
grep -E "GSK IRELAND|LONZA|UNICEF" reports/wave0/s4_business_partner.csv
```

GSK Ireland Manufacturing is customer 210059 and supplier 510017 - one
business partner with all four roles. Lonza AG is a supplier three
times over across the two systems - one BP, three company code
segments. UNICEF Supply Division is a customer in each system under a
different number - one BP, both numbers in the cross-reference. 43
accepted source records, 33 business partners.

Products merge the same way, but only where the business has said so:

```bash
cat data/wave0/material_harmonisation.csv
```

Deciding two materials are the same product has a regulatory
consequence, so it is a governed input, not a description match. One
of those decisions does not go through - the surviving core product is
itself rejected for a missing weight unit, so `DQ-MAT-010` holds the
retired Vaccines record back rather than loading it under its own
number and quietly splitting the product's stock in two.

```bash
cat reports/wave0/reconciliation.md
```

37 checks, all passing: counts, value totals per company code and
currency, debit/credit balance, quantity totals per plant, BP
arithmetic, and the merge arithmetic (`REC-MRG-*`). That last group
matters here - with two sources loading into one client, a smaller
target count is both the intended outcome and exactly what data loss
looks like, so the difference has to be accounted for record by record.
This is the evidence pack that goes on the cutover log.

Talking point for a data and analytics audience: the migration is the
once-a-decade chance to make the core data decision-ready. The
cleansing rules are where that happens, and they are code - reviewed,
tested, re-runnable per wave, and improvable each time the wave repeats.

## 5. The gate (1 min)

```bash
make check
```

ruff, the test suite, and the readiness gate. CI additionally fails if the
committed reports in `reports/` are stale, so the measurement can never
drift from the code.
