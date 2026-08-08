*&---------------------------------------------------------------------*
*& Report  ZGSK_FI_ICT_MARGIN
*&---------------------------------------------------------------------*
*& Intercompany profit tracking (ICT) - unrealised margin in stock.
*& Reads FI documents and CO line items to derive the intercompany
*& mark-up carried in inventory at period end.
*&
*& Object owner : Global Financial Services
*& GxP class    : Non-GxP (SOX relevant)
*& Created      : 2008
*& Last change  : 2022 - added vaccines company codes
*&---------------------------------------------------------------------*
REPORT zgsk_fi_ict_margin.

TABLES: bkpf, bseg, bsis, coep.

TYPES: BEGIN OF ty_line,
         bukrs TYPE bukrs,
         gjahr TYPE gjahr,
         monat TYPE monat,
         belnr TYPE belnr_d,
         buzei TYPE buzei,
         hkont TYPE hkont,
         kostl TYPE kostl,
         prctr TYPE prctr,
         dmbtr TYPE dmbtr,
         wrbtr TYPE wrbtr,
         waers TYPE waers,
         shkzg TYPE shkzg,
       END OF ty_line.

DATA: gt_lines  TYPE STANDARD TABLE OF ty_line WITH HEADER LINE,
      gt_bkpf   TYPE STANDARD TABLE OF bkpf WITH HEADER LINE,
      gv_margin TYPE dmbtr.

SELECT-OPTIONS: s_bukrs FOR bkpf-bukrs OBLIGATORY,
                s_gjahr FOR bkpf-gjahr OBLIGATORY NO-EXTENSION NO INTERVALS,
                s_monat FOR bkpf-monat,
                s_hkont FOR bseg-hkont.

START-OF-SELECTION.

  PERFORM read_fi_documents.
  PERFORM read_open_items.
  PERFORM read_co_line_items.
  PERFORM calculate_margin.

*&---------------------------------------------------------------------*
*&      Form  READ_FI_DOCUMENTS
*&---------------------------------------------------------------------*
FORM read_fi_documents.

  SELECT * FROM bkpf
    INTO TABLE gt_bkpf
    WHERE bukrs IN s_bukrs
      AND gjahr IN s_gjahr
      AND monat IN s_monat.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_OPEN_ITEMS
*&---------------------------------------------------------------------*
* G/L open items are read from the secondary index BSIS rather than
* from BSEG for performance on the ECC database.
*&---------------------------------------------------------------------*
FORM read_open_items.

  SELECT bukrs gjahr monat belnr buzei hkont dmbtr wrbtr waers shkzg
    FROM bsis
    INTO CORRESPONDING FIELDS OF TABLE gt_lines
    WHERE bukrs IN s_bukrs
      AND gjahr IN s_gjahr
      AND hkont IN s_hkont.

  LOOP AT gt_lines.

*   Profit centre is not in BSIS on this release, read it from BSEG.
    SELECT SINGLE prctr kostl FROM bseg
      INTO (gt_lines-prctr, gt_lines-kostl)
      WHERE bukrs = gt_lines-bukrs
        AND belnr = gt_lines-belnr
        AND gjahr = gt_lines-gjahr
        AND buzei = gt_lines-buzei.

    MODIFY gt_lines.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_CO_LINE_ITEMS
*&---------------------------------------------------------------------*
FORM read_co_line_items.

  DATA: lt_coep TYPE STANDARD TABLE OF coep WITH HEADER LINE.

  SELECT * FROM coep
    INTO TABLE lt_coep
    WHERE gjahr IN s_gjahr
      AND perio IN s_monat.

  LOOP AT lt_coep.
    ADD lt_coep-wtgbtr TO gv_margin.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  CALCULATE_MARGIN
*&---------------------------------------------------------------------*
FORM calculate_margin.

  DATA: lv_debit  TYPE dmbtr,
        lv_credit TYPE dmbtr.

  LOOP AT gt_lines.
    IF gt_lines-shkzg = 'S'.
      ADD gt_lines-dmbtr TO lv_debit.
    ELSE.
      ADD gt_lines-dmbtr TO lv_credit.
    ENDIF.
  ENDLOOP.

  gv_margin = lv_debit - lv_credit.

  WRITE: / 'Unrealised intercompany margin:', gv_margin.

ENDFORM.
