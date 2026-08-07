*&---------------------------------------------------------------------*
*& Report  ZGSK_SD_ORDER_VARIANTS
*&---------------------------------------------------------------------*
*& Sales order status and variant analysis. This is the report behind
*& the process mining extract that surfaced ~28,000 variants of the
*& order-to-cash process across the unified ECC instance.
*&
*& Object owner : Commercial IT
*& GxP class    : Non-GxP
*&---------------------------------------------------------------------*
REPORT zgsk_sd_order_variants.

TABLES: vbak, vbap, vbuk, vbup, likp.

TYPES: BEGIN OF ty_order,
         vbeln TYPE vbeln_va,
         posnr TYPE posnr_va,
         auart TYPE auart,
         vkorg TYPE vkorg,
         vtweg TYPE vtweg,
         kunnr TYPE kunnr,
         matnr TYPE char18,
         kwmeng TYPE kwmeng,
         gbstk TYPE gbstk,
         lfstk TYPE lfstk,
         fkstk TYPE fkstk,
         cmgst TYPE cmgst,
         variant TYPE string,
       END OF ty_order.

DATA: gt_orders TYPE STANDARD TABLE OF ty_order WITH HEADER LINE,
      gt_var    TYPE STANDARD TABLE OF string WITH HEADER LINE.

SELECT-OPTIONS: s_vkorg FOR vbak-vkorg OBLIGATORY,
                s_erdat FOR vbak-erdat OBLIGATORY,
                s_auart FOR vbak-auart.

START-OF-SELECTION.

  PERFORM read_orders.
  PERFORM read_header_status.
  PERFORM read_item_status.
  PERFORM build_variants.

*&---------------------------------------------------------------------*
*&      Form  READ_ORDERS
*&---------------------------------------------------------------------*
FORM read_orders.

  SELECT k~vbeln p~posnr k~auart k~vkorg k~vtweg k~kunnr
         p~matnr p~kwmeng
    FROM vbak AS k INNER JOIN vbap AS p ON k~vbeln = p~vbeln
    INTO CORRESPONDING FIELDS OF TABLE gt_orders
    WHERE k~vkorg IN s_vkorg
      AND k~erdat IN s_erdat
      AND k~auart IN s_auart.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_HEADER_STATUS
*&---------------------------------------------------------------------*
* Header status is read from VBUK.
*&---------------------------------------------------------------------*
FORM read_header_status.

  DATA: lt_vbuk TYPE STANDARD TABLE OF vbuk WITH HEADER LINE.

  IF gt_orders[] IS INITIAL.
    RETURN.
  ENDIF.

  SELECT * FROM vbuk
    INTO TABLE lt_vbuk
    FOR ALL ENTRIES IN gt_orders
    WHERE vbeln = gt_orders-vbeln.

  LOOP AT gt_orders.
    READ TABLE lt_vbuk WITH KEY vbeln = gt_orders-vbeln.
    IF sy-subrc = 0.
      gt_orders-gbstk = lt_vbuk-gbstk.
      gt_orders-lfstk = lt_vbuk-lfstk.
      gt_orders-fkstk = lt_vbuk-fkstk.
      gt_orders-cmgst = lt_vbuk-cmgst.
      MODIFY gt_orders.
    ENDIF.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_ITEM_STATUS
*&---------------------------------------------------------------------*
* Item status from VBUP - used to detect partially delivered items.
*&---------------------------------------------------------------------*
FORM read_item_status.

  DATA: lv_lfsta TYPE lfsta.

  LOOP AT gt_orders.

    SELECT SINGLE lfsta FROM vbup
      INTO lv_lfsta
      WHERE vbeln = gt_orders-vbeln
        AND posnr = gt_orders-posnr.

    IF sy-subrc = 0 AND lv_lfsta = 'B'.
      CONCATENATE gt_orders-variant 'PARTIAL_DELIVERY' INTO gt_orders-variant
        SEPARATED BY '|'.
      MODIFY gt_orders.
    ENDIF.

  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  BUILD_VARIANTS
*&---------------------------------------------------------------------*
FORM build_variants.

  DATA: lv_key TYPE string.

  LOOP AT gt_orders.
    CONCATENATE gt_orders-auart gt_orders-gbstk gt_orders-lfstk
                gt_orders-fkstk gt_orders-cmgst gt_orders-variant
           INTO lv_key SEPARATED BY '-'.
    APPEND lv_key TO gt_var.
  ENDLOOP.

  SORT gt_var.
  DELETE ADJACENT DUPLICATES FROM gt_var.

  LOOP AT gt_var.
    WRITE: / gt_var.
  ENDLOOP.

  DESCRIBE TABLE gt_var LINES sy-tfill.
  WRITE: / 'Distinct process variants:', sy-tfill.

ENDFORM.
