*&---------------------------------------------------------------------*
*& Report  ZGSK_MM_STOCK_OVERVIEW
*&---------------------------------------------------------------------*
*& Global unrestricted / quality / blocked stock overview across the
*& GSK manufacturing network. Used by Global Supply Chain planners and
*& by the nightly feed into the enterprise data platform.
*&
*& Object owner : GSC Supply Chain IT
*& GxP class    : GxP-relevant (indirect - reporting only)
*& Created      : 2009 (ERP unification wave 2)
*& Last change  : 2019 - added vaccine cold-chain plants
*&---------------------------------------------------------------------*
REPORT zgsk_mm_stock_overview.

TABLES: mard, marc, mchb.

TYPES: BEGIN OF ty_stock,
         werks TYPE werks_d,
         lgort TYPE lgort_d,
         matnr TYPE char18,
         charg TYPE charg_d,
         labst TYPE labst,
         insme TYPE insme,
         speme TYPE speme,
         meins TYPE meins,
       END OF ty_stock.

DATA: gt_stock  TYPE STANDARD TABLE OF ty_stock WITH HEADER LINE,
      gt_plants TYPE STANDARD TABLE OF t001w OCCURS 0 WITH HEADER LINE,
      gv_total  TYPE labst,
      gv_lines  TYPE i.

SELECTION-SCREEN BEGIN OF BLOCK b1 WITH FRAME TITLE text-001.
SELECT-OPTIONS: s_werks FOR mard-werks OBLIGATORY,
                s_matnr FOR mard-matnr,
                s_lgort FOR mard-lgort.
PARAMETERS: p_batch AS CHECKBOX DEFAULT 'X',
            p_zero  AS CHECKBOX.
SELECTION-SCREEN END OF BLOCK b1.

START-OF-SELECTION.

  PERFORM read_plants.
  PERFORM read_storage_location_stock.
  IF p_batch = 'X'.
    PERFORM read_batch_stock.
  ENDIF.
  PERFORM output_list.

*&---------------------------------------------------------------------*
*&      Form  READ_PLANTS
*&---------------------------------------------------------------------*
FORM read_plants.

  SELECT * FROM t001w
    INTO TABLE gt_plants
    WHERE werks IN s_werks.

  IF sy-subrc <> 0.
    MESSAGE 'No plants selected' TYPE 'E'.
  ENDIF.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_STORAGE_LOCATION_STOCK
*&---------------------------------------------------------------------*
* Reads the aggregated storage location stock directly from MARD.
* NOTE: LABST / INSME / SPEME are read straight off the table because
* the MB52 BAPI was too slow for the nightly full-network extract.
*&---------------------------------------------------------------------*
FORM read_storage_location_stock.

  DATA: lv_index TYPE sy-tabix.

  SELECT matnr werks lgort labst insme speme
    FROM mard
    INTO CORRESPONDING FIELDS OF TABLE gt_stock
    WHERE werks IN s_werks
      AND matnr IN s_matnr
      AND lgort IN s_lgort.

  LOOP AT gt_stock.
    lv_index = sy-tabix.

*   Plant level valuation view - one SELECT per material, historically
*   acceptable because the report ran overnight.
    SELECT SINGLE meins FROM marc
      INTO gt_stock-meins
      WHERE matnr = gt_stock-matnr
        AND werks = gt_stock-werks.

    IF sy-subrc <> 0.
      SELECT SINGLE meins FROM mara
        INTO gt_stock-meins
        WHERE matnr = gt_stock-matnr.
    ENDIF.

    IF p_zero IS INITIAL AND gt_stock-labst IS INITIAL
                        AND gt_stock-insme IS INITIAL
                        AND gt_stock-speme IS INITIAL.
      DELETE gt_stock INDEX lv_index.
      CONTINUE.
    ENDIF.

    MODIFY gt_stock INDEX lv_index.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_BATCH_STOCK
*&---------------------------------------------------------------------*
* Batch level stock from MCHB - required for expiry and cold chain
* reporting on the vaccines network.
*&---------------------------------------------------------------------*
FORM read_batch_stock.

  DATA: lt_batch TYPE STANDARD TABLE OF mchb WITH HEADER LINE.

  SELECT * FROM mchb
    INTO TABLE lt_batch
    WHERE werks IN s_werks
      AND matnr IN s_matnr
      AND lgort IN s_lgort
      AND ( clabs > 0 OR cinsm > 0 OR cspem > 0 ).

  LOOP AT lt_batch.
    CLEAR gt_stock.
    MOVE lt_batch-matnr TO gt_stock-matnr.
    MOVE lt_batch-werks TO gt_stock-werks.
    MOVE lt_batch-lgort TO gt_stock-lgort.
    MOVE lt_batch-charg TO gt_stock-charg.
    MOVE lt_batch-clabs TO gt_stock-labst.
    MOVE lt_batch-cinsm TO gt_stock-insme.
    MOVE lt_batch-cspem TO gt_stock-speme.
    APPEND gt_stock.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  OUTPUT_LIST
*&---------------------------------------------------------------------*
FORM output_list.

  SORT gt_stock BY werks lgort matnr charg.

  LOOP AT gt_stock.
    WRITE: / gt_stock-werks,
             gt_stock-lgort,
             gt_stock-matnr,
             gt_stock-charg,
             gt_stock-labst,
             gt_stock-insme,
             gt_stock-speme,
             gt_stock-meins.
    ADD gt_stock-labst TO gv_total.
  ENDLOOP.

  DESCRIBE TABLE gt_stock LINES gv_lines.
  SKIP 1.
  WRITE: / 'Lines:', gv_lines, 'Unrestricted total:', gv_total.

ENDFORM.
