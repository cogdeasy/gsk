*&---------------------------------------------------------------------*
*& Class  ZCL_GSK_BATCH_RELEASE  (S/4HANA remediated)
*&---------------------------------------------------------------------*
*& Qualified Person batch release worklist. Batch master comes from the
*& released CDS view I_Batch instead of the ECC pair MCHA / MCH1, and
*& the inspection lot usage decision comes from I_InspectionLot, which
*& exposes the decision attributes the ECC report read row by row from
*& QALS and QAVE.
*&
*& I_Batch carries the identifying plant, which is initial for batches
*& kept at material level, so the plant batches and the cross plant
*& batches the ECC report read from two tables arrive in one read.
*&---------------------------------------------------------------------*
CLASS zcl_gsk_batch_release DEFINITION
  PUBLIC
  CREATE PUBLIC.

  PUBLIC SECTION.

    CONSTANTS co_status_ready       TYPE c LENGTH 12 VALUE 'READY FOR QP'.
    CONSTANTS co_status_coa_missing TYPE c LENGTH 12 VALUE 'COA MISSING'.

    TYPES: BEGIN OF ty_sel,
             plant       TYPE werks_d,
             material    TYPE matnr,
             expiry_date TYPE vfdat,
           END OF ty_sel.

    TYPES: BEGIN OF ty_batch,
             material         TYPE matnr,
             batch            TYPE charg_d,
             plant            TYPE werks_d,
             expiry_date      TYPE vfdat,
             manufacture_date TYPE hsdat,
             restricted_use   TYPE abap_bool,
           END OF ty_batch,
           tt_batch TYPE STANDARD TABLE OF ty_batch WITH EMPTY KEY.

    TYPES: BEGIN OF ty_usage_decision,
             inspection_lot      TYPE qplos,
             material            TYPE matnr,
             batch               TYPE charg_d,
             plant               TYPE werks_d,
             usage_decision_code TYPE qvcode,
             usage_decision_date TYPE qvdatum,
             usage_decision_by   TYPE qprueferq,
           END OF ty_usage_decision,
           tt_usage_decision TYPE STANDARD TABLE OF ty_usage_decision WITH EMPTY KEY.

    TYPES: BEGIN OF ty_coa,
             material           TYPE matnr,
             batch              TYPE charg_d,
             released_documents TYPE i,
           END OF ty_coa,
           tt_coa TYPE STANDARD TABLE OF ty_coa WITH EMPTY KEY.

    TYPES: BEGIN OF ty_release_line,
             plant               TYPE werks_d,
             material            TYPE matnr,
             batch               TYPE charg_d,
             expiry_date         TYPE vfdat,
             manufacture_date    TYPE hsdat,
             restricted_use      TYPE abap_bool,
             inspection_lot      TYPE qplos,
             usage_decision_code TYPE qvcode,
             usage_decision_date TYPE qvdatum,
             usage_decision_by   TYPE qprueferq,
             coa_released        TYPE abap_bool,
             release_status      TYPE c LENGTH 12,
           END OF ty_release_line,
           tt_release TYPE STANDARD TABLE OF ty_release_line WITH EMPTY KEY.

    TYPES: tt_plant_range    TYPE RANGE OF werks_d,
           tt_material_range TYPE RANGE OF matnr,
           tt_expiry_range   TYPE RANGE OF vfdat.

    METHODS constructor
      IMPORTING io_release_source TYPE REF TO zif_gsk_batch_release_source OPTIONAL.

    "! Worklist of batches with their usage decision and certificate of
    "! analysis status. A batch with no released certificate is held
    "! back from QP certification, which is the ECC behaviour.
    METHODS read_worklist
      IMPORTING it_plant           TYPE tt_plant_range
                it_material        TYPE tt_material_range OPTIONAL
                it_expiry_date     TYPE tt_expiry_range OPTIONAL
                iv_missing_coa     TYPE abap_bool DEFAULT abap_false
      RETURNING VALUE(rt_release)  TYPE tt_release
      RAISING   zcx_gsk_release_error.

    METHODS display
      IMPORTING it_release TYPE tt_release.

  PRIVATE SECTION.

    DATA mo_release_source TYPE REF TO zif_gsk_batch_release_source.

    "! Latest decision per batch. The ECC report took whichever
    "! inspection lot the database returned first, which is not
    "! reproducible for a batch inspected more than once.
    METHODS latest_decisions
      IMPORTING it_decision            TYPE tt_usage_decision
      RETURNING VALUE(rt_decision)     TYPE tt_usage_decision.

