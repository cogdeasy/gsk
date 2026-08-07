# Wave 0 plan

The first-phase plan for the S/4HANA migration as this repository models
it: what is in scope for wave 0, what "done" means per object, the order
the work is taken in, and the gates it has to pass. Numbers here are the
committed ones in `reports/`; regenerate the reports rather than editing
figures by hand.

## Forcing function

ECC 6.0 mainstream maintenance ends in 2027, with extended support to
2030 (`docs/PROGRAMME.md`). The programme is mid-flight, not deciding,
and deploys S/4HANA in waves. Wave 0 is the representative subset that
goes first: it proves the patterns, the tooling and the evidence trail
before `wave1` and `wave2` repeat them at volume. The `wave` column in
`estate/inventory.csv` follows that shape.

Wave 0 therefore succeeds on two counts. The objects and data have to
land, and the way they landed has to be repeatable - a target pattern
other engineers copy, a scanner that sizes and orders the remaining
work, and a reconciliation pack that can be produced again next wave
without renegotiating what evidence means.

## Scope

The three workstreams this repository models (`README.md`), scoped to
wave 0:

| Workstream | Wave 0 scope | Source |
| --- | --- | --- |
| Custom code remediation | 7 outstanding objects, 89 findings, 97.7 engineer-days | `reports/remediation-backlog.md` (findings by wave) |
| Data migration engineering | 5 objects - materials, customers, vendors, open items, batch stock; 96 records extracted, 82 loaded, 14 held back | `reports/wave0/reconciliation.md` |
| Test and validation evidence | 9 GxP-classified objects estate-wide, of which 7 still lack ABAP Unit test evidence under rule `SI-GXP-001` - 6 of those are wave 0 | `docs/VALIDATION.md`, `reports/remediation-backlog.md` (findings by rule) |

Two wave 0 objects are already done and are the reference pattern rather
than backlog: `ZGSK_MM_STOCK_OVERVIEW` (20 findings cleared) and
`ZGSK_MM_BATCH_MOVEMENTS` (11 cleared). Their ECC sources stay in
`abap/src` as the before/after pair the validation package needs.

## Definition of done

Per `docs/VALIDATION.md`, a remediated object is done when all four
artefacts exist:

1. **Specification delta** - what changed and why, traceable to a
   simplification item. The scanner finding is the trace: it names the
   rule, the line and the target pattern.
2. **Automated test evidence** - an ABAP Unit test class named
   `<object>.testclasses.abap`, running against a test double rather
   than client data. Rule `SI-GXP-001` fails any GxP object without one.
3. **Review record** - the pull request. One remediated object per PR,
   reviewed by the owner named in `estate/inventory.csv`.
4. **Regression run** - the object's tests green in CI on the wave
   branch, plus the wave regression suite.

The mechanical half of that is machine-checked. `abap/remediated/` is
the reference pattern - released CDS views and APIs, set-based selects,
no header lines or `OCCURS`, data access behind an interface so ABAP
Unit can substitute a test double - and it scans clean:

```bash
s4scan scan abap/remediated --fail-on minor
```

Every object in the wave 0 backlog is expected to reach that same
standard, which is what makes remediation at volume reviewable: review
attention goes to the business logic because the patterns are gated.

## Wave 0 backlog tracker

The order is the scanner's: wave, then severity, then business exposure
(monthly executions and business criticality from the inventory).
Engineer-days include the GxP validation multiplier. Rows reproduce the
prioritised backlog in `reports/remediation-backlog.md`; the status
column is maintained here.

| # | Object | GxP class | Owner | Blockers | Engineer-days | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | ZGSK_QM_BATCH_RELEASE | gxp_critical | Global Quality IT | 2 | 17.6 | Not started |
| 2 | ZGSK_MM_SERIALISATION_RECON | gxp_critical | GSC Serialisation Programme | 5 | 18.4 | Not started |
| 3 | ZGSK_MD_CUSTOMER_SYNC | gxp_relevant | Enterprise Data & Analytics | 4 | 17.6 | Not started |
| 4 | ZGSK_FI_ICT_MARGIN | non_gxp | Global Financial Services | 4 | 8.7 | Not started |
| 5 | ZGSK_IF_LABEL_PRINT | gxp_critical | GSC Manufacturing IT | 0 | 18.9 | Not started |
| 6 | ZGSK_IF_MES_CONFIRMATION | gxp_critical | GSC Manufacturing IT | 0 | 8.3 | Not started |
| 7 | ZGSK_COMMON_UTILS | gxp_relevant | ERP Competency Centre | 0 | 8.2 | Not started |

