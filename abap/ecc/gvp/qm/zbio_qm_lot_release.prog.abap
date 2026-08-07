*&---------------------------------------------------------------------*
*& Report  ZBIO_QM_LOT_RELEASE
*&---------------------------------------------------------------------*
*& Lot release worklist for Vaccines. Beyond the internal QP
*& certification that the core system's ZGSK_QM_BATCH_RELEASE covers,
*& a vaccine lot cannot be released to an EU market until an Official
*& Control Authority Batch Release (OCABR) certificate has been issued
*& by an Official Medicines Control Laboratory.
*&
*& The OCABR state machine is the Vaccines-only capability; the QP
*& worklist underneath it is the same function as the core report and
*& the pair converges to one S/4HANA object.
*&
*& Source system : GVP (GSK Vaccines ECC 6.0)
*& Object owner  : Vaccines Quality IT
*& GxP class     : GxP-critical (Annex 16 / OCABR evidence)
*& Validation    : CSV package BIO-QMS-002
*&---------------------------------------------------------------------*
REPORT zbio_qm_lot_release.

TABLES: mcha, mch1, qals, qave.

TYPES: BEGIN OF ty_lot,
         matnr     TYPE char18,
         charg     TYPE charg_d,
         werks     TYPE werks_d,
         vfdat     TYPE vfdat,
         hsdat     TYPE hsdat,
         zustd     TYPE char1,
         prueflos  TYPE qplos,
         vcode     TYPE qvcode,
         vdatum    TYPE qvdatum,
         potency   TYPE p LENGTH 8 DECIMALS 2,
         ocabr_ref TYPE c LENGTH 20,
         ocabr_sta TYPE c LENGTH 1,
         omcl      TYPE c LENGTH 10,
       END OF ty_lot.

DATA: gt_lot TYPE STANDARD TABLE OF ty_lot WITH HEADER LINE,
      gv_rel TYPE i,
      gv_hld TYPE i.

SELECT-OPTIONS: s_werks FOR mcha-werks OBLIGATORY,
                s_matnr FOR mcha-matnr,
                s_vfdat FOR mcha-vfdat.
PARAMETERS: p_market TYPE land1_gp DEFAULT 'BE'.

START-OF-SELECTION.

  PERFORM read_lots.
  PERFORM read_inspection.
  PERFORM read_ocabr.
  PERFORM output_worklist.

*&---------------------------------------------------------------------*
*&      Form  READ_LOTS
*&---------------------------------------------------------------------*
FORM read_lots.

  SELECT matnr charg werks vfdat hsdat zustd
    FROM mcha
    INTO CORRESPONDING FIELDS OF TABLE gt_lot
    WHERE werks IN s_werks
      AND matnr IN s_matnr
      AND vfdat IN s_vfdat.

  SELECT matnr charg vfdat hsdat zustd
    FROM mch1
    APPENDING CORRESPONDING FIELDS OF TABLE gt_lot
    WHERE matnr IN s_matnr
      AND vfdat IN s_vfdat.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_INSPECTION
*&---------------------------------------------------------------------*
* Usage decision plus the potency result from the inspection
* characteristic. Potency is what the OMCL re-tests, so it travels
* with the release record.
*&---------------------------------------------------------------------*
FORM read_inspection.

  LOOP AT gt_lot.

    SELECT SINGLE prueflos FROM qals
      INTO gt_lot-prueflos
      WHERE matnr = gt_lot-matnr
        AND charg = gt_lot-charg
        AND werk  = gt_lot-werks.

    IF sy-subrc = 0.

      SELECT SINGLE vcode vdatum FROM qave
        INTO (gt_lot-vcode, gt_lot-vdatum)
        WHERE prueflos = gt_lot-prueflos.

      SELECT SINGLE mittelwert FROM qamv
        INTO gt_lot-potency
        WHERE prueflos = gt_lot-prueflos
          AND verwmerkm = 'POTENCY'.

    ENDIF.

    MODIFY gt_lot.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_OCABR
*&---------------------------------------------------------------------*
* OCABR certificates are held in a Z table fed by the regulatory
* affairs system. Native SQL because the feed writes to a secondary
* schema that was never exposed through the dictionary.
*&---------------------------------------------------------------------*
FORM read_ocabr.

  DATA: lv_charg TYPE charg_d,
        lv_ref   TYPE c LENGTH 20,
        lv_sta   TYPE c LENGTH 1,
        lv_omcl  TYPE c LENGTH 10.

  LOOP AT gt_lot.

    lv_charg = gt_lot-charg.
    CLEAR: lv_ref, lv_sta, lv_omcl.

    EXEC SQL.
      SELECT CERT_REF, CERT_STATUS, OMCL_CODE
        INTO :lv_ref, :lv_sta, :lv_omcl
        FROM ZBIO_OCABR_CERT
       WHERE CHARG = :lv_charg
         AND MARKET = :p_market
    ENDEXEC.

    gt_lot-ocabr_ref = lv_ref.
    gt_lot-ocabr_sta = lv_sta.
    gt_lot-omcl      = lv_omcl.

    MODIFY gt_lot.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  OUTPUT_WORKLIST
*&---------------------------------------------------------------------*
FORM output_worklist.

  SORT gt_lot BY werks matnr charg.

  LOOP AT gt_lot.

    IF gt_lot-vcode IS INITIAL.
      WRITE: / gt_lot-werks, gt_lot-matnr, gt_lot-charg,
               gt_lot-vfdat, 'NO USAGE DECISION'.
      ADD 1 TO gv_hld.
    ELSEIF gt_lot-ocabr_sta <> 'C'.
      WRITE: / gt_lot-werks, gt_lot-matnr, gt_lot-charg,
               gt_lot-vfdat, gt_lot-omcl, 'AWAITING OCABR'.
      ADD 1 TO gv_hld.
    ELSE.
      WRITE: / gt_lot-werks, gt_lot-matnr, gt_lot-charg,
               gt_lot-vfdat, gt_lot-ocabr_ref, 'RELEASABLE'.
      ADD 1 TO gv_rel.
    ENDIF.

  ENDLOOP.

  WRITE: / 'Releasable:', gv_rel, 'Held:', gv_hld.

ENDFORM.
