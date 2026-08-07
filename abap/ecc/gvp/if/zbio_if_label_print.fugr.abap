*&---------------------------------------------------------------------*
*& Function group ZBIO_IF_LABEL_PRINT
*&---------------------------------------------------------------------*
*& Label printing interface to Loftware for the Vaccines network.
*&
*& Functionally the same interface as ZGSK_IF_LABEL_PRINT in the core
*& system - same middleware, same print server estate - but written
*& separately, triggered from process order confirmation rather than
*& delivery, and carrying the serialisation fields the FMD aggregation
*& step needs. Two implementations of one interface: they converge to
*& one S/4HANA object and one output management configuration.
*&
*& Source system : GVP (GSK Vaccines ECC 6.0)
*& Object owner  : Vaccines Manufacturing IT (Wavre)
*& GxP class     : GxP-critical (product labelling, Annex 11)
*&---------------------------------------------------------------------*

FUNCTION zbio_label_print_confirm.
*"----------------------------------------------------------------------
*"*"Local Interface:
*"  IMPORTING
*"     VALUE(IS_NAST) TYPE  NAST
*"     VALUE(IV_AUFNR) TYPE  AUFNR
*"  EXPORTING
*"     VALUE(EV_RETCODE) TYPE  SY-SUBRC
*"----------------------------------------------------------------------

  DATA: lt_afpo    TYPE STANDARD TABLE OF afpo WITH HEADER LINE,
        lt_payload TYPE STANDARD TABLE OF zbio_label_line WITH HEADER LINE,
        lv_printer TYPE rspopname,
        lv_dest    TYPE rfcdest,
        lv_matnr   TYPE char18,
        lv_gtin    TYPE c LENGTH 14.

  CLEAR ev_retcode.

  SELECT * FROM afpo
    INTO TABLE lt_afpo
    WHERE aufnr = iv_aufnr.

  IF sy-subrc <> 0.
    ev_retcode = 4.
    EXIT.
  ENDIF.

  LOOP AT lt_afpo.

    CLEAR lt_payload.
    lv_matnr = lt_afpo-matnr.

*   Fixed width 18 character material number, as the label templates
*   were built against it.
    lt_payload-matnr = lv_matnr(18).
    lt_payload-charg = lt_afpo-charg.
    lt_payload-psmng = lt_afpo-psmng.
    lt_payload-meins = lt_afpo-umrez.
    lt_payload-aufnr = iv_aufnr.

    SELECT SINGLE maktx FROM makt
      INTO lt_payload-maktx
      WHERE matnr = lt_afpo-matnr
        AND spras = sy-langu.

*   Serialisation identifiers for the FMD aggregation step.
    SELECT SINGLE gtin FROM zbio_gtin_map
      INTO lv_gtin
      WHERE matnr = lt_afpo-matnr.

    lt_payload-gtin  = lv_gtin.
    lt_payload-vfdat = lt_afpo-vfdat.

    APPEND lt_payload.
  ENDLOOP.

  PERFORM determine_printer USING is_nast CHANGING lv_printer lv_dest.

  CALL FUNCTION 'Z_LOFTWARE_PRINT_REQUEST'
    DESTINATION lv_dest
    EXPORTING
      iv_printer    = lv_printer
      iv_template   = 'BIO_VIAL_CARTON'
      iv_object_key = is_nast-objky
    TABLES
      it_payload    = lt_payload
    EXCEPTIONS
      communication_failure = 1
      system_failure        = 2
      OTHERS                = 3.

  IF sy-subrc <> 0.
    ev_retcode = sy-subrc.
    UPDATE nast SET vstat = '2'
                WHERE kappl = is_nast-kappl
                  AND objky = is_nast-objky
                  AND kschl = is_nast-kschl
                  AND spras = is_nast-spras
                  AND parnr = is_nast-parnr
                  AND parvw = is_nast-parvw.
    COMMIT WORK.
  ENDIF.

ENDFUNCTION.

*&---------------------------------------------------------------------*
*&      Form  DETERMINE_PRINTER
*&---------------------------------------------------------------------*
* Printer determination reads a Bio-specific mapping table. The core
* system has the equivalent in ZGSK_PRINTER_MAP with a different key,
* so the merged object needs one harmonised determination.
*&---------------------------------------------------------------------*
FORM determine_printer USING is_nast TYPE nast
                    CHANGING cv_printer TYPE rspopname
                             cv_dest    TYPE rfcdest.

  DATA: lv_werks TYPE werks_d,
        lv_arbpl TYPE arbpl.

  SELECT SINGLE werks arbpl FROM zbio_line_map
    INTO (lv_werks, lv_arbpl)
    WHERE objky = is_nast-objky.

  SELECT SINGLE printer rfcdest FROM zbio_printer_map
    INTO (cv_printer, cv_dest)
    WHERE werks = lv_werks
      AND arbpl = lv_arbpl.

  IF sy-subrc <> 0.
    cv_printer = 'LP01'.
    cv_dest    = 'LOFTWARE_BIO_PRD'.
  ENDIF.

ENDFORM.
