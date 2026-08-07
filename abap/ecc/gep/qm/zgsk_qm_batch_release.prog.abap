*&---------------------------------------------------------------------*
*& Report  ZGSK_QM_BATCH_RELEASE
*&---------------------------------------------------------------------*
*& Qualified Person (QP) batch release worklist. Lists batches in
*& quality inspection with their inspection lot usage decisions and
*& blocks release where the certificate of analysis is missing.
*&
*& Object owner : Global Quality IT
*& GxP class    : GxP-critical (Annex 16 batch certification support)
*& Validation   : CSV package QMS-014, last requalified 2021
*&---------------------------------------------------------------------*
REPORT zgsk_qm_batch_release.

TABLES: mcha, mch1, qals, qave.

TYPES: BEGIN OF ty_release,
         matnr TYPE char18,
         charg TYPE charg_d,
         werks TYPE werks_d,
         vfdat TYPE vfdat,
         hsdat TYPE hsdat,
         zustd TYPE char1,
         prueflos TYPE qplos,
         vcode TYPE qvcode,
         vdatum TYPE qvdatum,
         vprueferq TYPE qprueferq,
         coa_flag TYPE c LENGTH 1,
       END OF ty_release.

DATA: gt_rel TYPE STANDARD TABLE OF ty_release WITH HEADER LINE,
      gv_cnt TYPE i.

SELECT-OPTIONS: s_werks FOR mcha-werks OBLIGATORY,
                s_matnr FOR mcha-matnr,
                s_vfdat FOR mcha-vfdat.

START-OF-SELECTION.

  PERFORM read_batches.
  PERFORM read_inspection_lots.
  PERFORM check_coa.
  PERFORM output_worklist.

*&---------------------------------------------------------------------*
*&      Form  READ_BATCHES
*&---------------------------------------------------------------------*
FORM read_batches.

  SELECT matnr charg werks vfdat hsdat zustd
    FROM mcha
    INTO CORRESPONDING FIELDS OF TABLE gt_rel
    WHERE werks IN s_werks
      AND matnr IN s_matnr
      AND vfdat IN s_vfdat.

* Cross client batches (batch level = material) live in MCH1.
  SELECT matnr charg vfdat hsdat zustd
    FROM mch1
    APPENDING CORRESPONDING FIELDS OF TABLE gt_rel
    WHERE matnr IN s_matnr
      AND vfdat IN s_vfdat.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_INSPECTION_LOTS
*&---------------------------------------------------------------------*
FORM read_inspection_lots.

  LOOP AT gt_rel.

    SELECT SINGLE prueflos FROM qals
      INTO gt_rel-prueflos
      WHERE matnr = gt_rel-matnr
        AND charg = gt_rel-charg
        AND werk  = gt_rel-werks.

    IF sy-subrc = 0.
      SELECT SINGLE vcode vdatum vprueferq FROM qave
        INTO (gt_rel-vcode, gt_rel-vdatum, gt_rel-vprueferq)
        WHERE prueflos = gt_rel-prueflos.
    ENDIF.

    MODIFY gt_rel.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  CHECK_COA
*&---------------------------------------------------------------------*
* Certificate of analysis presence is checked against the document
* management staging table with native SQL because the DMS API on this
* release did not expose the archive link for batch documents.
*&---------------------------------------------------------------------*
FORM check_coa.

  DATA: lv_count TYPE i,
        lv_matnr TYPE char18,
        lv_charg TYPE charg_d.

  LOOP AT gt_rel.

    lv_matnr = gt_rel-matnr.
    lv_charg = gt_rel-charg.
    lv_count = 0.

    EXEC SQL.
      SELECT COUNT(*) INTO :lv_count
        FROM ZGSK_COA_STAGING
       WHERE MATNR = :lv_matnr
         AND CHARG = :lv_charg
         AND STATUS = 'REL'
    ENDEXEC.

    IF lv_count > 0.
      gt_rel-coa_flag = 'X'.
    ELSE.
      CLEAR gt_rel-coa_flag.
    ENDIF.

    MODIFY gt_rel.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  OUTPUT_WORKLIST
*&---------------------------------------------------------------------*
FORM output_worklist.

  SORT gt_rel BY werks matnr charg.

  LOOP AT gt_rel.

    IF gt_rel-coa_flag IS INITIAL.
      WRITE: / gt_rel-werks, gt_rel-matnr, gt_rel-charg,
               gt_rel-vfdat, gt_rel-vcode, 'COA MISSING'.
    ELSE.
      WRITE: / gt_rel-werks, gt_rel-matnr, gt_rel-charg,
               gt_rel-vfdat, gt_rel-vcode, 'READY FOR QP'.
    ENDIF.

    ADD 1 TO gv_cnt.
  ENDLOOP.

  WRITE: / 'Batches in worklist:', gv_cnt.

ENDFORM.
