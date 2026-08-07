*&---------------------------------------------------------------------*
*& Class  ZCL_GSK_BATCH_MOVEMENTS  (S/4HANA remediated)
*&---------------------------------------------------------------------*
*& Batch genealogy extract. Movements are read from the released CDS
*& view I_MaterialDocumentItem, which is backed by MATDOC, instead of
*& the ECC pair MKPF / MSEG.
*&
*& The header attributes the ECC version copied from MKPF in a nested
*& loop (posting date, entry user) are exposed on the item view, so the
*& whole extract is a single set based read.
*&---------------------------------------------------------------------*
CLASS zcl_gsk_batch_movements DEFINITION
  PUBLIC
  CREATE PUBLIC.

  PUBLIC SECTION.

    TYPES: BEGIN OF ty_sel,
             posting_date TYPE budat,
             plant        TYPE werks_d,
             batch        TYPE charg_d,
             movement     TYPE bwart,
           END OF ty_sel.

    TYPES: BEGIN OF ty_movement,
             material_document      TYPE mblnr,
             material_document_year TYPE mjahr,
             material_document_item TYPE mblpo,
             movement_type          TYPE bwart,
             material               TYPE matnr,
             plant                  TYPE werks_d,
             storage_location       TYPE lgort_d,
             batch                  TYPE charg_d,
             quantity               TYPE menge_d,
             base_unit              TYPE meins,
             debit_credit           TYPE shkzg,
             posting_date           TYPE budat,
             created_by             TYPE usnam,
           END OF ty_movement,
           tt_movement TYPE STANDARD TABLE OF ty_movement WITH EMPTY KEY.

    TYPES: BEGIN OF ty_batch_total,
             plant     TYPE werks_d,
             material  TYPE matnr,
             batch     TYPE charg_d,
             receipts  TYPE menge_d,
             issues    TYPE menge_d,
             net       TYPE menge_d,
             base_unit TYPE meins,
           END OF ty_batch_total,
           tt_batch_total TYPE STANDARD TABLE OF ty_batch_total WITH EMPTY KEY.

    TYPES: tt_date_range     TYPE RANGE OF budat,
           tt_plant_range    TYPE RANGE OF werks_d,
           tt_batch_range    TYPE RANGE OF charg_d,
           tt_movement_range TYPE RANGE OF bwart.

    METHODS constructor
      IMPORTING io_movement_source TYPE REF TO zif_gsk_movement_source OPTIONAL.

    METHODS read_movements
      IMPORTING it_posting_date    TYPE tt_date_range
                it_plant           TYPE tt_plant_range
                it_batch           TYPE tt_batch_range OPTIONAL
                it_movement_type   TYPE tt_movement_range OPTIONAL
                iv_batches_only    TYPE abap_bool DEFAULT abap_true
      RETURNING VALUE(rt_movement) TYPE tt_movement
      RAISING   zcx_gsk_movement_error.

    "! Batch balance over the selected period. Receipts and issues are
    "! derived from the debit/credit indicator rather than a hard coded
    "! list of movement types, so plant specific Z movement types are
    "! included in the genealogy without maintenance.
    METHODS summarise_by_batch
      IMPORTING it_movement     TYPE tt_movement
      RETURNING VALUE(rt_total) TYPE tt_batch_total.

    METHODS display
      IMPORTING it_movement TYPE tt_movement
                it_total    TYPE tt_batch_total.

  PRIVATE SECTION.

    DATA mo_movement_source TYPE REF TO zif_gsk_movement_source.

ENDCLASS.


