*&---------------------------------------------------------------------*
*& Class  ZCL_GSK_STOCK_OVERVIEW  (S/4HANA remediated reference)
*&---------------------------------------------------------------------*
*& Data access and presentation for the global stock overview.
*& Stock quantities come from the released CDS view I_MaterialStock
*& (MATDOC backed) instead of the ECC aggregate tables MARD / MCHB.
*&---------------------------------------------------------------------*
CLASS zcl_gsk_stock_overview DEFINITION
  PUBLIC
  CREATE PUBLIC.

  PUBLIC SECTION.

    TYPES: BEGIN OF ty_sel,
             plant            TYPE werks_d,
             material         TYPE matnr,
             storage_location TYPE lgort_d,
           END OF ty_sel.

    TYPES: BEGIN OF ty_stock_line,
             plant             TYPE werks_d,
             storage_location  TYPE lgort_d,
             material          TYPE matnr,
             batch             TYPE charg_d,
             unrestricted_qty  TYPE labst,
             quality_insp_qty  TYPE insme,
             blocked_qty       TYPE speme,
             base_unit         TYPE meins,
           END OF ty_stock_line,
           tt_stock TYPE STANDARD TABLE OF ty_stock_line WITH EMPTY KEY.

    TYPES: tt_plant_range    TYPE RANGE OF werks_d,
           tt_material_range TYPE RANGE OF matnr,
           tt_lgort_range    TYPE RANGE OF lgort_d.

    METHODS constructor
      IMPORTING io_stock_source TYPE REF TO zif_gsk_stock_source OPTIONAL.

    METHODS read_stock
      IMPORTING it_plant            TYPE tt_plant_range
                it_material         TYPE tt_material_range OPTIONAL
                it_storage_location TYPE tt_lgort_range OPTIONAL
                iv_with_batches     TYPE abap_bool DEFAULT abap_true
                iv_include_zero     TYPE abap_bool DEFAULT abap_false
      RETURNING VALUE(rt_stock)     TYPE tt_stock
      RAISING   zcx_gsk_stock_error.

    METHODS display
      IMPORTING it_stock TYPE tt_stock.

  PRIVATE SECTION.

    DATA mo_stock_source TYPE REF TO zif_gsk_stock_source.

    METHODS remove_zero_lines
      CHANGING ct_stock TYPE tt_stock.

ENDCLASS.


CLASS zcl_gsk_stock_overview IMPLEMENTATION.

  METHOD constructor.

    mo_stock_source = COND #( WHEN io_stock_source IS BOUND
                              THEN io_stock_source
                              ELSE NEW zcl_gsk_stock_source_cds( ) ).

  ENDMETHOD.

  METHOD read_stock.

    IF it_plant IS INITIAL.
      RAISE EXCEPTION TYPE zcx_gsk_stock_error
        EXPORTING textid = zcx_gsk_stock_error=>no_plant_selected.
    ENDIF.

    rt_stock = mo_stock_source->select(
      it_plant            = it_plant
      it_material         = it_material
      it_storage_location = it_storage_location
      iv_with_batches     = iv_with_batches ).

    IF iv_include_zero = abap_false.
      remove_zero_lines( CHANGING ct_stock = rt_stock ).
    ENDIF.

    SORT rt_stock BY plant storage_location material batch.

  ENDMETHOD.

  METHOD remove_zero_lines.

    DELETE ct_stock WHERE unrestricted_qty IS INITIAL
                      AND quality_insp_qty IS INITIAL
                      AND blocked_qty      IS INITIAL.

  ENDMETHOD.

  METHOD display.

    DATA(lv_total) = REDUCE labst( INIT sum = CONV labst( 0 )
                                   FOR ls_line IN it_stock
                                   NEXT sum = sum + ls_line-unrestricted_qty ).

    cl_demo_output=>write_data( it_stock ).
    cl_demo_output=>write_text( |Lines: { lines( it_stock ) }| ).
    cl_demo_output=>write_text( |Unrestricted total: { lv_total NUMBER = USER }| ).
    cl_demo_output=>display( ).

  ENDMETHOD.

ENDCLASS.


*&---------------------------------------------------------------------*
*& Interface  ZIF_GSK_STOCK_SOURCE
*&---------------------------------------------------------------------*
*& Seam for ABAP Unit - the production implementation reads the
*& released CDS view, the test double returns fixture data so the
*& validation test package does not depend on client data.
*&---------------------------------------------------------------------*
INTERFACE zif_gsk_stock_source PUBLIC.

  METHODS select
    IMPORTING it_plant            TYPE zcl_gsk_stock_overview=>tt_plant_range
              it_material         TYPE zcl_gsk_stock_overview=>tt_material_range
              it_storage_location TYPE zcl_gsk_stock_overview=>tt_lgort_range
              iv_with_batches     TYPE abap_bool
    RETURNING VALUE(rt_stock)     TYPE zcl_gsk_stock_overview=>tt_stock.

ENDINTERFACE.


*&---------------------------------------------------------------------*
*& Class  ZCL_GSK_STOCK_SOURCE_CDS
*&---------------------------------------------------------------------*
CLASS zcl_gsk_stock_source_cds DEFINITION
  PUBLIC
  CREATE PUBLIC.

  PUBLIC SECTION.
    INTERFACES zif_gsk_stock_source.

ENDCLASS.


CLASS zcl_gsk_stock_source_cds IMPLEMENTATION.

  METHOD zif_gsk_stock_source~select.

    IF iv_with_batches = abap_true.

      SELECT FROM i_materialstock
        FIELDS plant                    AS plant,
               storagelocation          AS storage_location,
               material                 AS material,
               batch                    AS batch,
               matlwrhsstkqtyinmatlbaseunit AS unrestricted_qty,
               matlstkqtyinqualityinsp      AS quality_insp_qty,
               matlstkqtyinblockedstock     AS blocked_qty,
               materialbaseunit             AS base_unit
        WHERE plant           IN @it_plant
          AND material        IN @it_material
          AND storagelocation IN @it_storage_location
        INTO TABLE @rt_stock.

    ELSE.

      SELECT FROM i_materialstock
        FIELDS plant                    AS plant,
               storagelocation          AS storage_location,
               material                 AS material,
               SUM( matlwrhsstkqtyinmatlbaseunit ) AS unrestricted_qty,
               SUM( matlstkqtyinqualityinsp )      AS quality_insp_qty,
               SUM( matlstkqtyinblockedstock )     AS blocked_qty,
               materialbaseunit                    AS base_unit
        WHERE plant           IN @it_plant
          AND material        IN @it_material
          AND storagelocation IN @it_storage_location
        GROUP BY plant, storagelocation, material, materialbaseunit
        INTO CORRESPONDING FIELDS OF TABLE @rt_stock.

    ENDIF.

  ENDMETHOD.

ENDCLASS.