ENDCLASS.


CLASS zcl_gsk_batch_release IMPLEMENTATION.

  METHOD constructor.

    mo_release_source = COND #( WHEN io_release_source IS BOUND
                                THEN io_release_source
                                ELSE NEW zcl_gsk_batch_release_src( ) ).

  ENDMETHOD.

  METHOD read_worklist.

    IF it_plant IS INITIAL.
      RAISE EXCEPTION TYPE zcx_gsk_release_error
        EXPORTING textid = zcx_gsk_release_error=>no_plant_selected.
    ENDIF.

    DATA(lt_batch) = mo_release_source->select_batches(
      it_plant       = it_plant
      it_material    = it_material
      it_expiry_date = it_expiry_date ).

    IF lt_batch IS INITIAL.
      RETURN.
    ENDIF.

    DATA(lt_decision) = latest_decisions(
      mo_release_source->select_usage_decisions( lt_batch ) ).

    DATA(lt_coa) = mo_release_source->select_released_coa( lt_batch ).

    LOOP AT lt_batch INTO DATA(ls_batch).

      APPEND VALUE #( plant            = ls_batch-plant
                      material         = ls_batch-material
                      batch            = ls_batch-batch
                      expiry_date      = ls_batch-expiry_date
                      manufacture_date = ls_batch-manufacture_date
                      restricted_use   = ls_batch-restricted_use )
             TO rt_release ASSIGNING FIELD-SYMBOL(<ls_line>).

      ASSIGN lt_decision[ material = ls_batch-material
                          batch    = ls_batch-batch ] TO FIELD-SYMBOL(<ls_decision>).
      IF sy-subrc = 0.
        <ls_line>-inspection_lot      = <ls_decision>-inspection_lot.
        <ls_line>-usage_decision_code = <ls_decision>-usage_decision_code.
        <ls_line>-usage_decision_date = <ls_decision>-usage_decision_date.
        <ls_line>-usage_decision_by   = <ls_decision>-usage_decision_by.
      ENDIF.

      ASSIGN lt_coa[ material = ls_batch-material
                     batch    = ls_batch-batch ] TO FIELD-SYMBOL(<ls_coa>).
      IF sy-subrc = 0.
        <ls_line>-coa_released = xsdbool( <ls_coa>-released_documents > 0 ).
      ENDIF.

      <ls_line>-release_status = COND #( WHEN <ls_line>-coa_released = abap_true
                                         THEN co_status_ready
                                         ELSE co_status_coa_missing ).

    ENDLOOP.

    IF iv_missing_coa = abap_true.
      DELETE rt_release WHERE coa_released = abap_true.
    ENDIF.

    SORT rt_release BY plant material batch.

  ENDMETHOD.

  METHOD latest_decisions.

    rt_decision = it_decision.
    SORT rt_decision BY material batch usage_decision_date DESCENDING
                        inspection_lot DESCENDING.
    DELETE ADJACENT DUPLICATES FROM rt_decision COMPARING material batch.

  ENDMETHOD.

  METHOD display.

    DATA(lv_held) = REDUCE i( INIT held = 0
                              FOR ls_line IN it_release
                              WHERE ( coa_released = abap_false )
                              NEXT held = held + 1 ).

    cl_demo_output=>write_data( it_release ).
    cl_demo_output=>write_text( |Batches in worklist: { lines( it_release ) }| ).
    cl_demo_output=>write_text( |Held for missing certificate: { lv_held }| ).
    cl_demo_output=>display( ).

  ENDMETHOD.

