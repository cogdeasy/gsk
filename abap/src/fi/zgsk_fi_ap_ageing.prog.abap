*&---------------------------------------------------------------------*
*& Report  ZGSK_FI_AP_AGEING
*&---------------------------------------------------------------------*
*& Accounts payable ageing for the shared service centres. Splits
*& supplier open items into ageing buckets and reconciles against the
*& G/L reconciliation accounts.
*&
*& Object owner : Global Financial Services (Kuala Lumpur SSC)
*& GxP class    : Non-GxP (SOX relevant)
*&---------------------------------------------------------------------*
REPORT zgsk_fi_ap_ageing.

TABLES: bsik, bsak, lfa1, lfb1.

TYPES: BEGIN OF ty_ageing,
         bukrs   TYPE bukrs,
         lifnr   TYPE lifnr,
         name1   TYPE name1_gp,
         land1   TYPE land1_gp,
         belnr   TYPE belnr_d,
         gjahr   TYPE gjahr,
         zfbdt   TYPE dzfbdt,
         dmbtr   TYPE dmbtr,
         waers   TYPE waers,
         bucket1 TYPE dmbtr,
         bucket2 TYPE dmbtr,
         bucket3 TYPE dmbtr,
         bucket4 TYPE dmbtr,
       END OF ty_ageing.

DATA: gt_ageing TYPE STANDARD TABLE OF ty_ageing WITH HEADER LINE,
      gv_days   TYPE i.

SELECT-OPTIONS: s_bukrs FOR bsik-bukrs OBLIGATORY,
                s_lifnr FOR bsik-lifnr.
PARAMETERS: p_keydat TYPE budat DEFAULT sy-datum.

START-OF-SELECTION.

  PERFORM read_open_items.
  PERFORM enrich_vendor.
  PERFORM build_buckets.
  PERFORM output.

*&---------------------------------------------------------------------*
*&      Form  READ_OPEN_ITEMS
*&---------------------------------------------------------------------*
FORM read_open_items.

  SELECT bukrs lifnr belnr gjahr zfbdt dmbtr waers
    FROM bsik
    INTO CORRESPONDING FIELDS OF TABLE gt_ageing
    WHERE bukrs IN s_bukrs
      AND lifnr IN s_lifnr.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  ENRICH_VENDOR
*&---------------------------------------------------------------------*
* Vendor master name and country read directly from LFA1 / LFB1.
*&---------------------------------------------------------------------*
FORM enrich_vendor.

  LOOP AT gt_ageing.

    SELECT SINGLE name1 land1 FROM lfa1
      INTO (gt_ageing-name1, gt_ageing-land1)
      WHERE lifnr = gt_ageing-lifnr.

    IF sy-subrc <> 0.
      gt_ageing-name1 = 'UNKNOWN SUPPLIER'.
    ENDIF.

    MODIFY gt_ageing.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  BUILD_BUCKETS
*&---------------------------------------------------------------------*
FORM build_buckets.

  LOOP AT gt_ageing.
    gv_days = p_keydat - gt_ageing-zfbdt.

    IF gv_days <= 30.
      MOVE gt_ageing-dmbtr TO gt_ageing-bucket1.
    ELSEIF gv_days <= 60.
      MOVE gt_ageing-dmbtr TO gt_ageing-bucket2.
    ELSEIF gv_days <= 90.
      MOVE gt_ageing-dmbtr TO gt_ageing-bucket3.
    ELSE.
      MOVE gt_ageing-dmbtr TO gt_ageing-bucket4.
    ENDIF.

    MODIFY gt_ageing.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  OUTPUT
*&---------------------------------------------------------------------*
FORM output.

  DATA: lv_sum TYPE dmbtr.

  SORT gt_ageing BY bukrs lifnr.

  LOOP AT gt_ageing.
    WRITE: / gt_ageing-bukrs,
             gt_ageing-lifnr,
             gt_ageing-name1,
             gt_ageing-bucket1,
             gt_ageing-bucket2,
             gt_ageing-bucket3,
             gt_ageing-bucket4.
    ADD gt_ageing-dmbtr TO lv_sum.
  ENDLOOP.

  WRITE: / 'Total open AP:', lv_sum.

ENDFORM.
