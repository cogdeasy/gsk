*&---------------------------------------------------------------------*
*& ABAP Unit  ZGSK_QM_BATCH_RELEASE
*&---------------------------------------------------------------------*
*& Test evidence for validation package QMS-014 (QP batch release
*& support). The data access layer is replaced by a test double, so the
*& tests are deterministic and run in any client without GMP data,
*& which is what the CSV package requires for regression evidence per
*& wave.
*&---------------------------------------------------------------------*
CLASS ltcl_release_source_double DEFINITION FOR TESTING.

  PUBLIC SECTION.
    INTERFACES zif_gsk_batch_release_source.

    DATA mt_batch    TYPE zcl_gsk_batch_release=>tt_batch.
    DATA mt_decision TYPE zcl_gsk_batch_release=>tt_usage_decision.
    DATA mt_coa      TYPE zcl_gsk_batch_release=>tt_coa.

ENDCLASS.

CLASS ltcl_release_source_double IMPLEMENTATION.

  METHOD zif_gsk_batch_release_source~select_batches.
    rt_batch = mt_batch.
  ENDMETHOD.

  METHOD zif_gsk_batch_release_source~select_usage_decisions.
    rt_decision = mt_decision.
  ENDMETHOD.

  METHOD zif_gsk_batch_release_source~select_released_coa.
    rt_coa = mt_coa.
  ENDMETHOD.

ENDCLASS.


CLASS ltcl_batch_release DEFINITION FOR TESTING
  DURATION SHORT
  RISK LEVEL HARMLESS.

  PRIVATE SECTION.

    DATA mo_double TYPE REF TO ltcl_release_source_double.
    DATA mo_cut    TYPE REF TO zcl_gsk_batch_release.

    METHODS setup.
    METHODS plant_range RETURNING VALUE(rt_range)
                          TYPE zcl_gsk_batch_release=>tt_plant_range.

    METHODS plant_is_mandatory       FOR TESTING RAISING cx_static_check.
    METHODS released_coa_is_ready    FOR TESTING RAISING cx_static_check.
    METHODS missing_coa_is_held      FOR TESTING RAISING cx_static_check.
    METHODS held_coa_is_not_released FOR TESTING RAISING cx_static_check.
    METHODS latest_decision_reported FOR TESTING RAISING cx_static_check.
    METHODS material_level_batch_kept FOR TESTING RAISING cx_static_check.
    METHODS batch_without_lot_is_held FOR TESTING RAISING cx_static_check.
    METHODS missing_coa_filter        FOR TESTING RAISING cx_static_check.
    METHODS result_is_sorted          FOR TESTING RAISING cx_static_check.

ENDCLASS.