CLASS zcl_gsk_batch_movements IMPLEMENTATION.

  METHOD constructor.

    mo_movement_source = COND #( WHEN io_movement_source IS BOUND
                                 THEN io_movement_source
                                 ELSE NEW zcl_gsk_movement_src_cds( ) ).

  ENDMETHOD.

  METHOD read_movements.

    IF it_posting_date IS INITIAL.
      RAISE EXCEPTION TYPE zcx_gsk_movement_error
        EXPORTING textid = zcx_gsk_movement_error=>no_period_selected.
    ENDIF.

    IF it_plant IS INITIAL.
      RAISE EXCEPTION TYPE zcx_gsk_movement_error
        EXPORTING textid = zcx_gsk_movement_error=>no_plant_selected.
    ENDIF.

    rt_movement = mo_movement_source->select(
      it_posting_date  = it_posting_date
      it_plant         = it_plant
      it_batch         = it_batch
      it_movement_type = it_movement_type ).

    IF iv_batches_only = abap_true.
      DELETE rt_movement WHERE batch IS INITIAL.
    ENDIF.

    SORT rt_movement BY posting_date plant batch
                        material_document material_document_item.

  ENDMETHOD.

  METHOD summarise_by_batch.

    LOOP AT it_movement INTO DATA(ls_movement).

      ASSIGN rt_total[ plant    = ls_movement-plant
                       material = ls_movement-material
                       batch    = ls_movement-batch ] TO FIELD-SYMBOL(<ls_total>).

      IF sy-subrc <> 0.
        APPEND VALUE #( plant     = ls_movement-plant
                        material  = ls_movement-material
                        batch     = ls_movement-batch
                        base_unit = ls_movement-base_unit ) TO rt_total
               ASSIGNING <ls_total>.
      ENDIF.

      IF ls_movement-debit_credit = 'S'.
        <ls_total>-receipts += ls_movement-quantity.
      ELSE.
        <ls_total>-issues += ls_movement-quantity.
      ENDIF.

      <ls_total>-net = <ls_total>-receipts - <ls_total>-issues.

    ENDLOOP.

    SORT rt_total BY plant material batch.

  ENDMETHOD.

  METHOD display.

    cl_demo_output=>write_data( it_movement ).
    cl_demo_output=>write_data( it_total ).
    cl_demo_output=>write_text( |Movements: { lines( it_movement ) }| ).
    cl_demo_output=>write_text( |Batches: { lines( it_total ) }| ).
    cl_demo_output=>display( ).

  ENDMETHOD.

ENDCLASS.


*&---------------------------------------------------------------------*
*& Interface  ZIF_GSK_MOVEMENT_SOURCE
*&---------------------------------------------------------------------*
*& Seam for ABAP Unit. The GMP batch record extract is validated
*& evidence, so its tests must run against fixture data rather than
*& client data.
*&---------------------------------------------------------------------*
INTERFACE zif_gsk_movement_source PUBLIC.

  METHODS select
    IMPORTING it_posting_date    TYPE zcl_gsk_batch_movements=>tt_date_range
              it_plant           TYPE zcl_gsk_batch_movements=>tt_plant_range
              it_batch           TYPE zcl_gsk_batch_movements=>tt_batch_range
              it_movement_type   TYPE zcl_gsk_batch_movements=>tt_movement_range
    RETURNING VALUE(rt_movement) TYPE zcl_gsk_batch_movements=>tt_movement.

ENDINTERFACE.


*&---------------------------------------------------------------------*
*& Class  ZCL_GSK_MOVEMENT_SRC_CDS
*&---------------------------------------------------------------------*
CLASS zcl_gsk_movement_src_cds DEFINITION
  PUBLIC
  CREATE PUBLIC.

  PUBLIC SECTION.
    INTERFACES zif_gsk_movement_source.

ENDCLASS.


CLASS zcl_gsk_movement_src_cds IMPLEMENTATION.

  METHOD zif_gsk_movement_source~select.

    SELECT FROM i_materialdocumentitem
      FIELDS materialdocument            AS material_document,
             materialdocumentyear        AS material_document_year,
             materialdocumentitem        AS material_document_item,
             goodsmovementtype           AS movement_type,
             material                    AS material,
             plant                       AS plant,
             storagelocation             AS storage_location,
             batch                       AS batch,
             quantityinbaseunit          AS quantity,
             materialbaseunit            AS base_unit,
             debitcreditcode             AS debit_credit,
             postingdate                 AS posting_date,
             createdbyuser               AS created_by
      WHERE postingdate       IN @it_posting_date
        AND plant             IN @it_plant
        AND batch             IN @it_batch
        AND goodsmovementtype IN @it_movement_type
        AND materialdocumentitemisdeleted = @abap_false
      INTO TABLE @rt_movement.

  ENDMETHOD.

ENDCLASS.
