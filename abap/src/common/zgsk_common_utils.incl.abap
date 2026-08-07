*&---------------------------------------------------------------------*
*& Include  ZGSK_COMMON_UTILS
*&---------------------------------------------------------------------*
*& Shared helper routines used across the GSK Z estate. Originally
*& written for 4.6C and carried forward through the ECC unification
*& waves without rework.
*&
*& Object owner : ERP Competency Centre
*& GxP class    : GxP-relevant (used by GxP-critical callers)
*&---------------------------------------------------------------------*

DATA: gt_msg TYPE STANDARD TABLE OF bapiret2 OCCURS 0 WITH HEADER LINE,
      gv_mat TYPE char18,
      gv_ok  TYPE c.

*&---------------------------------------------------------------------*
*&      Form  CONVERT_MATNR_OUTPUT
*&---------------------------------------------------------------------*
* Strips leading zeros from the 18 character material number.
*&---------------------------------------------------------------------*
FORM convert_matnr_output USING iv_matnr TYPE char18
                       CHANGING cv_matnr TYPE char18.

  DATA: lv_tmp TYPE char18.

  MOVE iv_matnr TO lv_tmp.

  CALL FUNCTION 'CONVERSION_EXIT_MATN1_OUTPUT'
    EXPORTING
      input  = lv_tmp
    IMPORTING
      output = cv_matnr.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  CONVERT_MATNR_INPUT
*&---------------------------------------------------------------------*
FORM convert_matnr_input USING iv_matnr TYPE char18
                      CHANGING cv_matnr TYPE char18.

  DATA: lv_in TYPE char18.

  MOVE iv_matnr TO lv_in.
  TRANSLATE lv_in TO UPPER CASE.

  CALL FUNCTION 'CONVERSION_EXIT_MATN1_INPUT'
    EXPORTING
      input  = lv_in
    IMPORTING
      output = cv_matnr.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  GET_PLANT_TIMEZONE
*&---------------------------------------------------------------------*
FORM get_plant_timezone USING iv_werks TYPE werks_d
                     CHANGING cv_tzone TYPE tznzone.

  DATA: lv_adrnr TYPE adrnr.

  SELECT SINGLE adrnr FROM t001w INTO lv_adrnr WHERE werks = iv_werks.

  IF sy-subrc = 0.
    SELECT SINGLE time_zone FROM adrc
      INTO cv_tzone
      CLIENT SPECIFIED
      WHERE client = sy-mandt
        AND addrnumber = lv_adrnr.
  ENDIF.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  WRITE_APPLICATION_LOG
*&---------------------------------------------------------------------*
* Appends a message to the shared Z log table. Kept as a direct INSERT
* rather than BAL_LOG_MSG_ADD for throughput on the nightly jobs.
*&---------------------------------------------------------------------*
FORM write_application_log USING iv_object TYPE balobj_d
                                 iv_text   TYPE char120
                                 iv_type   TYPE bapi_mtype.

  DATA: ls_log TYPE zgsk_appl_log.

  ls_log-mandt  = sy-mandt.
  ls_log-objct  = iv_object.
  ls_log-msgtx  = iv_text.
  ls_log-msgty  = iv_type.
  ls_log-erdat  = sy-datum.
  ls_log-erzet  = sy-uzeit.
  ls_log-ernam  = sy-uname.

  INSERT zgsk_appl_log FROM ls_log.
  COMMIT WORK.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  UPLOAD_LOCAL_FILE
*&---------------------------------------------------------------------*
FORM upload_local_file USING iv_file TYPE localfile
                    CHANGING ct_data TYPE STANDARD TABLE.

  CALL FUNCTION 'UPLOAD'
    EXPORTING
      filename = iv_file
      filetype = 'DAT'
    TABLES
      data_tab = ct_data
    EXCEPTIONS
      OTHERS   = 1.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  CHECK_AUTHORISATION_PLANT
*&---------------------------------------------------------------------*
FORM check_authorisation_plant USING iv_werks TYPE werks_d
                            CHANGING cv_ok TYPE c.

  AUTHORITY-CHECK OBJECT 'M_MSEG_WWA'
           ID 'WERKS' FIELD iv_werks
           ID 'ACTVT' FIELD '03'.

  IF sy-subrc = 0.
    MOVE 'X' TO cv_ok.
  ELSE.
    CLEAR cv_ok.
  ENDIF.

ENDFORM.