CLASS ltcl_batch_release IMPLEMENTATION.

  METHOD setup.

    mo_double = NEW ltcl_release_source_double( ).
    mo_cut    = NEW zcl_gsk_batch_release( mo_double ).

    " B24001 has a released certificate and two usage decisions, the
    " second one taken after a retest. B24002 has a certificate that is
    " still in progress. B24003 is held at material level, so I_Batch
    " returns it without an identifying plant. B24004 has no inspection
    " lot at all.
    mo_double->mt_batch = VALUE #(
      ( material = 'FG-000123' batch = 'B24001' plant = 'GB21'
        expiry_date = '20270331' manufacture_date = '20260301' )
      ( material = 'FG-000123' batch = 'B24002' plant = 'GB21'
        expiry_date = '20270430' manufacture_date = '20260401' )
      ( material = 'API-00045' batch = 'B24003' plant = ''
        expiry_date = '20280131' manufacture_date = '20260115' )
      ( material = 'PKG-00901' batch = 'B24004' plant = 'BE31'
        expiry_date = '20290131' manufacture_date = '20260120' ) ).

    mo_double->mt_decision = VALUE #(
      ( inspection_lot = '010000000101' material = 'FG-000123'
        batch = 'B24001' plant = 'GB21' usage_decision_code = 'A1'
        usage_decision_date = '20260310' usage_decision_by = 'QPGB01' )
      ( inspection_lot = '010000000188' material = 'FG-000123'
        batch = 'B24001' plant = 'GB21' usage_decision_code = 'A3'
        usage_decision_date = '20260325' usage_decision_by = 'QPGB02' )
      ( inspection_lot = '010000000205' material = 'FG-000123'
        batch = 'B24002' plant = 'GB21' usage_decision_code = 'A1'
        usage_decision_date = '20260415' usage_decision_by = 'QPGB01' )
      ( inspection_lot = '010000000301' material = 'API-00045'
        batch = 'B24003' plant = '' usage_decision_code = 'A1'
        usage_decision_date = '20260120' usage_decision_by = 'QPBE01' ) ).

    mo_double->mt_coa = VALUE #(
      ( material = 'FG-000123' batch = 'B24001' released_documents = 2 )
      ( material = 'FG-000123' batch = 'B24002' released_documents = 0 )
      ( material = 'API-00045' batch = 'B24003' released_documents = 1 ) ).

  ENDMETHOD.

  METHOD plant_range.
    rt_range = VALUE #( ( sign = 'I' option = 'EQ' low = 'GB21' ) ).
  ENDMETHOD.

  METHOD plant_is_mandatory.

    TRY.
        mo_cut->read_worklist( it_plant = VALUE #( ) ).
        cl_abap_unit_assert=>fail( 'Expected exception for empty plant range' ).
      CATCH zcx_gsk_release_error.
        " expected
    ENDTRY.

  ENDMETHOD.

  METHOD released_coa_is_ready.

    DATA(lt_result) = mo_cut->read_worklist( plant_range( ) ).

    cl_abap_unit_assert=>assert_equals(
      act = lt_result[ batch = 'B24001' ]-release_status
      exp = zcl_gsk_batch_release=>co_status_ready
      msg = 'A batch with a released certificate is ready for the QP' ).

  ENDMETHOD.

  METHOD missing_coa_is_held.

    DATA(lt_result) = mo_cut->read_worklist( plant_range( ) ).

    cl_abap_unit_assert=>assert_equals(
      act = lt_result[ batch = 'B24004' ]-release_status
      exp = zcl_gsk_batch_release=>co_status_coa_missing
      msg = 'A batch with no certificate row must be held' ).

  ENDMETHOD.

  METHOD held_coa_is_not_released.

    DATA(lt_result) = mo_cut->read_worklist( plant_range( ) ).

    " A staging row exists but nothing on it is released, which is the
    " case the native SQL count in the ECC report covered.
    cl_abap_unit_assert=>assert_equals(
      act = lt_result[ batch = 'B24002' ]-release_status
      exp = zcl_gsk_batch_release=>co_status_coa_missing
      msg = 'A certificate still in progress must not release the batch' ).

  ENDMETHOD.

  METHOD latest_decision_reported.

    DATA(lt_result) = mo_cut->read_worklist( plant_range( ) ).
    DATA(ls_line) = lt_result[ batch = 'B24001' ].

    cl_abap_unit_assert=>assert_equals(
      act = ls_line-inspection_lot
      exp = '010000000188'
      msg = 'The most recent inspection lot must be reported' ).
    cl_abap_unit_assert=>assert_equals( act = ls_line-usage_decision_code exp = 'A3' ).
    cl_abap_unit_assert=>assert_equals( act = ls_line-usage_decision_by exp = 'QPGB02' ).

  ENDMETHOD.

  METHOD material_level_batch_kept.

    DATA(lt_result) = mo_cut->read_worklist( plant_range( ) ).

    cl_abap_unit_assert=>assert_equals(
      act = lt_result[ batch = 'B24003' ]-usage_decision_code
      exp = 'A1'
      msg = 'A batch held at material level must stay in the worklist' ).

  ENDMETHOD.

  METHOD batch_without_lot_is_held.

    DATA(lt_result) = mo_cut->read_worklist( plant_range( ) ).
    DATA(ls_line) = lt_result[ batch = 'B24004' ].

    cl_abap_unit_assert=>assert_initial(
      act = ls_line-inspection_lot
      msg = 'A batch with no inspection lot must report no decision' ).
    cl_abap_unit_assert=>assert_initial( act = ls_line-usage_decision_code ).

  ENDMETHOD.

  METHOD missing_coa_filter.

    DATA(lt_result) = mo_cut->read_worklist( it_plant       = plant_range( )
                                             iv_missing_coa = abap_true ).

    cl_abap_unit_assert=>assert_equals(
      act = lines( lt_result )
      exp = 2
      msg = 'Only batches without a released certificate must remain' ).

  ENDMETHOD.

  METHOD result_is_sorted.

    DATA(lt_result) = mo_cut->read_worklist( plant_range( ) ).

    cl_abap_unit_assert=>assert_equals(
      act = lt_result[ 1 ]-batch
      exp = 'B24003'
      msg = 'Result must be sorted by plant, material and batch' ).

  ENDMETHOD.

ENDCLASS.
