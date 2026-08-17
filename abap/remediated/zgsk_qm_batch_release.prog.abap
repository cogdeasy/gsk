*&---------------------------------------------------------------------*
*& Report  ZGSK_QM_BATCH_RELEASE  (S/4HANA remediated)
*&---------------------------------------------------------------------*
*& Qualified Person batch release worklist. Lists batches with their
*& inspection lot usage decision and holds back any batch whose
*& certificate of analysis has not been released.
*&
*& Remediation of the ECC report of the same name, following the target
*& pattern in this package. Cleared findings:
*&
*&   SI-QM-001   MCHA and MCH1 replaced by the released view I_Batch;
*&               the identifying plant on that view is initial for
*&               batches held at material level, so the cross plant
*&               batches the ECC report appended from MCH1 arrive in
*&               the same read.
*&   SI-MM-003   CHAR18 material typing replaced by TYPE matnr.
*&   SI-TECH-001 the native SQL count over ZGSK_COA_STAGING is now one
*&               grouped Open SQL read; the staging table is a custom
*&               table and survives the conversion unchanged.
*&   SI-TECH-003 header lines and TABLES work areas removed.
*&   SI-TECH-004 the per-batch reads of QALS and QAVE inside LOOP AT
*&               gt_rel, and the per-batch certificate count, are three
*&               set based reads; the usage decision attributes are on
*&               I_InspectionLot.
*&   SI-GXP-001  ABAP Unit tests in
*&               zgsk_qm_batch_release.testclasses.abap.
*&
*& One behavioural change, flagged for the validation package: where a
*& batch carries more than one inspection lot the ECC report reported
*& whichever lot the database returned first. The worklist now reports
*& the most recent usage decision, so the same batch gives the same
*& answer on every run.
*&
*& Object owner : Global Quality IT
*& GxP class    : GxP-critical (Annex 16 batch certification support)
*& Validation   : QMS-014
*& Remediation  : Wave 0
*&---------------------------------------------------------------------*
REPORT zgsk_qm_batch_release.

SELECTION-SCREEN BEGIN OF BLOCK b1 WITH FRAME TITLE TEXT-001.
SELECT-OPTIONS:
  s_werks FOR zcl_gsk_batch_release=>ty_sel-plant OBLIGATORY,
  s_matnr FOR zcl_gsk_batch_release=>ty_sel-material,
  s_vfdat FOR zcl_gsk_batch_release=>ty_sel-expiry_date.
PARAMETERS: p_nocoa AS CHECKBOX.
SELECTION-SCREEN END OF BLOCK b1.

START-OF-SELECTION.

  DATA(lo_worklist) = NEW zcl_gsk_batch_release( ).

  TRY.
      DATA(lt_release) = lo_worklist->read_worklist(
        it_plant       = s_werks[]
        it_material    = s_matnr[]
        it_expiry_date = s_vfdat[]
        iv_missing_coa = p_nocoa ).

      lo_worklist->display( lt_release ).

    CATCH zcx_gsk_release_error INTO DATA(lx_error).
      MESSAGE lx_error TYPE 'E'.
  ENDTRY.