One deviation from the computed order is worth planning for:
`ZGSK_COMMON_UTILS` ranks last because it is an `INCL` with no
executions of its own, but it is shared, so remediating it early
de-risks every dependent object rather than forcing the same fix twice.

## Effort and validation budgeting

Raw remediation effort is inflated per object by the GxP multiplier held
in the inventory (`docs/VALIDATION.md`):

| Class | Multiplier |
| --- | --- |
| `gxp_critical` | 2.0 |
| `gxp_relevant` | 1.5 |
| `non_gxp` | 1.0 |

The overhead is reported as a separate number rather than buried in the
estimate, so the plan can be read as engineering days plus validation
days. Across the outstanding estate that is 152 engineer-days, of which
45 is GxP validation overhead (`README.md`; 151.8 and 44.6 before
rounding in `reports/remediation-backlog.md`), against 32 engineer-days
already cleared. Wave 0 carries 97.7 of the outstanding days, and the
concentration of `gxp_critical` objects at the top of the tracker is
exactly where the multiplier bites.

## Data migration slice

Wave 0 runs end to end from committed extracts:

```bash
make migrate                                  # -> out/wave0
datamig run --wave wave0 --fail-on-reject     # cutover gate
```

The acceptance target is `reports/wave0/reconciliation.md` passing all
22 checks - record counts per object, value totals per company code and
currency, debit/credit balance, quantity totals per plant, and the
business partner arithmetic (28 source records, 25 business partners,
3 merged) - with every reject named.

The held-back records are the data cleansing worklist, not a pipeline
defect. Each is caught by a named data quality rule and itemised in the
exception files:

| Object | Held back | Reason |
| --- | --- | --- |
| materials | 2 | batch managed material without total shelf life (GMP); gross weight without a weight unit |
| customers | 1 | country code `XX` is not a valid ISO country |
| vendors | 1 | name or country missing, so no business partner can be created |
| open_items | 4 | one document out of balance by 10 cents; one document for a partner that is not in the migrated master |
| batch_stock | 6 | stock for materials not in the migrated master; batch stock for materials that are not batch managed; stock in a unit the material master contradicts |

Open warnings are allowed but must be explained in the cutover log; for
wave 0 those are stock in quality inspection at cutover, needing a usage
decision before go-live, and suppliers without a GMP audit flag.

## Gate and exit criteria

```bash
make scan     # baseline and progress against the estate
make check    # ruff + pytest + the readiness gate
```

- `make scan` is how progress is reported: an object leaves the backlog
  when its inventory row names its successor in `remediated_path`, and
  its days move from outstanding to cleared.
- `make check` is the exit criterion for every change and must pass
  before any PR.
- The reports in `reports/` are committed and CI fails if a code change
  leaves them stale - regenerate with `make reports` so the measurement
  cannot drift from the code.
- Remediated ABAP must scan clean at `--fail-on minor`.

Wave 0 is complete when the tracker above is all `Done`, the six
outstanding wave 0 GxP objects have ABAP Unit evidence, and the
reconciliation report
regenerates with 22 of 22 checks passing.

## Where to begin

`ZGSK_QM_BATCH_RELEASE` - top of the tracker, `gxp_critical`, owned by
Global Quality IT, 4,100 executions a month, validation package QMS-014.

1. `s4scan scan abap/src --wave wave0` and read the object detail
   section of `reports/remediation-backlog.md` for its findings.
2. Rebuild it following `abap/remediated/`, clearing every finding -
   including the native SQL blocker `SI-TECH-001`, which has no
   equivalent in a clean-core implementation.
3. Add `zcl_gsk_qm_batch_release.testclasses.abap` over a test double
   for the data access layer.
4. Point the inventory row's `remediated_path` at the successor and
   regenerate the reports.
5. Open a PR - one object, reviewed by the inventory owner.
