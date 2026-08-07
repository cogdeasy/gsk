*&---------------------------------------------------------------------*
*& Report  ZBIO_FI_AP_AGEING
*&---------------------------------------------------------------------*
*& Accounts payable ageing for the Vaccines shared service centre.
*&
*& Copied from ZGSK_FI_AP_AGEING in the core system in 2013 and
*& maintained separately since. The two versions have diverged: this
*& one carries a fifth ageing bucket (>180 days) demanded by the
*& Belgian statutory pack, reads the withholding tax indicator, and
*& reports in EUR only.
*&
*& Source system : GVP (GSK Vaccines ECC 6.0)
*& Object owner  : Vaccines Finance Systems (Wavre)
*& GxP class     : Non-GxP (SOX relevant)
*&---------------------------------------------------------------------*
REPORT zbio_fi_ap_ageing.

TABLES: bsik, bsak, lfa1, lfb1.

TYPES: BEGIN OF ty_ageing,
         bukrs   TYPE bukrs,
         lifnr   TYPE lifnr,
         name1   TYPE name1_gp,
         land1   TYPE land1_gp,
         qsskz   TYPE qsskz,
         belnr   TYPE belnr_d,
         gjahr   TYPE gjahr,
         zfbdt   TYPE dzfbdt,
         dmbtr   TYPE dmbtr,
         waers   TYPE waers,
         bucket1 TYPE dmbtr,
         bucket2 TYPE dmbtr,
         bucket3 TYPE dmbtr,
         bucket4 TYPE dmbtr,
         bucket5 TYPE dmbtr,
       END OF ty_ageing.

DATA: gt_ageing TYPE STANDARD TABLE OF ty_ageing WITH HEADER LINE,
      gv_days   TYPE i.

SELECT-OPTIONS: s_bukrs FOR bsik-bukrs OBLIGATORY,
                s_lifnr FOR bsik-lifnr.
PARAMETERS: p_keydat TYPE budat DEFAULT sy-datum,
            p_cleard AS CHECKBOX.

START-OF-SELECTION.

  PERFORM read_open_items.
  IF p_cleard = 'X'.
    PERFORM read_cleared_items.
  ENDIF.
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
*&      Form  READ_CLEARED_ITEMS
*&---------------------------------------------------------------------*
* Cleared items are pulled in for the rolling twelve month statutory
* comparison. The core system's version of this report does not do
* this, which is one reason the two outputs never tie.
*&---------------------------------------------------------------------*
FORM read_cleared_items.

  SELECT bukrs lifnr belnr gjahr zfbdt dmbtr waers
    FROM bsak
    APPENDING CORRESPONDING FIELDS OF TABLE gt_ageing
    WHERE bukrs IN s_bukrs
      AND lifnr IN s_lifnr
      AND augdt >= p_keydat.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  ENRICH_VENDOR
*&---------------------------------------------------------------------*
FORM enrich_vendor.

  LOOP AT gt_ageing.

    SELECT SINGLE name1 land1 FROM lfa1
      INTO (gt_ageing-name1, gt_ageing-land1)
      WHERE lifnr = gt_ageing-lifnr.

    IF sy-subrc <> 0.
      gt_ageing-name1 = 'UNKNOWN SUPPLIER'.
    ENDIF.

    SELECT SINGLE qsskz FROM lfb1
      INTO gt_ageing-qsskz
      WHERE lifnr = gt_ageing-lifnr
        AND bukrs = gt_ageing-bukrs.

    MODIFY gt_ageing.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  BUILD_BUCKETS
*&---------------------------------------------------------------------*
* Five buckets, not four. The boundary at 180 days is the divergence
* from the core report that has to be resolved in fit-gap before the
* two can share one S/4HANA object.
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
    ELSEIF gv_days <= 180.
      MOVE gt_ageing-dmbtr TO gt_ageing-bucket4.
    ELSE.
      MOVE gt_ageing-dmbtr TO gt_ageing-bucket5.
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
             gt_ageing-qsskz,
             gt_ageing-bucket1,
             gt_ageing-bucket2,
             gt_ageing-bucket3,
             gt_ageing-bucket4,
             gt_ageing-bucket5.
    ADD gt_ageing-dmbtr TO lv_sum.
  ENDLOOP.

  WRITE: / 'Total open AP (EUR):', lv_sum.

ENDFORM.
