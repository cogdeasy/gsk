*&---------------------------------------------------------------------*
*& Function group ZGSK_IF_LABEL_PRINT
*&---------------------------------------------------------------------*
*& Label printing interface to Loftware. Triggered from output
*& determination (NAST) on delivery and process order confirmation,
*& sends label payloads by RFC to the Loftware print server which
*& drives ~3,500 printers across the network.
*&
*& Object owner : GSC Manufacturing IT
*& GxP class    : GxP-critical (product labelling, Annex 11)
*&---------------------------------------------------------------------*

FUNCTION zgsk_label_print_delivery.
*"----------------------------------------------------------------------
*"*"Local Interface:
*"  IMPORTING
*"     VALUE(IS_NAST) TYPE  NAST
*"     VALUE(IV_PROCESSING_MODE) TYPE  C DEFAULT '1'
*"  EXPORTING
*"     VALUE(EV_RETCODE) TYPE  SY-SUBRC
*"----------------------------------------------------------------------

  DATA: lt_lips     TYPE STANDARD TABLE OF lips WITH HEADER LINE,
        ls_likp     TYPE likp,
        lt_payload  TYPE STANDARD TABLE OF zgsk_label_line WITH HEADER LINE,
        lv_printer  TYPE rspopname,
        lv_matnr    TYPE char18,
        lv_dest     TYPE rfcdest.

  CLEAR ev_retcode.

  SELECT SINGLE * FROM likp INTO ls_likp WHERE vbeln = is_nast-objky.
  IF sy-subrc <> 0.
    ev_retcode = 4.
    EXIT.
  ENDIF.

  SELECT * FROM lips
    INTO TABLE lt_lips
    WHERE vbeln = ls_likp-vbeln.

  LOOP AT lt_lips.

    CLEAR lt_payload.
    lv_matnr = lt_lips-matnr.

*   Legacy 18 character material number is padded and passed to the
*   label template as a fixed width field.
    lt_payload-matnr    = lv_matnr(18).
    lt_payload-charg    = lt_lips-charg.
    lt_payload-lfimg    = lt_lips-lfimg.
    lt_payload-vrkme    = lt_lips-vrkme.
    lt_payload-werks    = lt_lips-werks.
    lt_payload-vbeln    = ls_likp-vbeln.
    lt_payload-posnr    = lt_lips-posnr.

    SELECT SINGLE maktx FROM makt
      INTO lt_payload-maktx
      WHERE matnr = lt_lips-matnr
        AND spras = sy-langu.

    APPEND lt_payload.
  ENDLOOP.

  PERFORM determine_printer USING is_nast CHANGING lv_printer lv_dest.

  CALL FUNCTION 'Z_LOFTWARE_PRINT_REQUEST'
    DESTINATION lv_dest
    EXPORTING
      iv_printer      = lv_printer
      iv_template     = 'GSK_DELIVERY_CARTON'
      iv_object_key   = is_nast-objky
    TABLES
      it_payload      = lt_payload
    EXCEPTIONS
      communication_failure = 1
      system_failure        = 2
      OTHERS                = 3.

  IF sy-subrc <> 0.
    ev_retcode = sy-subrc.
*   Update the NAST processing status so RSNAST00 can repeat the send.
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
FORM determine_printer USING is_nast TYPE nast
                    CHANGING cv_printer TYPE rspopname
                             cv_dest    TYPE rfcdest.

  DATA: lv_werks TYPE werks_d.

  SELECT SINGLE werks FROM lips INTO lv_werks WHERE vbeln = is_nast-objky.

  SELECT SINGLE printer rfcdest FROM zgsk_printer_map
    INTO (cv_printer, cv_dest)
    WHERE werks = lv_werks
      AND kschl = is_nast-kschl.

  IF sy-subrc <> 0.
    cv_printer = 'LP01'.
    cv_dest    = 'LOFTWARE_PRD'.
  ENDIF.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  REPRINT_FAILED
*&---------------------------------------------------------------------*
* Re-queues failed label output records for RSNAST00.
*&---------------------------------------------------------------------*
FORM reprint_failed USING iv_objky TYPE na_objkey.

  DATA: lt_nast TYPE STANDARD TABLE OF nast WITH HEADER LINE.

  SELECT * FROM nast
    INTO TABLE lt_nast
    CLIENT SPECIFIED
    WHERE mandt = sy-mandt
      AND objky = iv_objky
      AND vstat = '2'.

  LOOP AT lt_nast.
    lt_nast-vstat = '0'.
    MODIFY nast FROM lt_nast.
  ENDLOOP.

  COMMIT WORK.

ENDFORM.
