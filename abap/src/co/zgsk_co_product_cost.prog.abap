*&---------------------------------------------------------------------*
*& Report  ZGSK_CO_PRODUCT_COST
*&---------------------------------------------------------------------*
*& Product cost collector variance analysis for the manufacturing
*& sites. Compares planned and actual costs by cost element from the
*& CO totals tables.
*&
*& Object owner : Global Financial Services / Controlling
*& GxP class    : Non-GxP
*&---------------------------------------------------------------------*
REPORT zgsk_co_product_cost.

TABLES: cosp, coss, coep, aufk.

TYPES: BEGIN OF ty_cost,
         kokrs  TYPE kokrs,
         objnr  TYPE j_objnr,
         aufnr  TYPE aufnr,
         gjahr  TYPE gjahr,
         kstar  TYPE kstar,
         wrttp  TYPE co_wrttp,
         plan   TYPE wtg001,
         actual TYPE wtg001,
         var    TYPE wtg001,
       END OF ty_cost.

DATA: gt_cost TYPE STANDARD TABLE OF ty_cost WITH HEADER LINE,
      gt_aufk TYPE STANDARD TABLE OF aufk WITH HEADER LINE.

SELECT-OPTIONS: s_kokrs FOR cosp-kokrs OBLIGATORY NO-EXTENSION NO INTERVALS,
                s_gjahr FOR cosp-gjahr OBLIGATORY NO-EXTENSION NO INTERVALS,
                s_aufnr FOR aufk-aufnr.

START-OF-SELECTION.

  PERFORM read_orders.
  PERFORM read_primary_costs.
  PERFORM read_secondary_costs.
  PERFORM output_variance.

*&---------------------------------------------------------------------*
*&      Form  READ_ORDERS
*&---------------------------------------------------------------------*
FORM read_orders.

  SELECT * FROM aufk
    INTO TABLE gt_aufk
    WHERE aufnr IN s_aufnr.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_PRIMARY_COSTS
*&---------------------------------------------------------------------*
* Primary cost totals from COSP, one read per order object number.
*&---------------------------------------------------------------------*
FORM read_primary_costs.

  DATA: lt_cosp TYPE STANDARD TABLE OF cosp WITH HEADER LINE.

  LOOP AT gt_aufk.

    SELECT * FROM cosp
      INTO TABLE lt_cosp
      WHERE kokrs IN s_kokrs
        AND objnr = gt_aufk-objnr
        AND gjahr IN s_gjahr.

    LOOP AT lt_cosp.
      CLEAR gt_cost.
      gt_cost-kokrs = lt_cosp-kokrs.
      gt_cost-objnr = lt_cosp-objnr.
      gt_cost-aufnr = gt_aufk-aufnr.
      gt_cost-gjahr = lt_cosp-gjahr.
      gt_cost-kstar = lt_cosp-kstar.
      gt_cost-wrttp = lt_cosp-wrttp.

      IF lt_cosp-wrttp = '01'.
        gt_cost-plan = lt_cosp-wtg001 + lt_cosp-wtg002 + lt_cosp-wtg003.
      ELSE.
        gt_cost-actual = lt_cosp-wtg001 + lt_cosp-wtg002 + lt_cosp-wtg003.
      ENDIF.

      COLLECT gt_cost.
    ENDLOOP.

  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_SECONDARY_COSTS
*&---------------------------------------------------------------------*
FORM read_secondary_costs.

  DATA: lt_coss TYPE STANDARD TABLE OF coss WITH HEADER LINE.

  LOOP AT gt_aufk.

    SELECT * FROM coss
      INTO TABLE lt_coss
      WHERE kokrs IN s_kokrs
        AND objnr = gt_aufk-objnr
        AND gjahr IN s_gjahr.

    LOOP AT lt_coss.
      CLEAR gt_cost.
      gt_cost-kokrs  = lt_coss-kokrs.
      gt_cost-objnr  = lt_coss-objnr.
      gt_cost-aufnr  = gt_aufk-aufnr.
      gt_cost-gjahr  = lt_coss-gjahr.
      gt_cost-kstar  = lt_coss-kstar.
      gt_cost-actual = lt_coss-wtg001 + lt_coss-wtg002 + lt_coss-wtg003.
      COLLECT gt_cost.
    ENDLOOP.

  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  OUTPUT_VARIANCE
*&---------------------------------------------------------------------*
FORM output_variance.

  LOOP AT gt_cost.
    gt_cost-var = gt_cost-actual - gt_cost-plan.
    MODIFY gt_cost.
    WRITE: / gt_cost-aufnr, gt_cost-kstar, gt_cost-plan,
             gt_cost-actual, gt_cost-var.
  ENDLOOP.

ENDFORM.
