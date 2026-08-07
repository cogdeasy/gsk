# ERP Evolution - programme context

Context for anyone working in this repository. Sourced from the meeting
brief in `docs/brief-manish-varma.md`; items that are inference rather
than confirmed fact are marked as such there and here.

## The estate being migrated

- A single global SAP ECC 6.0 core, reached through a decade of "ERP
  unification" wave deployments across the 2010s.
- Nominally unified, actually highly variant: process mining surfaced
  roughly 28,000 variants of a single sales-order process. The variant
  count is the real migration problem, and it is visible in this
  repository as the market-by-market accretion in
  `abap/src/exits/zxvedu01_sales_order.exit.abap`.
- Large operational footprint on that one core: ~37 manufacturing
  sites, operations in 75+ countries, manufacturing, supply chain,
  finance, procurement (Ariba), intercompany profit tracking, and label
  printing at 3,500+ printers through Loftware.
- GxP-regulated throughout. The ERP is a validated system; every change
  needs computer system validation. This is the single biggest cost
  multiplier compared with a non-pharma migration, and it is why the
  scanner carries a validation multiplier per object rather than
  costing every object the same.
- ECC 6.0 mainstream maintenance ends in 2027 (extended support to
  2030). That is the forcing function.

## The programme

GSK is mid-flight, not deciding. "ERP Evolution" (also referenced as
"ERP Together") is deploying S/4HANA globally in waves across Pharma
and Vaccines - commercial markets, manufacturing sites, R&D, shared
financial services, plus customers, suppliers and logistics partners. A
"Wave 0" covers a representative subset first. Programme secondments
run to end-2027.

Target (from public staff profiles, therefore inference): S/4HANA on
RISE with SAP, currently in Realization after Blueprint and Confirm -
sizing, application architecture and integration planning done; build,
test, data migration and wave cutovers in progress.

The wave column in `estate/inventory.csv` follows that shape: `wave0`
is the representative subset, `wave1` and `wave2` follow.

## Workstreams

| Workstream | Character | Modelled here |
| --- | --- | --- |
| Custom code remediation | Tens of thousands of objects, pattern heavy | Yes - `tools/s4scan`, `abap/` |
| Process standardisation | Fit-gap and template governance per market | No - business-led |
| Data migration and master data cleansing | Per wave, repeated, reconciliation heavy | Yes - `tools/datamig`, `data/` |
| Interface re-pointing | Hundreds of integrations, re-tested per wave | Partly - `abap/src/if/` |
| GxP validation and testing | Typically 30-40% of programme effort in pharma | Yes - `docs/VALIDATION.md`, rule `SI-GXP-001` |
| Cutover and hypercare per wave | Rehearsed, reconciled, repeated | Partly - reconciliation evidence |
| Change management and training | People-led | No |

## Where AI-assisted engineering fits

The labour-intensive, pattern-heavy middle: triaging simplification-item
hits and mechanically remediating deprecated patterns as reviewable
PRs; generating and maintaining regression suites and validation
documentation drafts per wave; writing and iterating extraction,
cleansing and mapping pipelines with reconciliation evidence; and the
repetitive re-pointing and re-testing of interfaces per wave.

This repository is the concrete version of that argument: the estate,
the measurement, the target pattern, and the evidence trail - all of it
executable rather than described.
