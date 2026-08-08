*&---------------------------------------------------------------------*
*& Report  ZBIO_MD_PARTNER_SYNC
*&---------------------------------------------------------------------*
*& Partner master synchronisation for Vaccines. Loads customer and
*& supplier records from the Vaccines commercial data hub and writes
*& them into KNA1 / LFA1 directly.
*&
*& The core system has the same function in ZGSK_MD_CUSTOMER_SYNC.
*& Both write the legacy master tables, both have to move to Business
*& Partner with CVI, and both feed the same physical counterparties:
*& tender bodies, ministries of health and wholesalers that already
*& exist in the core system under a different number. That overlap is
*& the merge problem, not the conversion problem.
*&
*& Both ECC systems were configured from the same 1998 template, so
*& the customer range here is 21xxxx and the supplier range 51xxxx -
*& identical to the core system's. The numbers are not unique across
*& the estate: the same KUNNR in the two systems is usually two
*& different companies. Any merge that keys on the legacy number
*& rather than on the legal entity will silently combine unrelated
*& partners, so the target BP numbers cannot be carried over.
*&
*& Source system : GVP (GSK Vaccines ECC 6.0)
*& Object owner  : Vaccines Commercial Data
*& GxP class     : GxP-relevant (ship-to controls product distribution)
*& Validation    : CSV package BIO-MDM-001
*&---------------------------------------------------------------------*
REPORT zbio_md_partner_sync.

TABLES: kna1, lfa1, knb1, lfb1.

TYPES: BEGIN OF ty_feed,
         partner_role TYPE c LENGTH 1,
         extern_id    TYPE c LENGTH 20,
         name1        TYPE name1_gp,
         land1        TYPE land1_gp,
         ort01        TYPE ort01_gp,
         pstlz        TYPE pstlz,
         stras        TYPE stras_gp,
         stceg        TYPE stceg,
         bukrs        TYPE bukrs,
         akont        TYPE akont,
         gmp_audit    TYPE c LENGTH 1,
       END OF ty_feed.

DATA: gt_feed  TYPE STANDARD TABLE OF ty_feed WITH HEADER LINE,
      gs_kna1  TYPE kna1,
      gs_lfa1  TYPE lfa1,
      gv_next  TYPE kunnr,
      gv_lifnr TYPE lifnr,
      gv_ok    TYPE i,
      gv_err   TYPE i.

PARAMETERS: p_file TYPE localfile LOWER CASE OBLIGATORY,
            p_test AS CHECKBOX DEFAULT 'X'.

START-OF-SELECTION.

  PERFORM load_feed.
  PERFORM apply_feed.
  WRITE: / 'Applied:', gv_ok, 'Errors:', gv_err.

*&---------------------------------------------------------------------*
*&      Form  LOAD_FEED
*&---------------------------------------------------------------------*
FORM load_feed.

  CALL FUNCTION 'WS_UPLOAD'
    EXPORTING
      filename = p_file
      filetype = 'DAT'
    TABLES
      data_tab = gt_feed
    EXCEPTIONS
      OTHERS   = 1.

  IF sy-subrc <> 0.
    MESSAGE 'Partner feed could not be read' TYPE 'E'.
  ENDIF.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  APPLY_FEED
*&---------------------------------------------------------------------*
* Direct writes to the master tables. No BAPI, no CVI, and a commit
* per record so a failed row does not roll back the ones before it.
*&---------------------------------------------------------------------*
FORM apply_feed.

  LOOP AT gt_feed.

    IF gt_feed-partner_role = 'C'.

      SELECT SINGLE kunnr FROM kna1
        INTO gv_next
        WHERE stceg = gt_feed-stceg
          AND land1 = gt_feed-land1.

      IF sy-subrc <> 0.
        PERFORM next_customer_number CHANGING gv_next.
      ENDIF.

      CLEAR gs_kna1.
      gs_kna1-mandt = sy-mandt.
      gs_kna1-kunnr = gv_next.
      gs_kna1-name1 = gt_feed-name1.
      gs_kna1-land1 = gt_feed-land1.
      gs_kna1-ort01 = gt_feed-ort01.
      gs_kna1-pstlz = gt_feed-pstlz.
      gs_kna1-stras = gt_feed-stras.
      gs_kna1-stceg = gt_feed-stceg.

      IF p_test IS INITIAL.
        MODIFY kna1 FROM gs_kna1.
        IF sy-subrc = 0.
          ADD 1 TO gv_ok.
        ELSE.
          ADD 1 TO gv_err.
        ENDIF.
        COMMIT WORK.
      ENDIF.

    ELSE.

      SELECT SINGLE lifnr FROM lfa1
        INTO gv_lifnr
        WHERE stceg = gt_feed-stceg
          AND land1 = gt_feed-land1.

      IF sy-subrc <> 0.
        PERFORM next_vendor_number CHANGING gv_lifnr.
      ENDIF.

      CLEAR gs_lfa1.
      gs_lfa1-mandt = sy-mandt.
      gs_lfa1-lifnr = gv_lifnr.
      gs_lfa1-name1 = gt_feed-name1.
      gs_lfa1-land1 = gt_feed-land1.
      gs_lfa1-ort01 = gt_feed-ort01.
      gs_lfa1-pstlz = gt_feed-pstlz.
      gs_lfa1-stras = gt_feed-stras.
      gs_lfa1-stceg = gt_feed-stceg.

      IF p_test IS INITIAL.
        MODIFY lfa1 FROM gs_lfa1.
        IF sy-subrc = 0.
          ADD 1 TO gv_ok.
        ELSE.
          ADD 1 TO gv_err.
        ENDIF.
        COMMIT WORK.
      ENDIF.

    ENDIF.

  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  NEXT_CUSTOMER_NUMBER
*&---------------------------------------------------------------------*
FORM next_customer_number CHANGING cv_kunnr TYPE kunnr.

  SELECT MAX( kunnr ) FROM kna1
    INTO cv_kunnr
    WHERE kunnr BETWEEN '0000210000' AND '0000219999'.

  cv_kunnr = cv_kunnr + 1.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  NEXT_VENDOR_NUMBER
*&---------------------------------------------------------------------*
FORM next_vendor_number CHANGING cv_lifnr TYPE lifnr.

  SELECT MAX( lifnr ) FROM lfa1
    INTO cv_lifnr
    WHERE lifnr BETWEEN '0000510000' AND '0000519999'.

  cv_lifnr = cv_lifnr + 1.

ENDFORM.
