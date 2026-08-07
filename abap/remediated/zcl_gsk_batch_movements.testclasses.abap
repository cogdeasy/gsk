*&---------------------------------------------------------------------*
*& ABAP Unit  ZCL_GSK_BATCH_MOVEMENTS
*&---------------------------------------------------------------------*
*& Test evidence for validation package GMP-BRE-007 (batch traceability).
*& The data access layer is replaced by a test double, so the tests are
*& deterministic and run in any client without GMP data - which is what
*& the CSV package requires for regression evidence per wave.
*&---------------------------------------------------------------------*
CLASS ltcl_movement_source_double DEFINITION FOR TESTING.

  PUBLIC SECTION.
    INTERFACES zif_gsk_movement_source.
    DATA mt_fixture TYPE zcl_gsk_batch_movements=>tt_movement.

ENDCLASS.

CLASS ltcl_movement_source_double IMPLEMENTATION.

  METHOD zif_gsk_movement_source~select.
    rt_movement = mt_fixture.
  ENDMETHOD.

ENDCLASS.


CLASS ltcl_batch_movements DEFINITION FOR TESTING
  DURATION SHORT
  RISK LEVEL HARMLESS.

  PRIVATE SECTION.

    DATA mo_double TYPE REF TO ltcl_movement_source_double.
    DATA mo_cut    TYPE REF TO zcl_gsk_batch_movements.

    METHODS setup.
    METHODS plant_range          RETURNING VALUE(rt_range)
                                   TYPE zcl_gsk_batch_movements=>tt_plant_range.
    METHODS period_range         RETURNING VALUE(rt_range)
                                   TYPE zcl_gsk_batch_movements=>tt_date_range.

    METHODS period_is_mandatory     FOR TESTING RAISING cx_static_check.
    METHODS plant_is_mandatory      FOR TESTING RAISING cx_static_check.
    METHODS unbatched_lines_dropped FOR TESTING RAISING cx_static_check.
    METHODS unbatched_kept_on_flag  FOR TESTING RAISING cx_static_check.
    METHODS result_is_sorted        FOR TESTING RAISING cx_static_check.
    METHODS balance_per_batch       FOR TESTING RAISING cx_static_check.
    METHODS custom_movement_counted FOR TESTING RAISING cx_static_check.
    METHODS export_has_one_line_per_movement FOR TESTING RAISING cx_static_check.

ENDCLASS.


