# GSK: Manish Varma, the SAP estate, and the S/4HANA migration

Background brief that this repository was built against. Items marked
as inference are reasoned from public evidence, not confirmed by GSK.

## Manish Varma: role and background

Global Vice President & Enterprise Head of Data & Analytics at GSK,
based in Philadelphia, in post since January 2022. His LinkedIn
headline frames ERP modernization as part of his mandate: "Global
Technology & AI Executive | CIO | CDTO | Driving Enterprise Growth
through AI Innovation, Data Foundation & ERP Modernization." He owns
the enterprise data foundation that an ERP migration both depends on
and feeds.

Career is ERP- and pharma-native: Pharma ERP Data Warehouse Architect
at Bristol-Myers Squibb (1999-2001); ~15 years at Johnson & Johnson
rising to VP of IT (one of the largest global SAP estates in life
sciences); Chief Strategy Officer at ArisGlobal (drug-safety SaaS);
CEO of Mareana (AI/data for pharma manufacturing and supply-chain
intelligence - extracting value from exactly the data locked in ERP and
MES). Wharton MBA, IIT Kanpur engineering.

His public writing emphasises that enterprise AI advantage comes from
proprietary data and operating context, that "data is capital; if it
isn't trusted and decision-ready, AI will fail," and that AI only
creates value when it changes how work gets done. Expect him to
evaluate migration tooling through that lens.

*Inference:* he is unlikely to own day-to-day S/4HANA programme
delivery (that sits with GSK Tech programme leadership under CDTO
Shobie Ramakrishnan), but as enterprise head of Data & Analytics he
owns the data foundation the migration must not break - master data,
analytics continuity, and the AI agenda layered on top. Strong internal
champion candidate for AI-assisted engineering on the programme.

## GSK's likely SAP set-up today

- **A single global SAP ECC 6.0 core.** A decade-long "ERP unification"
  onto SAP ECC worldwide, completed through wave deployments across the
  2010s. By 2021 the global ERP competency centre described a unified
  ECC instance - but process mining (Celonis) revealed ~28,000 process
  variants for a single sales-order process: a nominally unified system
  with enormous embedded process and custom-code complexity.
- **Massive operational footprint.** ~37 manufacturing sites, 1.7bn
  packs of medicines and ~409m vaccine doses shipped in 2024,
  operations across 75+ countries, with ECC driving manufacturing,
  supply chain, finance, procurement (Ariba), intercompany profit
  tracking (ICT), and label printing at 3,500+ printers via Loftware.
- **Heavily GxP-regulated.** The ERP is a validated system under pharma
  GMP rules - every change requires computer-system validation, the
  single biggest cost multiplier versus a non-pharma migration.
- **Deadline pressure.** Mainstream maintenance for ECC 6.0 ends in
  2027 (extended support to 2030).

*Inference on surroundings:* SAP BW/analytics feeding the enterprise
data platform Manish owns, Ariba for procurement, a large bespoke ABAP
layer (28k variants imply years of Z-code accretion), and hundreds of
interfaces to MES, LIMS, serialization/track-and-trace, and logistics
partners.

## The migration already underway: ERP Evolution

GSK is mid-flight. "ERP Evolution" (also referenced internally as "ERP
Together") is deploying S/4HANA globally in waves across Pharma and
Vaccines: commercial markets, manufacturing sites, R&D, shared
financial services, plus customers, suppliers and logistics partners. A
"Wave 0" covers a representative subset first; programme secondments
run to end-2027.

Public staff profiles indicate the target is S/4HANA on RISE with SAP
(SAP-managed cloud), and that the programme has completed Blueprint and
Confirm phases and is currently in Realization - system sizing,
application architecture, integration planning done; build, test, data
migration and wave cutovers now in progress. GSK is hiring ERP Process
Directors (Logistics, Planning), PMO/cutover leads, integration leads
and data SMEs on fixed terms to December 2027 - a classic multi-year,
multi-wave brownfield-plus-redesign programme.

## What the migration entails

- **Custom code remediation.** Years of custom ABAP (Z-programs, user
  exits, enhancements) inventoried, assessed against S/4
  simplifications (new data model: MATDOC, ACDOCA, business partner
  mandate), then retired, remediated, or rebuilt as clean-core
  extensions on BTP. At GSK's scale, tens of thousands of objects.
- **Process standardisation.** The 28,000 sales-order variants are the
  real migration problem: each wave forces a decision to adopt the
  global template or justify a deviation.
- **Data migration & master data cleansing.** Material masters, BOMs,
  recipes, vendors/customers (business-partner conversion), open items,
  batch/serialization data - extracted, cleansed, mapped and loaded per
  wave, with reconciliation evidence. Squarely Manish's territory: the
  once-a-decade chance to make core data decision-ready.
- **Interface re-pointing.** Hundreds of integrations (MES, LIMS,
  Loftware labeling, Ariba, banks, 3PLs, EDI) re-built or re-tested per
  wave.
- **GxP validation & testing.** Every remediated object, interface and
  process needs documented test evidence; regression suites per wave
  and per release. Typically 30-40% of programme effort in pharma.
- **Cutover & hypercare per wave.** Rehearsed cutovers, stock/finance
  reconciliation, hypercare, then the next wave - across ~37 sites and
  dozens of markets through 2027+.
- **Change management & training** for tens of thousands of users.

## Where Cognition fits

The labour-intensive, pattern-heavy middle of the programme:

- **ABAP custom-code analysis and remediation at scale** - triaging
  simplification-item hits, mechanically remediating deprecated
  patterns, migrating to clean-core/BTP extensions, each change a
  reviewable PR.
- **Test asset generation** - automated regression suites and
  validation documentation drafts per wave, cutting the GxP testing
  burden.
- **Data migration engineering** - extraction/cleansing/mapping
  pipelines and reconciliation reports; directly supports the "trusted,
  decision-ready data" agenda.
- **Interface remediation** - repetitive re-pointing and re-testing of
  hundreds of integrations per wave.

Proof point for a GxP audience: Evinova (AstraZeneca group, 21 CFR Part
11 environment) uses Devin in production - 8x faster GxP documentation,
3x faster code migrations, 66% of bugs fixed autonomously in the first
10 days, and test automation compressed from quarters to weeks.

Framing for Manish specifically: less "we can help run your SAP
programme" (owned elsewhere in GSK Tech), more "AI software agents can
compress the engineering long-tail of ERP Evolution - code remediation,
test generation, data pipelines - while raising the quality of the data
foundation your AI strategy depends on."

## Sources

1. LinkedIn - Manish Varma (linkedin.com/in/mvarma): role, headline,
   career history.
2. Manish Varma, LinkedIn posts (Dec 2025) on enterprise AI value and
   data as capital.
3. The Register (Apr 2021), "GSK opens Pandora's Box of its SAP system
   to find 28,000 variations on a process".
4. GSK job postings (ERP Process Director - Logistics/Planning; GSC ERP
   PMO/Cutover Lead; ICT Deployment SME); Loftware GSK webinar (2024);
   The Resolution Engine GSK case study.
5. SAP ECC 6.0 mainstream maintenance timeline; excelerateds2p, "SAP
   ECC6 to S/4HANA Migration at GSK."
6. GSK "ERP Evolution Program" job descriptions (Built In, Dec 2025-Mar
   2026).
7. LinkedIn - GSK staff profiles (S/4HANA RISE, Realization phase;
   Senior Director S/4HANA ERP Deployment Delivery Lead; Integration
   Lead "ERP Together").
8. Devin customer case study - Evinova (AstraZeneca group),
   devin.ai/customers/evinova (July 2026).
