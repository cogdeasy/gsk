# ERP Evolution - programme context

Context for anyone working in this repository. Sourced from the meeting
brief in `docs/brief-manish-varma.md`; items that are inference rather
than confirmed fact are marked as such there and here.

## The estate being migrated

Two SAP ECC 6.0 production systems, not one:

| System | Scope | Modelled in |
| --- | --- | --- |
| **GEP** | The GSK core. Pharma and consumer, reached through a decade of "ERP unification" wave deployments across the 2010s. | `abap/ecc/gep`, `data/wave0/gep` |
| **GVP** | GSK Vaccines. A separate instance with its own client, its own number ranges and its own development history. | `abap/ecc/gvp`, `data/wave0/gvp` |

Both are in scope, and both land in **one** S/4HANA client. That makes
this a consolidation as well as a conversion, and the consolidation is
the part with no SAP tool to run: see `docs/CONVERGENCE.md`.

- Nominally unified, actually highly variant: process mining surfaced
  roughly 28,000 variants of a single sales-order process. The variant
  count is the real migration problem, and it is visible in this
  repository as the market-by-market accretion in
  `abap/ecc/gep/exits/zxvedu01_sales_order.exit.abap`.
- Large operational footprint: ~37 manufacturing sites, operations in
  75+ countries, manufacturing, supply chain, finance, procurement
  (Ariba), intercompany profit tracking, and label printing at 3,500+
  printers through Loftware. Vaccines adds antigen bulk campaigns,
  cold-chain and ultra-cold storage, OCABR batch certification and
  serialisation obligations that the core system has no equivalent of.
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
| Custom code convergence | Duplicated objects across the two systems, resolved to one target design | Yes - `SI-CONV-001`, `docs/CONVERGENCE.md` |
| Process standardisation | Fit-gap and template governance per market | No - business-led |
| Data migration and master data cleansing | Per wave, repeated, reconciliation heavy | Yes - `tools/datamig`, `data/` |
| Cross-system master data harmonisation | Same counterparty and product mastered twice, merged once | Yes - `REC-MRG-*`, `data/wave0/material_harmonisation.csv` |
| Interface re-pointing | Hundreds of integrations, re-tested per wave | Partly - `abap/ecc/*/if/` |
| Interface decommissioning | Integrations that exist only because the systems are separate | Yes - `disposition=decommission` in the inventory |
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

The consolidation adds a second kind: reading two implementations of
the same function side by side and stating precisely where they differ.
That is the work that decides the target design, it is currently done
by hand by people who know one system but rarely both, and it is
exactly the kind of comparison that does not get cheaper with more
people.

This repository is the concrete version of that argument: the estate,
the measurement, the target pattern, and the evidence trail - all of it
executable rather than described.
