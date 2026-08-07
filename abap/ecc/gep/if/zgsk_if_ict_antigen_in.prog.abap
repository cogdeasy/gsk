*&---------------------------------------------------------------------*
*& Report  ZGSK_IF_ICT_ANTIGEN_IN
*&---------------------------------------------------------------------*
*& Inbound intercompany interface: core system receiving from the
*& Vaccines system. The mirror of ZBIO_IF_ICT_ANTIGEN_OUT in GVP.
*&
*& Processes the DESADV IDocs Wavre sends for antigen bulk and
*& finished vaccine, posts the goods receipt against the intercompany
*& purchase order, and books the intercompany profit in stock so group
*& consolidation can eliminate it.
*&
*& Disposition: DECOMMISSION. This exists only because the supplying
*& and receiving companies sit in two ECC systems. In the merged
*& S/4HANA client the movement is a stock transport order and this
*& program, its IDoc configuration, its partner profiles and its
*& reconciliation job all go away.
*&
*& Source system : GEP (GSK core ECC 6.0)
*& Object owner  : Global Financial Services
*& GxP class     : GxP-relevant (goods receipt of GxP material)
*&---------------------------------------------------------------------*
REPORT zgsk_if_ict_antigen_in.

TABLES: edidc, edidd, ekko, ekpo.

TYPES: BEGIN OF ty_receipt,
         docnum    TYPE edi_docnum,
         ebeln     TYPE ebeln,
         ebelp     TYPE ebelp,
         matnr     TYPE char18,
         charg     TYPE charg_d,
         menge     TYPE menge_d,
         meins     TYPE meins,
         werks     TYPE werks_d,
         ict_price TYPE dmbtr,
         status    TYPE c LENGTH 2,
       END OF ty_receipt.

DATA: gt_receipt TYPE STANDARD TABLE OF ty_receipt WITH HEADER LINE,
      gv_posted  TYPE i,
      gv_held    TYPE i.

SELECT-OPTIONS: s_credat FOR edidc-credat OBLIGATORY,
                s_sndprn FOR edidc-sndprn.

START-OF-SELECTION.

  PERFORM read_inbound_idocs.
  PERFORM match_purchase_orders.
  PERFORM post_receipts.

  WRITE: / 'Receipts posted:', gv_posted, 'held:', gv_held.

*&---------------------------------------------------------------------*
*&      Form  READ_INBOUND_IDOCS
*&---------------------------------------------------------------------*
FORM read_inbound_idocs.

  DATA: lt_ctrl TYPE STANDARD TABLE OF edidc WITH HEADER LINE,
        lt_seg  TYPE STANDARD TABLE OF edidd WITH HEADER LINE.

  SELECT * FROM edidc
    INTO TABLE lt_ctrl
    CLIENT SPECIFIED
    WHERE mandt  = sy-mandt
      AND mestyp = 'DESADV'
      AND credat IN s_credat
      AND sndprn IN s_sndprn
      AND status = '64'.

  LOOP AT lt_ctrl.

    SELECT * FROM edidd
      INTO TABLE lt_seg
      WHERE docnum = lt_ctrl-docnum.

    LOOP AT lt_seg WHERE segnam = 'E1EDL24'.
      CLEAR gt_receipt.
      gt_receipt-docnum = lt_ctrl-docnum.
      SPLIT lt_seg-sdata AT space INTO gt_receipt-matnr
                                       gt_receipt-charg
                                       gt_receipt-menge.
      APPEND gt_receipt.
    ENDLOOP.

  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  MATCH_PURCHASE_ORDERS
*&---------------------------------------------------------------------*
* Matches each shipped line to the open intercompany purchase order.
* Where the Vaccines side has used its own material number and the
* cross reference is missing, the line is held for manual clearing -
* the cross reference table is the same overlap problem the master
* data merge has to solve.
*&---------------------------------------------------------------------*
FORM match_purchase_orders.

  DATA: lv_core_matnr TYPE char18.

  LOOP AT gt_receipt.

    SELECT SINGLE core_matnr FROM zgsk_bio_matnr_xref
      INTO lv_core_matnr
      WHERE bio_matnr = gt_receipt-matnr.

    IF sy-subrc <> 0.
      gt_receipt-status = 'XR'.
      MODIFY gt_receipt.
      CONTINUE.
    ENDIF.

    gt_receipt-matnr = lv_core_matnr.

    SELECT SINGLE ekpo~ebeln ekpo~ebelp ekpo~werks
      FROM ekpo
      INNER JOIN ekko ON ekko~ebeln = ekpo~ebeln
      INTO (gt_receipt-ebeln, gt_receipt-ebelp, gt_receipt-werks)
      WHERE ekpo~matnr = lv_core_matnr
        AND ekpo~elikz = space
        AND ekko~bsart = 'ZIC'.

    IF sy-subrc <> 0.
      gt_receipt-status = 'PO'.
    ELSE.
      gt_receipt-status = 'OK'.
    ENDIF.

    MODIFY gt_receipt.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  POST_RECEIPTS
*&---------------------------------------------------------------------*
FORM post_receipts.

  DATA: ls_header  TYPE bapi2017_gm_head_01,
        ls_code    TYPE bapi2017_gm_code,
        lt_item    TYPE STANDARD TABLE OF bapi2017_gm_item_create,
        ls_item    TYPE bapi2017_gm_item_create,
        lt_return  TYPE STANDARD TABLE OF bapiret2,
        lv_matdoc  TYPE bapi2017_gm_head_ret-mat_doc.

  LOOP AT gt_receipt.

    IF gt_receipt-status <> 'OK'.
      ADD 1 TO gv_held.
      CONTINUE.
    ENDIF.

    CLEAR: ls_header, lt_item[].
    ls_header-pstng_date = sy-datum.
    ls_header-doc_date   = sy-datum.
    ls_code-gm_code      = '01'.

    ls_item-material  = gt_receipt-matnr.
    ls_item-plant     = gt_receipt-werks.
    ls_item-batch     = gt_receipt-charg.
    ls_item-move_type = '101'.
    ls_item-entry_qnt = gt_receipt-menge.
    ls_item-po_number = gt_receipt-ebeln.
    ls_item-po_item   = gt_receipt-ebelp.
    APPEND ls_item TO lt_item.

    CALL FUNCTION 'BAPI_GOODSMVT_CREATE'
      EXPORTING
        goodsmvt_header  = ls_header
        goodsmvt_code    = ls_code
      IMPORTING
        materialdocument = lv_matdoc
      TABLES
        goodsmvt_item    = lt_item
        return           = lt_return.

    READ TABLE lt_return TRANSPORTING NO FIELDS WITH KEY type = 'E'.
    IF sy-subrc = 0.
      CALL FUNCTION 'BAPI_TRANSACTION_ROLLBACK'.
      ADD 1 TO gv_held.
    ELSE.
      COMMIT WORK.
      ADD 1 TO gv_posted.
    ENDIF.

  ENDLOOP.

ENDFORM.
