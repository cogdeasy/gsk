*&---------------------------------------------------------------------*
*& Class  ZCL_GSK_MOVEMENT_EXPORT  (S/4HANA remediated)
*&---------------------------------------------------------------------*
*& File export for the batch movement extract, replacing the WS_DOWNLOAD
*& call in the ECC report.
*&
*& The archive job runs in the background, where no presentation server
*& exists, so the target is chosen from the run context: frontend
*& services in dialogue, an application server path otherwise.
*&---------------------------------------------------------------------*
CLASS zcl_gsk_movement_export DEFINITION
  PUBLIC
  CREATE PUBLIC.

  PUBLIC SECTION.

    METHODS write
      IMPORTING it_movement TYPE zcl_gsk_batch_movements=>tt_movement
                iv_path     TYPE string
      RAISING   zcx_gsk_movement_error.

    "! Tab separated body, exposed so the ABAP Unit tests can assert on
    "! the serialised form without touching a file system.
    METHODS serialise
      IMPORTING it_movement    TYPE zcl_gsk_batch_movements=>tt_movement
      RETURNING VALUE(rt_line) TYPE string_table.

  PRIVATE SECTION.

    CONSTANTS mc_separator TYPE c LENGTH 1 VALUE cl_abap_char_utilities=>horizontal_tab.

    METHODS write_application_server
      IMPORTING it_line TYPE string_table
                iv_path TYPE string
      RAISING   zcx_gsk_movement_error.

ENDCLASS.


CLASS zcl_gsk_movement_export IMPLEMENTATION.

  METHOD write.

    DATA(lt_line) = serialise( it_movement ).

    IF cl_gui_frontend_services=>is_gui_available( ) = abap_true.

      TRY.
          cl_gui_frontend_services=>gui_download(
            EXPORTING filename = iv_path
                      filetype = 'ASC'
            CHANGING  data_tab = lt_line ).

        CATCH cx_root INTO DATA(lx_download).
          RAISE EXCEPTION TYPE zcx_gsk_movement_error
            EXPORTING textid   = zcx_gsk_movement_error=>export_failed
                      previous = lx_download.
      ENDTRY.

    ELSE.
      write_application_server( it_line = lt_line
                                iv_path = iv_path ).
    ENDIF.

  ENDMETHOD.

  METHOD write_application_server.

    OPEN DATASET iv_path FOR OUTPUT IN TEXT MODE ENCODING UTF-8.
    IF sy-subrc <> 0.
      RAISE EXCEPTION TYPE zcx_gsk_movement_error
        EXPORTING textid = zcx_gsk_movement_error=>export_failed.
    ENDIF.

    LOOP AT it_line INTO DATA(lv_line).
      TRANSFER lv_line TO iv_path.
    ENDLOOP.

    CLOSE DATASET iv_path.

  ENDMETHOD.

  METHOD serialise.

    APPEND |MATERIALDOCUMENT{ mc_separator }ITEM{ mc_separator }| &&
           |POSTINGDATE{ mc_separator }MOVEMENTTYPE{ mc_separator }| &&
           |MATERIAL{ mc_separator }PLANT{ mc_separator }BATCH{ mc_separator }| &&
           |QUANTITY{ mc_separator }UNIT{ mc_separator }CREATEDBY| TO rt_line.

    LOOP AT it_movement INTO DATA(ls_movement).
      APPEND |{ ls_movement-material_document }{ mc_separator }| &&
             |{ ls_movement-material_document_item }{ mc_separator }| &&
             |{ ls_movement-posting_date DATE = ISO }{ mc_separator }| &&
             |{ ls_movement-movement_type }{ mc_separator }| &&
             |{ ls_movement-material }{ mc_separator }| &&
             |{ ls_movement-plant }{ mc_separator }| &&
             |{ ls_movement-batch }{ mc_separator }| &&
             |{ ls_movement-quantity NUMBER = RAW }{ mc_separator }| &&
             |{ ls_movement-base_unit }{ mc_separator }| &&
             |{ ls_movement-created_by }| TO rt_line.
    ENDLOOP.

  ENDMETHOD.

ENDCLASS.
