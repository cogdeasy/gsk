*&---------------------------------------------------------------------*
*& Report  ZGSK_MD_CUSTOMER_SYNC
*&---------------------------------------------------------------------*
*& Nightly synchronisation of customer and vendor master from the
*& global MDM hub into ECC. Creates and updates customers (KNA1/KNB1)
*& and suppliers (LFA1/LFB1) directly.
*&
*& Object owner : Enterprise Data & Analytics
*& GxP class    : GxP-relevant (ship-to sites for clinical supply)
*& Created      : 2013
*&---------------------------------------------------------------------*
REPORT zgsk_md_customer_sync.

TABLES: kna1, knb1, lfa1, lfb1.

TYPES: BEGIN OF ty_feed,
         partner_type TYPE c LENGTH 1,
         partner_id   TYPE char10,
         name1        TYPE name1_gp,
         land1        TYPE land1_gp,
         ort01        TYPE ort01_gp,
         pstlz        TYPE pstlz,
         stras        TYPE stras_gp,
         bukrs        TYPE bukrs,
         akont        TYPE akont,
         zterm        TYPE dzterm,
         gxp_flag     TYPE c LENGTH 1,
       END OF ty_feed.

DATA: gt_feed  TYPE STANDARD TABLE OF ty_feed WITH HEADER LINE,
      gv_ok    TYPE i,
      gv_error TYPE i.

PARAMETERS: p_infile TYPE localfile LOWER CASE OBLIGATORY,
            p_test   AS CHECKBOX DEFAULT 'X'.

START-OF-SELECTION.

  PERFORM load_feed.
  PERFORM process_customers.
  PERFORM process_vendors.

  WRITE: / 'Processed OK:', gv_ok, 'Errors:', gv_error.

*&---------------------------------------------------------------------*
*&      Form  LOAD_FEED
*&---------------------------------------------------------------------*
FORM load_feed.

  CALL FUNCTION 'WS_UPLOAD'
    EXPORTING
      filename                = p_infile
      filetype                = 'DAT'
    TABLES
      data_tab                = gt_feed
    EXCEPTIONS
      file_open_error         = 1
      OTHERS                  = 2.

  IF sy-subrc <> 0.
    MESSAGE 'Cannot read MDM feed file' TYPE 'E'.
  ENDIF.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  PROCESS_CUSTOMERS
*&---------------------------------------------------------------------*
* Customers are written straight to the master data tables. The BAPI
* was not used because the MDM hub owns the number range and the BAPI
* refused externally supplied numbers on this release.
*&---------------------------------------------------------------------*
FORM process_customers.

  DATA: ls_kna1 TYPE kna1,
        ls_knb1 TYPE knb1.

  LOOP AT gt_feed WHERE partner_type = 'C'.

    CLEAR ls_kna1.
    ls_kna1-mandt = sy-mandt.
    ls_kna1-kunnr = gt_feed-partner_id.
    ls_kna1-name1 = gt_feed-name1.
    ls_kna1-land1 = gt_feed-land1.
    ls_kna1-ort01 = gt_feed-ort01.
    ls_kna1-pstlz = gt_feed-pstlz.
    ls_kna1-stras = gt_feed-stras.
    ls_kna1-erdat = sy-datum.
    ls_kna1-ernam = sy-uname.

    IF p_test IS INITIAL.
      MODIFY kna1 FROM ls_kna1.
      IF sy-subrc = 0.
        ADD 1 TO gv_ok.
      ELSE.
        ADD 1 TO gv_error.
        CONTINUE.
      ENDIF.

      CLEAR ls_knb1.
      ls_knb1-mandt = sy-mandt.
      ls_knb1-kunnr = gt_feed-partner_id.
      ls_knb1-bukrs = gt_feed-bukrs.
      ls_knb1-akont = gt_feed-akont.
      ls_knb1-zterm = gt_feed-zterm.
      MODIFY knb1 FROM ls_knb1.

      COMMIT WORK.
    ELSE.
      WRITE: / 'TEST customer', gt_feed-partner_id, gt_feed-name1.
    ENDIF.

  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  PROCESS_VENDORS
*&---------------------------------------------------------------------*
FORM process_vendors.

  DATA: ls_lfa1 TYPE lfa1,
        ls_lfb1 TYPE lfb1.

  LOOP AT gt_feed WHERE partner_type = 'V'.

    CLEAR ls_lfa1.
    ls_lfa1-mandt = sy-mandt.
    ls_lfa1-lifnr = gt_feed-partner_id.
    ls_lfa1-name1 = gt_feed-name1.
    ls_lfa1-land1 = gt_feed-land1.
    ls_lfa1-ort01 = gt_feed-ort01.
    ls_lfa1-pstlz = gt_feed-pstlz.
    ls_lfa1-stras = gt_feed-stras.
    ls_lfa1-erdat = sy-datum.
    ls_lfa1-ernam = sy-uname.

    IF p_test IS INITIAL.
      MODIFY lfa1 FROM ls_lfa1.

      CLEAR ls_lfb1.
      ls_lfb1-mandt = sy-mandt.
      ls_lfb1-lifnr = gt_feed-partner_id.
      ls_lfb1-bukrs = gt_feed-bukrs.
      ls_lfb1-akont = gt_feed-akont.
      MODIFY lfb1 FROM ls_lfb1.

      COMMIT WORK.
      ADD 1 TO gv_ok.
    ELSE.
      WRITE: / 'TEST vendor', gt_feed-partner_id, gt_feed-name1.
    ENDIF.

  ENDLOOP.

ENDFORM.
