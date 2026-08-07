*&---------------------------------------------------------------------*
*& Report  ZGSK_MM_BATCH_MOVEMENTS  (S/4HANA remediated)
*&---------------------------------------------------------------------*
*& Batch genealogy / material movement extract. Feeds the serialization
*& and track-and-trace reconciliation and the GMP batch record archive.
*&
*& Remediation of the ECC report of the same name, following the target
*& pattern in this package. Cleared findings:
*&
*&   SI-MM-002  MKPF / MSEG replaced by I_MaterialDocumentItem (MATDOC).
*&   SI-MM-003  CHAR18 material typing replaced by TYPE matnr.
*&   SI-TECH-003 header lines and TABLES work areas removed.
*&   SI-TECH-004 the per-document SELECT inside LOOP AT gt_head is now
*&               one set based read; the header fields the loop copied
*&               (posting date, entry user) are on the item view.
*&   SI-TECH-005 explicit field list instead of SELECT *.
*&   SI-TECH-002 WS_DOWNLOAD replaced by cl_gui_frontend_services; the
*&               background path writes to the application server so the
*&               archive job no longer needs a presentation session.
*&   SI-GXP-001  ABAP Unit tests in
*&               zcl_gsk_batch_movements.testclasses.abap.
*&
*& The line level extract is behaviour preserving. One addition: a
*& batch balance derived from the debit/credit indicator, so the
*& serialization reconciliation no longer has to recompute it from its
*& own staging table. Receipts and issues come from the indicator
*& rather than from a movement type list, which means plant specific Z
*& movement types are included. Flagged for validation package impact.
*&
*& Object owner : GSC Manufacturing IT
*& GxP class    : GxP-critical (batch traceability evidence)
*& Validation   : GMP-BRE-007
*& Remediation  : Wave 0
*&---------------------------------------------------------------------*
REPORT zgsk_mm_batch_movements.

SELECTION-SCREEN BEGIN OF BLOCK b1 WITH FRAME TITLE TEXT-001.
SELECT-OPTIONS:
  s_budat FOR zcl_gsk_batch_movements=>ty_sel-posting_date OBLIGATORY,
  s_werks FOR zcl_gsk_batch_movements=>ty_sel-plant OBLIGATORY,
  s_charg FOR zcl_gsk_batch_movements=>ty_sel-batch,
  s_bwart FOR zcl_gsk_batch_movements=>ty_sel-movement.
PARAMETERS: p_bonly AS CHECKBOX DEFAULT abap_true.
SELECTION-SCREEN END OF BLOCK b1.

SELECTION-SCREEN BEGIN OF BLOCK b2 WITH FRAME TITLE TEXT-002.
PARAMETERS: p_file TYPE string LOWER CASE.
SELECTION-SCREEN END OF BLOCK b2.

START-OF-SELECTION.

  DATA(lo_extract) = NEW zcl_gsk_batch_movements( ).

  TRY.
      DATA(lt_movement) = lo_extract->read_movements(
        it_posting_date  = s_budat[]
        it_plant         = s_werks[]
        it_batch         = s_charg[]
        it_movement_type = s_bwart[]
        iv_batches_only  = p_bonly ).

      DATA(lt_total) = lo_extract->summarise_by_batch( lt_movement ).

      lo_extract->display( it_movement = lt_movement
                           it_total    = lt_total ).

      IF p_file IS NOT INITIAL.
        NEW zcl_gsk_movement_export( )->write( it_movement = lt_movement
                                               iv_path     = p_file ).
      ENDIF.

    CATCH zcx_gsk_movement_error INTO DATA(lx_error).
      MESSAGE lx_error TYPE 'E'.
  ENDTRY.
