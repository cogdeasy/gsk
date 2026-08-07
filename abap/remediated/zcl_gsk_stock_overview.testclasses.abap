*&---------------------------------------------------------------------*
*& ABAP Unit  ZCL_GSK_STOCK_OVERVIEW
*&---------------------------------------------------------------------*
*& Test evidence for validation package GSC-STK-001. The data access
*& layer is replaced by a test double so the tests are deterministic
*& and can run in any client, which is what the CSV package requires.
*&---------------------------------------------------------------------*
CLASS ltcl_stock_source_double DEFINITION FOR TESTING.

  PUBLIC SECTION.
    INTERFACES zif_gsk_stock_source.
    DATA mt_fixture TYPE zcl_gsk_stock_overview=>tt_stock.

ENDCLASS.

CLASS ltcl_stock_source_double IMPLEMENTATION.

  METHOD zif_gsk_stock_source~select.
    rt_stock = mt_fixture.
  ENDMETHOD.

ENDCLASS.


CLASS ltcl_stock_overview DEFINITION FOR TESTING
  DURATION SHORT
  RISK LEVEL HARMLESS.

  PRIVATE SECTION.

    DATA mo_double TYPE REF TO ltcl_stock_source_double.
    DATA mo_cut    TYPE REF TO zcl_gsk_stock_overview.

    METHODS setup.
    METHODS plant_is_mandatory      FOR TESTING RAISING cx_static_check.
    METHODS zero_lines_are_removed  FOR TESTING RAISING cx_static_check.
    METHODS zero_lines_kept_on_flag FOR TESTING RAISING cx_static_check.
    METHODS result_is_sorted        FOR TESTING RAISING cx_static_check.

ENDCLASS.


CLASS ltcl_stock_overview IMPLEMENTATION.

  METHOD setup.

    mo_double = NEW ltcl_stock_source_double( ).
    mo_cut    = NEW zcl_gsk_stock_overview( mo_double ).

    mo_double->mt_fixture = VALUE #(
      ( plant = 'GB21' storage_location = '0001' material = 'FG-000123'
        batch = 'B24001' unrestricted_qty = '120.000' base_unit = 'EA' )
      ( plant = 'BE31' storage_location = '0001' material = 'FG-000123'
        batch = 'B24002' unrestricted_qty = '0.000' base_unit = 'EA' )
      ( plant = 'BE31' storage_location = '0002' material = 'API-00045'
        batch = 'B24003' quality_insp_qty = '15.500' base_unit = 'KG' ) ).

  ENDMETHOD.

  METHOD plant_is_mandatory.

    TRY.
        mo_cut->read_stock( it_plant = VALUE #( ) ).
        cl_abap_unit_assert=>fail( 'Expected exception for empty plant range' ).
      CATCH zcx_gsk_stock_error.
        " expected
    ENDTRY.

  ENDMETHOD.

  METHOD zero_lines_are_removed.

    DATA(lt_result) = mo_cut->read_stock(
      it_plant = VALUE #( ( sign = 'I' option = 'EQ' low = 'GB21' ) ) ).

    cl_abap_unit_assert=>assert_equals(
      act = lines( lt_result )
      exp = 2
      msg = 'Batch with zero stock in all categories must be dropped' ).

  ENDMETHOD.

  METHOD zero_lines_kept_on_flag.

    DATA(lt_result) = mo_cut->read_stock(
      it_plant        = VALUE #( ( sign = 'I' option = 'EQ' low = 'GB21' ) )
      iv_include_zero = abap_true ).

    cl_abap_unit_assert=>assert_equals(
      act = lines( lt_result )
      exp = 3
      msg = 'Zero lines must be retained when requested' ).

  ENDMETHOD.

  METHOD result_is_sorted.

    DATA(lt_result) = mo_cut->read_stock(
      it_plant        = VALUE #( ( sign = 'I' option = 'EQ' low = 'GB21' ) )
      iv_include_zero = abap_true ).

    cl_abap_unit_assert=>assert_equals(
      act = lt_result[ 1 ]-plant
      exp = 'BE31'
      msg = 'Result must be sorted by plant' ).

  ENDMETHOD.

ENDCLASS.
