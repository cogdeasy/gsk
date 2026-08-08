*&---------------------------------------------------------------------*
*& Report  ZBIO_MM_BATCH_GENEALOGY
*&---------------------------------------------------------------------*
*& Batch genealogy for Vaccines. Walks the lineage from filled and
*& packed product back through drug substance to the antigen bulk
*& campaign, which is the evidence a Vaccines batch record needs and
*& the core system's ZGSK_MM_BATCH_MOVEMENTS does not produce - that
*& one stops at a flat movement list.
*&
*& The two reports read the same ECC tables for the same purpose and
*& converge onto one S/4HANA object; the genealogy walk is the
*& capability the merged object has to keep.
*&
*& Source system : GVP (GSK Vaccines ECC 6.0)
*& Object owner  : Vaccines Manufacturing IT (Wavre)
*& GxP class     : GxP-critical (batch traceability evidence)
*& Created       : 2009, last major change 2016 (RSV campaign)
*&---------------------------------------------------------------------*
REPORT zbio_mm_batch_genealogy LINE-SIZE 240.

TABLES: mkpf, mseg, mcha.

TYPES: BEGIN OF ty_move,
         mblnr TYPE mblnr,
         mjahr TYPE mjahr,
         zeile TYPE mblpo,
         bwart TYPE bwart,
         matnr TYPE char18,
         werks TYPE werks_d,
         charg TYPE charg_d,
         menge TYPE menge_d,
         meins TYPE meins,
         aufnr TYPE aufnr,
         budat TYPE budat,
         shkzg TYPE shkzg,
       END OF ty_move.

TYPES: BEGIN OF ty_lineage,
         level        TYPE i,
         child_matnr  TYPE char18,
         child_charg  TYPE charg_d,
         parent_matnr TYPE char18,
         parent_charg TYPE charg_d,
         aufnr        TYPE aufnr,
         menge        TYPE menge_d,
       END OF ty_lineage.

DATA: gt_move    TYPE STANDARD TABLE OF ty_move WITH HEADER LINE,
      gt_lineage TYPE STANDARD TABLE OF ty_lineage WITH HEADER LINE,
      gv_level   TYPE i.

CONSTANTS: c_max_level TYPE i VALUE 6.

SELECT-OPTIONS: s_werks FOR mseg-werks OBLIGATORY,
                s_charg FOR mseg-charg OBLIGATORY.
PARAMETERS: p_levels TYPE i DEFAULT 4,
            p_file   TYPE localfile LOWER CASE.

START-OF-SELECTION.

  PERFORM read_movements.
  PERFORM walk_lineage.
  PERFORM output.
  IF p_file IS NOT INITIAL.
    PERFORM download.
  ENDIF.

*&---------------------------------------------------------------------*
*&      Form  READ_MOVEMENTS
*&---------------------------------------------------------------------*
FORM read_movements.

  DATA: lt_head TYPE STANDARD TABLE OF mkpf WITH HEADER LINE.

  SELECT * FROM mkpf
    INTO TABLE lt_head
    WHERE budat >= '20200101'.

  LOOP AT lt_head.

    SELECT mblnr mjahr zeile bwart matnr werks charg menge meins aufnr shkzg
      FROM mseg
      APPENDING CORRESPONDING FIELDS OF TABLE gt_move
      WHERE mblnr = lt_head-mblnr
        AND mjahr = lt_head-mjahr
        AND werks IN s_werks.

  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  WALK_LINEAGE
*&---------------------------------------------------------------------*
* Genealogy walk. For each batch in scope, the process order that
* produced it (movement type 101) gives the components consumed
* against the same order (261), and those component batches become the
* next level up. Antigen bulk sits at the top.
*&---------------------------------------------------------------------*
FORM walk_lineage.

  DATA: lt_current TYPE STANDARD TABLE OF ty_move WITH HEADER LINE,
        lv_aufnr   TYPE aufnr.

  LOOP AT gt_move WHERE charg IN s_charg AND bwart = '101'.
    lt_current = gt_move.
    APPEND lt_current.
  ENDLOOP.

  gv_level = 1.

  WHILE gv_level <= p_levels AND gv_level <= c_max_level.

    LOOP AT lt_current.

      lv_aufnr = lt_current-aufnr.

      SELECT matnr charg menge FROM mseg
        INTO (gt_lineage-parent_matnr, gt_lineage-parent_charg, gt_lineage-menge)
        WHERE aufnr = lv_aufnr
          AND bwart = '261'.

        gt_lineage-level       = gv_level.
        gt_lineage-child_matnr = lt_current-matnr.
        gt_lineage-child_charg = lt_current-charg.
        gt_lineage-aufnr       = lv_aufnr.
        APPEND gt_lineage.

      ENDSELECT.

    ENDLOOP.

    CLEAR lt_current[].
    LOOP AT gt_lineage WHERE level = gv_level.
      lt_current-matnr = gt_lineage-parent_matnr.
      lt_current-charg = gt_lineage-parent_charg.

      SELECT SINGLE aufnr FROM mseg
        INTO lt_current-aufnr
        WHERE charg = gt_lineage-parent_charg
          AND bwart = '101'.

      IF sy-subrc = 0.
        APPEND lt_current.
      ENDIF.
    ENDLOOP.

    gv_level = gv_level + 1.

  ENDWHILE.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  OUTPUT
*&---------------------------------------------------------------------*
FORM output.

  DATA: lv_vfdat TYPE vfdat.

  SORT gt_lineage BY level child_charg parent_charg.

  LOOP AT gt_lineage.

    SELECT SINGLE vfdat FROM mcha
      INTO lv_vfdat
      WHERE matnr = gt_lineage-parent_matnr
        AND charg = gt_lineage-parent_charg.

    WRITE: / gt_lineage-level,
             gt_lineage-child_matnr,
             gt_lineage-child_charg,
             gt_lineage-parent_matnr,
             gt_lineage-parent_charg,
             gt_lineage-aufnr,
             gt_lineage-menge,
             lv_vfdat.
  ENDLOOP.

  WRITE: / 'Lineage rows:', lines( gt_lineage ).

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  DOWNLOAD
*&---------------------------------------------------------------------*
FORM download.

  CALL FUNCTION 'WS_DOWNLOAD'
    EXPORTING
      filename = p_file
      filetype = 'DAT'
    TABLES
      data_tab = gt_lineage
    EXCEPTIONS
      OTHERS   = 1.

  IF sy-subrc <> 0.
    MESSAGE 'Genealogy download failed' TYPE 'E'.
  ENDIF.

ENDFORM.
