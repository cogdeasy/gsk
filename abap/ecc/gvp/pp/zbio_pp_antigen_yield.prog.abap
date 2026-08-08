*&---------------------------------------------------------------------*
*& Report  ZBIO_PP_ANTIGEN_YIELD
*&---------------------------------------------------------------------*
*& Antigen bulk campaign yield. Compares planned against confirmed
*& quantity per process order across a fermentation or cell culture
*& campaign and reports yield against the validated range.
*&
*& No equivalent exists in the core system - Pharma does not run
*& campaign based biological production - so this object is retained
*& rather than converged, and needs a clean-core home of its own in
*& the target.
*&
*& Source system : GVP (GSK Vaccines ECC 6.0)
*& Object owner  : Vaccines Manufacturing IT (Wavre)
*& GxP class     : GxP-relevant (process performance, not a release
*&                 decision)
*&---------------------------------------------------------------------*
REPORT zbio_pp_antigen_yield LINE-SIZE 180.

TABLES: aufk, afko, afpo, mdkp.

TYPES: BEGIN OF ty_order,
         aufnr    TYPE aufnr,
         werks    TYPE werks_d,
         matnr    TYPE char18,
         charg    TYPE charg_d,
         gamng    TYPE gamng,
         gmein    TYPE meins,
         wemng    TYPE wemng,
         gstrp    TYPE co_gstrp,
         gltrp    TYPE co_gltrp,
         campaign TYPE c LENGTH 12,
         yield    TYPE p LENGTH 8 DECIMALS 2,
       END OF ty_order.

DATA: gt_order TYPE STANDARD TABLE OF ty_order WITH HEADER LINE,
      gv_total TYPE gamng,
      gv_conf  TYPE wemng.

SELECT-OPTIONS: s_werks FOR aufk-werks OBLIGATORY,
                s_gstrp FOR afko-gstrp OBLIGATORY,
                s_matnr FOR afpo-matnr.
PARAMETERS: p_minyld TYPE p LENGTH 8 DECIMALS 2 DEFAULT '85.00'.

START-OF-SELECTION.

  PERFORM read_orders.
  PERFORM read_confirmations.
  PERFORM read_mrp_exceptions.
  PERFORM output.

*&---------------------------------------------------------------------*
*&      Form  READ_ORDERS
*&---------------------------------------------------------------------*
FORM read_orders.

  SELECT aufk~aufnr aufk~werks afpo~matnr afpo~charg
         afko~gamng afko~gmein afko~gstrp afko~gltrp
    FROM aufk
    INNER JOIN afko ON afko~aufnr = aufk~aufnr
    INNER JOIN afpo ON afpo~aufnr = aufk~aufnr
    INTO CORRESPONDING FIELDS OF TABLE gt_order
    WHERE aufk~werks IN s_werks
      AND afko~gstrp IN s_gstrp
      AND afpo~matnr IN s_matnr.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_CONFIRMATIONS
*&---------------------------------------------------------------------*
* Confirmed quantity is summed from the goods receipts against the
* order. The campaign identifier lives in the order long text key,
* read one order at a time.
*&---------------------------------------------------------------------*
FORM read_confirmations.

  LOOP AT gt_order.

    SELECT SUM( menge ) FROM mseg
      INTO gt_order-wemng
      WHERE aufnr = gt_order-aufnr
        AND bwart = '101'.

    SELECT SINGLE zz_campaign FROM aufk
      INTO gt_order-campaign
      WHERE aufnr = gt_order-aufnr.

    IF gt_order-gamng > 0.
      gt_order-yield = gt_order-wemng * 100 / gt_order-gamng.
    ENDIF.

    MODIFY gt_order.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_MRP_EXCEPTIONS
*&---------------------------------------------------------------------*
* Campaign shortfalls are cross checked against the MRP exception
* list so planning sees the same picture.
*&---------------------------------------------------------------------*
FORM read_mrp_exceptions.

  DATA: lt_mdkp TYPE STANDARD TABLE OF mdkp WITH HEADER LINE.

  SELECT * FROM mdkp
    INTO TABLE lt_mdkp
    WHERE plwrk IN s_werks
      AND dtart = 'MD'.

  LOOP AT lt_mdkp.
    READ TABLE gt_order WITH KEY matnr = lt_mdkp-matnr.
    IF sy-subrc = 0 AND gt_order-yield < p_minyld.
      WRITE: / 'MRP exception open for short campaign:', lt_mdkp-matnr.
    ENDIF.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  OUTPUT
*&---------------------------------------------------------------------*
FORM output.

  SORT gt_order BY campaign werks aufnr.

  LOOP AT gt_order.

    WRITE: / gt_order-campaign,
             gt_order-werks,
             gt_order-aufnr,
             gt_order-matnr,
             gt_order-charg,
             gt_order-gamng,
             gt_order-wemng,
             gt_order-gmein,
             gt_order-yield.

    IF gt_order-yield < p_minyld.
      WRITE: 'BELOW VALIDATED RANGE'.
    ENDIF.

    ADD gt_order-gamng TO gv_total.
    ADD gt_order-wemng TO gv_conf.
  ENDLOOP.

  WRITE: / 'Planned:', gv_total, 'Confirmed:', gv_conf.

ENDFORM.
