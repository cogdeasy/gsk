*&---------------------------------------------------------------------*
*& Report  ZGSK_MM_ARIBA_PO_SYNC
*&---------------------------------------------------------------------*
*& Outbound purchase order synchronisation to Ariba Network. Selects
*& newly created and changed POs and pushes them over the integration
*& layer, tracking transmission state in a Z table.
*&
*& Object owner : Global Procurement IT
*& GxP class    : Non-GxP
*&---------------------------------------------------------------------*
REPORT zgsk_mm_ariba_po_sync.

TABLES: ekko, ekpo, lfa1, zgsk_ariba_state.

TYPES: BEGIN OF ty_po,
         ebeln TYPE ebeln,
         ebelp TYPE ebelp,
         bukrs TYPE bukrs,
         lifnr TYPE lifnr,
         name1 TYPE name1_gp,
         matnr TYPE char18,
         txz01 TYPE txz01,
         menge TYPE bstmg,
         meins TYPE bstme,
         netpr TYPE bprei,
         waers TYPE waers,
         eindt TYPE eindt,
         sent  TYPE c LENGTH 1,
       END OF ty_po.

DATA: gt_po   TYPE STANDARD TABLE OF ty_po WITH HEADER LINE,
      gt_ekko TYPE STANDARD TABLE OF ekko WITH HEADER LINE,
      gv_sent TYPE i.

SELECT-OPTIONS: s_bukrs FOR ekko-bukrs OBLIGATORY,
                s_aedat FOR ekko-aedat OBLIGATORY,
                s_ekorg FOR ekko-ekorg.
PARAMETERS: p_resend AS CHECKBOX.

START-OF-SELECTION.

  PERFORM select_purchase_orders.
  PERFORM enrich_items.
  PERFORM transmit.

  WRITE: / 'Purchase order items transmitted:', gv_sent.

*&---------------------------------------------------------------------*
*&      Form  SELECT_PURCHASE_ORDERS
*&---------------------------------------------------------------------*
FORM select_purchase_orders.

  SELECT * FROM ekko
    INTO TABLE gt_ekko
    WHERE bukrs IN s_bukrs
      AND aedat IN s_aedat
      AND ekorg IN s_ekorg
      AND bstyp = 'F'
      AND loekz = space.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  ENRICH_ITEMS
*&---------------------------------------------------------------------*
FORM enrich_items.

  DATA: lt_ekpo TYPE STANDARD TABLE OF ekpo WITH HEADER LINE,
        lv_eindt TYPE eindt.

  LOOP AT gt_ekko.

    SELECT * FROM ekpo
      INTO TABLE lt_ekpo
      WHERE ebeln = gt_ekko-ebeln
        AND loekz = space.

    LOOP AT lt_ekpo.

      CLEAR gt_po.
      gt_po-ebeln = lt_ekpo-ebeln.
      gt_po-ebelp = lt_ekpo-ebelp.
      gt_po-bukrs = gt_ekko-bukrs.
      gt_po-lifnr = gt_ekko-lifnr.
      gt_po-matnr = lt_ekpo-matnr.
      gt_po-txz01 = lt_ekpo-txz01.
      gt_po-menge = lt_ekpo-menge.
      gt_po-meins = lt_ekpo-meins.
      gt_po-netpr = lt_ekpo-netpr.
      gt_po-waers = gt_ekko-waers.

      SELECT SINGLE name1 FROM lfa1
        INTO gt_po-name1
        WHERE lifnr = gt_ekko-lifnr.

      SELECT SINGLE eindt FROM eket
        INTO lv_eindt
        WHERE ebeln = lt_ekpo-ebeln
          AND ebelp = lt_ekpo-ebelp
          AND etenr = '0001'.

      gt_po-eindt = lv_eindt.
      APPEND gt_po.

    ENDLOOP.

  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  TRANSMIT
*&---------------------------------------------------------------------*
FORM transmit.

  DATA: ls_state TYPE zgsk_ariba_state,
        lv_subrc TYPE sy-subrc.

  LOOP AT gt_po.

    IF p_resend IS INITIAL.
      SELECT SINGLE * FROM zgsk_ariba_state
        INTO ls_state
        WHERE ebeln = gt_po-ebeln
          AND ebelp = gt_po-ebelp
          AND sent  = 'X'.
      IF sy-subrc = 0.
        CONTINUE.
      ENDIF.
    ENDIF.

    CALL FUNCTION 'Z_ARIBA_PO_SEND'
      DESTINATION 'ARIBA_PRD'
      EXPORTING
        iv_ebeln = gt_po-ebeln
        iv_ebelp = gt_po-ebelp
        iv_lifnr = gt_po-lifnr
        iv_matnr = gt_po-matnr
        iv_menge = gt_po-menge
        iv_netpr = gt_po-netpr
      IMPORTING
        ev_subrc = lv_subrc
      EXCEPTIONS
        communication_failure = 1
        system_failure        = 2
        OTHERS                = 3.

    CLEAR ls_state.
    ls_state-mandt = sy-mandt.
    ls_state-ebeln = gt_po-ebeln.
    ls_state-ebelp = gt_po-ebelp.
    ls_state-erdat = sy-datum.

    IF sy-subrc = 0 AND lv_subrc = 0.
      ls_state-sent = 'X'.
      ADD 1 TO gv_sent.
    ENDIF.

    MODIFY zgsk_ariba_state FROM ls_state.
    COMMIT WORK.

  ENDLOOP.

ENDFORM.
