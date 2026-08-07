*&---------------------------------------------------------------------*
*& Report  ZGSK_IF_MES_CONFIRMATION
*&---------------------------------------------------------------------*
*& Inbound production confirmation interface from site MES systems.
*& Reads staged IDoc segments, posts process order confirmations and
*& goods movements, and writes an interface audit record.
*&
*& Object owner : GSC Manufacturing IT
*& GxP class    : GxP-critical (electronic batch record data flow)
*&---------------------------------------------------------------------*
REPORT zgsk_if_mes_confirmation.

TABLES: edidc, edid4, zgsk_if_audit.

TYPES: BEGIN OF ty_conf,
         docnum TYPE edi_docnum,
         aufnr  TYPE aufnr,
         vornr  TYPE vornr,
         matnr  TYPE char18,
         charg  TYPE charg_d,
         werks  TYPE werks_d,
         gmnga  TYPE gamng,
         meins  TYPE meins,
         budat  TYPE budat,
         status TYPE c LENGTH 1,
         msgtx  TYPE char120,
       END OF ty_conf.

DATA: gt_conf  TYPE STANDARD TABLE OF ty_conf WITH HEADER LINE,
      gt_edidc TYPE STANDARD TABLE OF edidc WITH HEADER LINE,
      gv_posted TYPE i,
      gv_failed TYPE i.

SELECT-OPTIONS: s_credat FOR edidc-credat OBLIGATORY,
                s_sndprn FOR edidc-sndprn.
PARAMETERS: p_commit TYPE i DEFAULT 50.

START-OF-SELECTION.

  PERFORM read_idocs.
  PERFORM parse_segments.
  PERFORM post_confirmations.
  PERFORM write_audit.

  WRITE: / 'Posted:', gv_posted, 'Failed:', gv_failed.

*&---------------------------------------------------------------------*
*&      Form  READ_IDOCS
*&---------------------------------------------------------------------*
FORM read_idocs.

  SELECT * FROM edidc
    INTO TABLE gt_edidc
    WHERE credat IN s_credat
      AND sndprn IN s_sndprn
      AND mestyp = 'LOIPRO'
      AND status = '64'.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  PARSE_SEGMENTS
*&---------------------------------------------------------------------*
FORM parse_segments.

  DATA: lt_data TYPE STANDARD TABLE OF edid4 WITH HEADER LINE,
        ls_seg  TYPE zgsk_e1conf.

  LOOP AT gt_edidc.

    SELECT * FROM edid4
      INTO TABLE lt_data
      WHERE docnum = gt_edidc-docnum
        AND segnam = 'ZGSK_E1CONF'.

    LOOP AT lt_data.
      ls_seg = lt_data-sdata.

      CLEAR gt_conf.
      gt_conf-docnum = gt_edidc-docnum.
      gt_conf-aufnr  = ls_seg-aufnr.
      gt_conf-vornr  = ls_seg-vornr.
      gt_conf-matnr  = ls_seg-matnr.
      gt_conf-charg  = ls_seg-charg.
      gt_conf-werks  = ls_seg-werks.
      gt_conf-gmnga  = ls_seg-gmnga.
      gt_conf-meins  = ls_seg-meins.
      gt_conf-budat  = ls_seg-budat.
      APPEND gt_conf.
    ENDLOOP.

  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  POST_CONFIRMATIONS
*&---------------------------------------------------------------------*
FORM post_confirmations.

  DATA: lt_return TYPE STANDARD TABLE OF bapiret2 WITH HEADER LINE,
        lt_timeticket TYPE STANDARD TABLE OF bapi_pp_timeticket WITH HEADER LINE,
        lv_counter TYPE i.

  LOOP AT gt_conf.

    CLEAR: lt_timeticket, lt_timeticket[], lt_return, lt_return[].

    lt_timeticket-orderid   = gt_conf-aufnr.
    lt_timeticket-operation = gt_conf-vornr.
    lt_timeticket-yield     = gt_conf-gmnga.
    lt_timeticket-conf_quan_unit = gt_conf-meins.
    lt_timeticket-postg_date = gt_conf-budat.
    lt_timeticket-batch      = gt_conf-charg.
    APPEND lt_timeticket.

    CALL FUNCTION 'BAPI_PROCORDCONF_CREATE_TT'
      TABLES
        timetickets = lt_timeticket
        return      = lt_return.

    READ TABLE lt_return WITH KEY type = 'E'.
    IF sy-subrc = 0.
      gt_conf-status = 'E'.
      gt_conf-msgtx  = lt_return-message.
      ADD 1 TO gv_failed.
      CALL FUNCTION 'BAPI_TRANSACTION_ROLLBACK'.
    ELSE.
      gt_conf-status = 'S'.
      ADD 1 TO gv_posted.
      ADD 1 TO lv_counter.
      IF lv_counter >= p_commit.
        CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.
        CLEAR lv_counter.
      ENDIF.
    ENDIF.

    MODIFY gt_conf.
  ENDLOOP.

  CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  WRITE_AUDIT
*&---------------------------------------------------------------------*
FORM write_audit.

  DATA: ls_audit TYPE zgsk_if_audit.

  LOOP AT gt_conf.
    CLEAR ls_audit.
    ls_audit-mandt   = sy-mandt.
    ls_audit-if_name = 'MES_CONF'.
    ls_audit-docnum  = gt_conf-docnum.
    ls_audit-objkey  = gt_conf-aufnr.
    ls_audit-status  = gt_conf-status.
    ls_audit-msgtx   = gt_conf-msgtx.
    ls_audit-erdat   = sy-datum.
    ls_audit-erzet   = sy-uzeit.
    ls_audit-ernam   = sy-uname.
    INSERT zgsk_if_audit FROM ls_audit.
  ENDLOOP.

  COMMIT WORK.

ENDFORM.
