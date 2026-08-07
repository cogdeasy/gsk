# Clean core - target patterns

What "remediated" means in this repository, rule by rule. The worked
example is `abap/remediated/`: the same stock overview report as
`abap/src/mm/zgsk_mm_stock_overview.prog.abap`, rebuilt.

## Principles

1. **Released APIs only.** Read through released CDS views and public
   APIs. If an object needs something not released, that is a gap to
   raise in fit-gap, not a reason to read the underlying table.
2. **No compatibility-view dependency for new code.** Compatibility
   views exist to keep the lights on during cutover; remediated code
   targets the real model.
3. **Extensions outside the core.** Anything that is genuinely bespoke
   goes to a side-by-side extension on BTP or a key-user extension, not
   into a modification of the delivered process.
4. **Testable by construction.** Data access sits behind an interface
   so ABAP Unit can substitute a double. Without that, there is no
   automated test evidence, and without automated test evidence the
   validation burden stays manual.
5. **Set-based, not row-based.** No SELECT inside LOOP. HANA rewards
   pushdown and punishes nested reads, and the wave cutover batch
   windows are fixed.

## Data model moves

| ECC | S/4HANA | Rule |
| --- | --- | --- |
| MARD, MCHB, MSKA, MSKU, MSLB, MSSA, MSSQ | `I_MaterialStock` / NSDM views over MATDOC | SI-MM-001 |
| MKPF, MSEG | MATDOC via `I_MaterialDocumentItem` | SI-MM-002 |
| MATNR as CHAR18 | `matnr`, 40 characters | SI-MM-003 |
| BSIS, BSAS, BSID, BSAD, BSIK, BSAK, GLT0, FAGLFLEX* | ACDOCA via `I_JournalEntryItem` | SI-FI-001 |
| BSEG, BKPF for reporting | ACDOCA | SI-FI-002 |
| COSP, COSS, COEP, COBK | ACDOCA | SI-CO-001 |
| VBUK, VBUP | status fields on VBAK/VBAP | SI-SD-001 |
| KNKK, KNKA, S066, S067 | SAP Credit Management (UKM) | SI-SD-002 |
| KNA1, KNB1, LFA1, LFB1 writes | Business Partner / CVI | SI-MD-001 |
| MDKP, MDTB | MRP Live result views | SI-PP-001 |
| NAST, RSNAST00 | BRF+ output management | SI-OM-001 |
| MCHA, MCH1 | `I_Batch` | SI-QM-001 |

## Language moves

| Legacy | Replacement | Rule |
| --- | --- | --- |
| `EXEC SQL` | Open SQL or AMDP | SI-TECH-001 |
| `WS_UPLOAD` / `WS_DOWNLOAD` / `UPLOAD` / `DOWNLOAD` | `cl_gui_frontend_services`, or a server-side path for background jobs | SI-TECH-002 |
| `WITH HEADER LINE`, `OCCURS n`, `MOVE ... TO`, `TABLES:` | inline declarations, explicit work areas | SI-TECH-003 |
| SELECT inside LOOP | join or `FOR ALL ENTRIES` | SI-TECH-004 |
| `SELECT *` | explicit field list | SI-TECH-005 |
| `CLIENT SPECIFIED` | remove; automatic client handling | SI-TECH-006 |
| `COMMIT WORK` per iteration | bounded commit block with restart | SI-TECH-007 |

## The worked example

`zgsk_mm_stock_overview` before: `TABLES:` declarations, three internal
tables with header lines, `SELECT * FROM t001w`, a read of MARD's
aggregate stock fields, a `SELECT SINGLE` per material inside the loop,
`MOVE` statements, and MATNR typed as CHAR18. 20 findings, 4 of them
blockers.

After (`abap/remediated/`):

- the report is a thin shell over `zcl_gsk_stock_overview`;
- stock comes from `I_MaterialStock`, aggregated in the database when
  batches are not requested;
- the data source sits behind `zif_gsk_stock_source`, so
  `zcl_gsk_stock_overview.testclasses.abap` runs four ABAP Unit tests
  against fixture data with no client dependency;
- zero findings - `s4scan scan abap/remediated --fail-on minor` passes,
  and CI keeps it that way.

That last point is the important one: the definition of done is
machine-checked, so remediation at volume does not depend on reviewer
vigilance for the mechanical parts.
