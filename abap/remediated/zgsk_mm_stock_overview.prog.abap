*&---------------------------------------------------------------------*
*& Report  ZGSK_MM_STOCK_OVERVIEW  (S/4HANA remediated reference)
*&---------------------------------------------------------------------*
*& Reference remediation of the ECC report of the same name. This is
*& the target pattern for the ERP Evolution custom code workstream:
*&
*&   1. No direct read of MARD / MARC / MCHB aggregate stock fields.
*&      Stock is read from the released CDS view I_MaterialStock, which
*&      is backed by MATDOC on S/4HANA.
*&   2. Released APIs only - no access to tables flagged by the
*&      simplification scanner as removed or restricted.
*&   3. Set based selection - no SELECT inside LOOP.
*&   4. Modern ABAP - no header lines, no OCCURS, no MOVE, inline
*&      declarations, string templates.
*&   5. Separated concerns - selection logic sits in a testable class
*&      so ABAP Unit tests can supply a test double for the data
*&      access layer (required for the GxP test evidence package).
*&
*& Object owner : GSC Supply Chain IT
*& GxP class    : GxP-relevant (indirect - reporting only)
*& Remediation  : Wave 0, simplification items SI-MM-001, SI-TECH-003
*&---------------------------------------------------------------------*
REPORT zgsk_mm_stock_overview.

SELECTION-SCREEN BEGIN OF BLOCK b1 WITH FRAME TITLE TEXT-001.
SELECT-OPTIONS: s_werks FOR zcl_gsk_stock_overview=>ty_sel-plant OBLIGATORY,
                s_matnr FOR zcl_gsk_stock_overview=>ty_sel-material,
                s_lgort FOR zcl_gsk_stock_overview=>ty_sel-storage_location.
PARAMETERS: p_batch AS CHECKBOX DEFAULT abap_true,
            p_zero  AS CHECKBOX.
SELECTION-SCREEN END OF BLOCK b1.

START-OF-SELECTION.

  DATA(lo_report) = NEW zcl_gsk_stock_overview( ).

  TRY.
      DATA(lt_stock) = lo_report->read_stock(
        it_plant            = s_werks[]
        it_material         = s_matnr[]
        it_storage_location = s_lgort[]
        iv_with_batches     = p_batch
        iv_include_zero     = p_zero ).

      lo_report->display( lt_stock ).

    CATCH zcx_gsk_stock_error INTO DATA(lx_error).
      MESSAGE lx_error TYPE 'E'.
  ENDTRY.
