*&---------------------------------------------------------------------*
*& Report  ZGSK_MM_SERIALISATION_RECON
*&---------------------------------------------------------------------*
*& Reconciliation between ECC batch stock and the serialization /
*& track-and-trace repository (EU FMD, DSCSA). Compares commissioned
*& serial numbers per batch against posted goods movements.
*&
*& Object owner : GSC Serialisation Programme
*& GxP class    : GxP-critical (falsified medicines compliance)
*&---------------------------------------------------------------------*
REPORT zgsk_mm_serialisation_recon.

TABLES: mseg, mkpf, mchb, zgsk_serial_stage.

TYPES: BEGIN OF ty_recon,
         werks     TYPE werks_d,
         matnr     TYPE char18,
         charg     TYPE charg_d,
         erp_qty   TYPE menge_d,
         ser_qty   TYPE menge_d,
         delta     TYPE menge_d,
         meins     TYPE meins,
         status    TYPE char10,
       END OF ty_recon.

DATA: gt_recon TYPE STANDARD TABLE OF ty_recon WITH HEADER LINE,
      gv_delta TYPE i.

SELECT-OPTIONS: s_werks FOR mseg-werks OBLIGATORY,
                s_budat FOR mkpf-budat OBLIGATORY,
                s_matnr FOR mseg-matnr.

START-OF-SELECTION.

  PERFORM read_erp_quantities.
  PERFORM read_serialisation_stage.
  PERFORM compare.

*&---------------------------------------------------------------------*
*&      Form  READ_ERP_QUANTITIES
*&---------------------------------------------------------------------*
* Packed quantity per batch derived from goods receipts (movement
* types 101 / 531) in MSEG joined to MKPF for the posting date.
*&---------------------------------------------------------------------*
FORM read_erp_quantities.

  DATA: lt_mseg TYPE STANDARD TABLE OF mseg WITH HEADER LINE,
        lt_mkpf TYPE STANDARD TABLE OF mkpf WITH HEADER LINE.

  SELECT * FROM mkpf
    INTO TABLE lt_mkpf
    WHERE budat IN s_budat.

  SELECT * FROM mseg
    INTO TABLE lt_mseg
    FOR ALL ENTRIES IN lt_mkpf
    WHERE mblnr = lt_mkpf-mblnr
      AND mjahr = lt_mkpf-mjahr
      AND werks IN s_werks
      AND matnr IN s_matnr
      AND bwart = '101'.

  LOOP AT lt_mseg.
    CLEAR gt_recon.
    gt_recon-werks   = lt_mseg-werks.
    gt_recon-matnr   = lt_mseg-matnr.
    gt_recon-charg   = lt_mseg-charg.
    gt_recon-erp_qty = lt_mseg-menge.
    gt_recon-meins   = lt_mseg-meins.
    COLLECT gt_recon.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_SERIALISATION_STAGE
*&---------------------------------------------------------------------*
FORM read_serialisation_stage.

  DATA: lv_qty TYPE menge_d.

  LOOP AT gt_recon.

    SELECT SUM( qty ) FROM zgsk_serial_stage
      INTO lv_qty
      WHERE werks = gt_recon-werks
        AND matnr = gt_recon-matnr
        AND charg = gt_recon-charg
        AND evt   = 'COMMISSION'.

    gt_recon-ser_qty = lv_qty.
    MODIFY gt_recon.

  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  COMPARE
*&---------------------------------------------------------------------*
FORM compare.

  SORT gt_recon BY werks matnr charg.

  LOOP AT gt_recon.

    gt_recon-delta = gt_recon-erp_qty - gt_recon-ser_qty.

    IF gt_recon-delta = 0.
      gt_recon-status = 'MATCHED'.
    ELSE.
      gt_recon-status = 'EXCEPTION'.
      ADD 1 TO gv_delta.
    ENDIF.

    MODIFY gt_recon.

    WRITE: / gt_recon-werks, gt_recon-matnr, gt_recon-charg,
             gt_recon-erp_qty, gt_recon-ser_qty, gt_recon-delta,
             gt_recon-status.
  ENDLOOP.

  WRITE: / 'Reconciliation exceptions:', gv_delta.

ENDFORM.
