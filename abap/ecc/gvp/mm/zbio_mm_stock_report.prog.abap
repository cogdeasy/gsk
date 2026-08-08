*&---------------------------------------------------------------------*
*& Report  ZBIO_MM_STOCK_REPORT
*&---------------------------------------------------------------------*
*& Stock overview for the Vaccines network. Same business question as
*& ZGSK_MM_STOCK_OVERVIEW in the core system, written independently by
*& the Bio team, so the field set, the selection screen and the
*& treatment of quality inspection stock all differ.
*&
*& The Vaccines-specific part is the storage condition split: antigen
*& bulk and filled product are held at -70C, 2-8C and 15-25C, and
*& stock has to be readable per condition because a deviation moves
*& material straight to blocked.
*&
*& Source system : GVP (GSK Vaccines ECC 6.0)
*& Object owner  : Vaccines Supply Chain IT
*& GxP class     : GxP-relevant
*&---------------------------------------------------------------------*
REPORT zbio_mm_stock_report LINE-SIZE 200.

TABLES: mard, mchb, mara, marc.

TYPES: BEGIN OF ty_stock,
         werks      TYPE werks_d,
         lgort      TYPE lgort_d,
         matnr      TYPE char18,
         charg      TYPE charg_d,
         labst      TYPE labst,
         insme      TYPE insme,
         speme      TYPE speme,
         meins      TYPE meins,
         temp_class TYPE c LENGTH 10,
         raube      TYPE raube,
       END OF ty_stock.

DATA: gt_stock TYPE STANDARD TABLE OF ty_stock WITH HEADER LINE,
      gt_bulk  TYPE STANDARD TABLE OF ty_stock WITH HEADER LINE.

SELECT-OPTIONS: s_werks FOR mard-werks OBLIGATORY,
                s_matnr FOR mard-matnr,
                s_lgort FOR mard-lgort.
PARAMETERS: p_batch AS CHECKBOX DEFAULT 'X',
            p_cold  AS CHECKBOX.

START-OF-SELECTION.

  PERFORM read_unbatched.
  IF p_batch = 'X'.
    PERFORM read_batched.
  ENDIF.
  PERFORM read_storage_condition.
  PERFORM output.

*&---------------------------------------------------------------------*
*&      Form  READ_UNBATCHED
*&---------------------------------------------------------------------*
FORM read_unbatched.

  SELECT werks lgort matnr labst insme speme
    FROM mard
    INTO CORRESPONDING FIELDS OF TABLE gt_stock
    WHERE werks IN s_werks
      AND matnr IN s_matnr
      AND lgort IN s_lgort.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_BATCHED
*&---------------------------------------------------------------------*
* Batch stock from MCHB. Everything in this system is batch managed,
* so in practice this is the branch that runs.
*&---------------------------------------------------------------------*
FORM read_batched.

  SELECT werks lgort matnr charg clabs cinsm cspem
    FROM mchb
    INTO CORRESPONDING FIELDS OF TABLE gt_bulk
    WHERE werks IN s_werks
      AND matnr IN s_matnr
      AND lgort IN s_lgort.

  LOOP AT gt_bulk.
    gt_stock = gt_bulk.
    APPEND gt_stock.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_STORAGE_CONDITION
*&---------------------------------------------------------------------*
* Storage condition drives the cold chain split. RAUBE comes from the
* material master, the temperature class from the Bio-specific append
* structure on MARA.
*&---------------------------------------------------------------------*
FORM read_storage_condition.

  LOOP AT gt_stock.

    SELECT SINGLE raube meins zz_temp_class FROM mara
      INTO (gt_stock-raube, gt_stock-meins, gt_stock-temp_class)
      WHERE matnr = gt_stock-matnr.

    IF p_cold = 'X' AND gt_stock-temp_class NA '-70C2-8C'.
      DELETE gt_stock.
      CONTINUE.
    ENDIF.

    MODIFY gt_stock.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  OUTPUT
*&---------------------------------------------------------------------*
FORM output.

  DATA: lv_total TYPE labst,
        lv_qi    TYPE insme.

  SORT gt_stock BY werks lgort matnr charg.

  LOOP AT gt_stock.
    WRITE: / gt_stock-werks,
             gt_stock-lgort,
             gt_stock-matnr,
             gt_stock-charg,
             gt_stock-temp_class,
             gt_stock-labst,
             gt_stock-insme,
             gt_stock-speme,
             gt_stock-meins.
    ADD gt_stock-labst TO lv_total.
    ADD gt_stock-insme TO lv_qi.
  ENDLOOP.

  WRITE: / 'Unrestricted:', lv_total.
  WRITE: / 'In quality inspection:', lv_qi.

ENDFORM.
