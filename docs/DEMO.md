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

16 custom objects, 173 findings outstanding, 27 of them blockers, plus
what has already been cleared. Then the point that matters - it is not
a flat list:

```bash
s4scan scan abap/src --format markdown --out /tmp/backlog.md
head -60 /tmp/backlog.md
```

The backlog is ordered by wave, then severity, then business exposure
(monthly execution volume and business criticality from
`estate/inventory.csv`). Effort is sized per object and inflated by the
GxP validation multiplier, so the plan separates 107 days of
engineering from 45 days of validation overhead.

Talking point: an SAP readiness check tells you which simplification
items you hit. This tells you which objects to do first, who owns them,
what the target pattern is for each finding, and what the validation
will cost.

## 2. What "done" looks like (3 min)

```bash
s4scan scan abap/remediated --fail-on minor && echo CLEAN
```

Compare `abap/src/mm/zgsk_mm_stock_overview.prog.abap` with
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

Wave 0: 96 records extracted, 13 held back, business partners created.
Every reject is named:

- a batch-managed vaccine with no shelf life (GMP data rule);
- an FI document out of balance by 10 cents;
- an open item for a customer that does not exist in the master;
- batch stock for a material that is not batch managed;
- batch stock in a unit the material master contradicts;
- a customer with country code `XX`.

Then the conversion that always bites:

```bash
grep -E "GSK IRELAND|LONZA" reports/wave0/s4_business_partner.csv
```

GSK Ireland Manufacturing is customer 210059 and supplier 510017 - one
business partner with all four roles. Lonza AG exists twice under two
company codes - one BP, two company code segments. 28 source records,
25 business partners, and the reconciliation proves the arithmetic.

```bash
cat reports/wave0/reconciliation.md
```

22 checks, all passing: counts, value totals per company code and
currency, debit/credit balance, quantity totals per plant, BP
arithmetic. This is the evidence pack that goes on the cutover log.

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
