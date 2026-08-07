*&---------------------------------------------------------------------*
*& Report  ZGSK_MM_BATCH_MOVEMENTS
*&---------------------------------------------------------------------*
*& Batch genealogy / material movement extract. Feeds the serialization
*& and track-and-trace reconciliation and the GMP batch record archive.
*&
*& Object owner : GSC Manufacturing IT
*& GxP class    : GxP-critical (batch traceability evidence)
*& Created      : 2011
*&---------------------------------------------------------------------*
REPORT zgsk_mm_batch_movements LINE-SIZE 220.

TABLES: mkpf, mseg.

TYPES: BEGIN OF ty_move,
         mblnr TYPE mblnr,
         mjahr TYPE mjahr,
         zeile TYPE mblpo,
         bwart TYPE bwart,
         matnr TYPE char18,
         werks TYPE werks_d,
         lgort TYPE lgort_d,
         charg TYPE charg_d,
         menge TYPE menge_d,
         meins TYPE meins,
         budat TYPE budat,
         usnam TYPE usnam,
       END OF ty_move.

DATA: gt_moves TYPE STANDARD TABLE OF ty_move WITH HEADER LINE,
      gt_head  TYPE STANDARD TABLE OF mkpf WITH HEADER LINE.

SELECT-OPTIONS: s_budat FOR mkpf-budat OBLIGATORY,
                s_werks FOR mseg-werks OBLIGATORY,
                s_charg FOR mseg-charg,
                s_bwart FOR mseg-bwart.

PARAMETERS: p_file TYPE localfile LOWER CASE.

START-OF-SELECTION.

  PERFORM select_documents.
  PERFORM select_items.
  PERFORM write_output.
  IF p_file IS NOT INITIAL.
    PERFORM download_extract.
  ENDIF.

*&---------------------------------------------------------------------*
*&      Form  SELECT_DOCUMENTS
*&---------------------------------------------------------------------*
FORM select_documents.

  SELECT * FROM mkpf
    INTO TABLE gt_head
    WHERE budat IN s_budat.

  IF gt_head[] IS INITIAL.
    MESSAGE 'No material documents in period' TYPE 'S' DISPLAY LIKE 'E'.
    LEAVE LIST-PROCESSING.
  ENDIF.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  SELECT_ITEMS
*&---------------------------------------------------------------------*
* Item level read from MSEG. The join back to MKPF is done in ABAP
* because the original 4.6C version pre-dated FOR ALL ENTRIES tuning.
*&---------------------------------------------------------------------*
FORM select_items.

  LOOP AT gt_head.

    SELECT mblnr mjahr zeile bwart matnr werks lgort charg menge meins
      FROM mseg
      INTO CORRESPONDING FIELDS OF TABLE gt_moves
      WHERE mblnr = gt_head-mblnr
        AND mjahr = gt_head-mjahr
        AND werks IN s_werks
        AND charg IN s_charg
        AND bwart IN s_bwart.

    LOOP AT gt_moves WHERE budat IS INITIAL.
      gt_moves-budat = gt_head-budat.
      gt_moves-usnam = gt_head-usnam.
      MODIFY gt_moves.
    ENDLOOP.

  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  WRITE_OUTPUT
*&---------------------------------------------------------------------*
FORM write_output.

  SORT gt_moves BY budat werks charg mblnr zeile.

  LOOP AT gt_moves.
    WRITE: / gt_moves-budat,
             gt_moves-mblnr,
             gt_moves-zeile,
             gt_moves-bwart,
             gt_moves-matnr,
             gt_moves-werks,
             gt_moves-charg,
             gt_moves-menge,
             gt_moves-meins,
             gt_moves-usnam.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  DOWNLOAD_EXTRACT
*&---------------------------------------------------------------------*
FORM download_extract.

  CALL FUNCTION 'WS_DOWNLOAD'
    EXPORTING
      filename = p_file
      filetype = 'DAT'
    TABLES
      data_tab = gt_moves
    EXCEPTIONS
      OTHERS   = 1.

  IF sy-subrc <> 0.
    MESSAGE 'Download failed' TYPE 'E'.
  ENDIF.

ENDFORM.