CLASS ltcl_batch_movements IMPLEMENTATION.

  METHOD setup.

    mo_double = NEW ltcl_movement_source_double( ).
    mo_cut    = NEW zcl_gsk_batch_movements( mo_double ).

    " Two receipts and one issue on batch B24001, an issue on B24002
    " posted with a plant specific movement type, and one unbatched
    " line that the extract must ignore by default.
    mo_double->mt_fixture = VALUE #(
      ( material_document = '4900001001' material_document_year = '2026'
        material_document_item = '0001' movement_type = '101'
        material = 'FG-000123' plant = 'GB21' storage_location = '0001'
        batch = 'B24001' quantity = '120.000' base_unit = 'EA'
        debit_credit = 'S' posting_date = '20260302' created_by = 'MFGJOB' )
      ( material_document = '4900001002' material_document_year = '2026'
        material_document_item = '0001' movement_type = '101'
        material = 'FG-000123' plant = 'GB21' storage_location = '0001'
        batch = 'B24001' quantity = '30.000' base_unit = 'EA'
        debit_credit = 'S' posting_date = '20260303' created_by = 'MFGJOB' )
      ( material_document = '4900001003' material_document_year = '2026'
        material_document_item = '0001' movement_type = '601'
        material = 'FG-000123' plant = 'GB21' storage_location = '0001'
        batch = 'B24001' quantity = '45.000' base_unit = 'EA'
        debit_credit = 'H' posting_date = '20260304' created_by = 'SDJOB' )
      ( material_document = '4900001004' material_document_year = '2026'
        material_document_item = '0002' movement_type = 'Z71'
        material = 'API-00045' plant = 'BE31' storage_location = '0002'
        batch = 'B24002' quantity = '12.500' base_unit = 'KG'
        debit_credit = 'H' posting_date = '20260301' created_by = 'QMJOB' )
      ( material_document = '4900001005' material_document_year = '2026'
        material_document_item = '0001' movement_type = '561'
        material = 'PKG-00901' plant = 'GB21' storage_location = '0003'
        batch = '' quantity = '5000.000' base_unit = 'EA'
        debit_credit = 'S' posting_date = '20260301' created_by = 'MFGJOB' ) ).

  ENDMETHOD.

  METHOD plant_range.
    rt_range = VALUE #( ( sign = 'I' option = 'EQ' low = 'GB21' ) ).
  ENDMETHOD.

  METHOD period_range.
    rt_range = VALUE #( ( sign = 'I' option = 'BT'
                          low = '20260301' high = '20260331' ) ).
  ENDMETHOD.

  METHOD period_is_mandatory.

    TRY.
        mo_cut->read_movements( it_posting_date = VALUE #( )
                                it_plant        = plant_range( ) ).
        cl_abap_unit_assert=>fail( 'Expected exception for empty period' ).
      CATCH zcx_gsk_movement_error.
        " expected
    ENDTRY.

  ENDMETHOD.

  METHOD plant_is_mandatory.

    TRY.
        mo_cut->read_movements( it_posting_date = period_range( )
                                it_plant        = VALUE #( ) ).
        cl_abap_unit_assert=>fail( 'Expected exception for empty plant range' ).
      CATCH zcx_gsk_movement_error.
        " expected
    ENDTRY.

  ENDMETHOD.

  METHOD unbatched_lines_dropped.

    DATA(lt_result) = mo_cut->read_movements(
      it_posting_date = period_range( )
      it_plant        = plant_range( ) ).

    cl_abap_unit_assert=>assert_equals(
      act = lines( lt_result )
      exp = 4
      msg = 'Movements without a batch must be dropped from the genealogy' ).

  ENDMETHOD.

  METHOD unbatched_kept_on_flag.

    DATA(lt_result) = mo_cut->read_movements(
      it_posting_date = period_range( )
      it_plant        = plant_range( )
      iv_batches_only = abap_false ).

    cl_abap_unit_assert=>assert_equals(
      act = lines( lt_result )
      exp = 5
      msg = 'Unbatched movements must be retained when requested' ).

  ENDMETHOD.

  METHOD result_is_sorted.

    DATA(lt_result) = mo_cut->read_movements(
      it_posting_date = period_range( )
      it_plant        = plant_range( ) ).

    cl_abap_unit_assert=>assert_equals(
      act = lt_result[ 1 ]-material_document
      exp = '4900001004'
      msg = 'Result must be sorted by posting date' ).

  ENDMETHOD.

  METHOD balance_per_batch.

    DATA(lt_total) = mo_cut->summarise_by_batch(
      mo_cut->read_movements( it_posting_date = period_range( )
                              it_plant        = plant_range( ) ) ).

    DATA(ls_total) = lt_total[ plant = 'GB21' batch = 'B24001' ].

    cl_abap_unit_assert=>assert_equals( act = ls_total-receipts exp = '150.000' ).
    cl_abap_unit_assert=>assert_equals( act = ls_total-issues   exp = '45.000' ).
    cl_abap_unit_assert=>assert_equals(
      act = ls_total-net
      exp = '105.000'
      msg = 'Net batch quantity must be receipts less issues' ).

  ENDMETHOD.

  METHOD custom_movement_counted.

    " Receipts and issues come from the debit/credit indicator, so a
    " plant specific movement type needs no rule maintenance here.
    DATA(lt_total) = mo_cut->summarise_by_batch(
      mo_cut->read_movements( it_posting_date = period_range( )
                              it_plant        = plant_range( ) ) ).

    DATA(ls_total) = lt_total[ plant = 'BE31' batch = 'B24002' ].

    cl_abap_unit_assert=>assert_equals(
      act = ls_total-issues
      exp = '12.500'
      msg = 'Plant specific movement type must be counted as an issue' ).
    cl_abap_unit_assert=>assert_equals( act = ls_total-net exp = '12.500-' ).

  ENDMETHOD.

  METHOD export_has_one_line_per_movement.

    DATA(lt_movement) = mo_cut->read_movements(
      it_posting_date = period_range( )
      it_plant        = plant_range( ) ).

    DATA(lt_line) = NEW zcl_gsk_movement_export( )->serialise( lt_movement ).

    cl_abap_unit_assert=>assert_equals(
      act = lines( lt_line )
      exp = lines( lt_movement ) + 1
      msg = 'Export must contain a header row and one row per movement' ).

  ENDMETHOD.

ENDCLASS.