ENDCLASS.


*&---------------------------------------------------------------------*
*& Interface  ZIF_GSK_BATCH_RELEASE_SOURCE
*&---------------------------------------------------------------------*
*& Seam for ABAP Unit. Batch certification is Annex 16 evidence, so the
*& tests for it must run on fixture data in any client rather than on
*& GMP data in one.
*&---------------------------------------------------------------------*
INTERFACE zif_gsk_batch_release_source PUBLIC.

  METHODS select_batches
    IMPORTING it_plant         TYPE zcl_gsk_batch_release=>tt_plant_range
              it_material      TYPE zcl_gsk_batch_release=>tt_material_range
              it_expiry_date   TYPE zcl_gsk_batch_release=>tt_expiry_range
    RETURNING VALUE(rt_batch)  TYPE zcl_gsk_batch_release=>tt_batch.

  METHODS select_usage_decisions
    IMPORTING it_batch           TYPE zcl_gsk_batch_release=>tt_batch
    RETURNING VALUE(rt_decision) TYPE zcl_gsk_batch_release=>tt_usage_decision.

  METHODS select_released_coa
    IMPORTING it_batch      TYPE zcl_gsk_batch_release=>tt_batch
    RETURNING VALUE(rt_coa) TYPE zcl_gsk_batch_release=>tt_coa.

ENDINTERFACE.


*&---------------------------------------------------------------------*
*& Class  ZCL_GSK_BATCH_RELEASE_SRC
*&---------------------------------------------------------------------*
*& Production data access. Batch master and inspection lot data come
*& from released CDS views; the certificate of analysis staging table
*& is a custom table that survives the conversion, so it is read with
*& Open SQL instead of the native SQL block the ECC report used.
*&---------------------------------------------------------------------*
CLASS zcl_gsk_batch_release_src DEFINITION
  PUBLIC
  CREATE PUBLIC.

  PUBLIC SECTION.
    INTERFACES zif_gsk_batch_release_source.

ENDCLASS.


CLASS zcl_gsk_batch_release_src IMPLEMENTATION.

  METHOD zif_gsk_batch_release_source~select_batches.

    SELECT FROM i_batch
      FIELDS material                      AS material,
             batch                         AS batch,
             batchidentifyingplant         AS plant,
             shelflifeexpirationdate       AS expiry_date,
             manufacturedate               AS manufacture_date,
             matlbatchisinrstrcdusestock   AS restricted_use
      WHERE ( batchidentifyingplant IN @it_plant
              OR batchidentifyingplant = @space )
        AND material                IN @it_material
        AND shelflifeexpirationdate IN @it_expiry_date
      INTO TABLE @rt_batch.

  ENDMETHOD.

  METHOD zif_gsk_batch_release_source~select_usage_decisions.

    SELECT FROM i_inspectionlot
      FIELDS inspectionlot                AS inspection_lot,
             material                     AS material,
             batch                        AS batch,
             plant                        AS plant,
             insplotusagedecisioncode     AS usage_decision_code,
             insplotusagedecisiondate     AS usage_decision_date,
             insplotusagedecisionbyuser   AS usage_decision_by
      FOR ALL ENTRIES IN @it_batch
      WHERE material = @it_batch-material
        AND batch    = @it_batch-batch
      INTO TABLE @rt_decision.

  ENDMETHOD.

  METHOD zif_gsk_batch_release_source~select_released_coa.

    SELECT FROM zgsk_coa_staging
      FIELDS matnr      AS material,
             charg      AS batch,
             COUNT( * ) AS released_documents
      FOR ALL ENTRIES IN @it_batch
      WHERE matnr  = @it_batch-material
        AND charg  = @it_batch-batch
        AND status = 'REL'
      GROUP BY matnr, charg
      INTO TABLE @rt_coa.

  ENDMETHOD.

ENDCLASS.
