*&---------------------------------------------------------------------*
*& User exit  MV45AFZZ - USEREXIT_SAVE_DOCUMENT_PREPARE (GSK copy)
*&---------------------------------------------------------------------*
*& Market specific sales order validations. Every market that joined an
*& ECC unification wave added its rules here; this is a major
*& contributor to the sales order process variant count.
*&
*& Object owner : Commercial IT
*& GxP class    : GxP-relevant (cold chain and controlled drug checks)
*&---------------------------------------------------------------------*

FORM userexit_save_document_prepare.

  DATA: lv_cold_chain TYPE c,
        lv_licence    TYPE c,
        lv_temp_class TYPE char4,
        lv_matnr      TYPE char18,
        lt_vbuk       TYPE STANDARD TABLE OF vbuk WITH HEADER LINE,
        lv_credit     TYPE klimk,
        lv_exposure   TYPE klimk.

* --- Controlled drug licence check (UK, DE, FR markets) -------------
  IF vbak-vkorg = 'GB01' OR vbak-vkorg = 'DE01' OR vbak-vkorg = 'FR01'.

    LOOP AT xvbap.

      lv_matnr = xvbap-matnr.

      SELECT SINGLE zz_controlled FROM mara
        INTO lv_licence
        WHERE matnr = lv_matnr.

      IF lv_licence = 'X'.
        SELECT SINGLE zz_licence_valid FROM kna1
          INTO lv_licence
          WHERE kunnr = vbak-kunnr.

        IF lv_licence <> 'X'.
          MESSAGE e001(zgsk_sd) WITH vbak-kunnr xvbap-matnr.
        ENDIF.
      ENDIF.

    ENDLOOP.

  ENDIF.

* --- Cold chain ship-to validation (vaccines) -----------------------
  LOOP AT xvbap.

    SELECT SINGLE zz_temp_class FROM mara
      INTO lv_temp_class
      WHERE matnr = xvbap-matnr.

    IF lv_temp_class = '2-8C' OR lv_temp_class = '-70C'.
      SELECT SINGLE zz_cold_chain FROM kna1
        INTO lv_cold_chain
        WHERE kunnr = vbak-kunnr.

      IF lv_cold_chain IS INITIAL.
        MESSAGE e002(zgsk_sd) WITH vbak-kunnr lv_temp_class.
      ENDIF.
    ENDIF.

  ENDLOOP.

* --- Credit block override for tender business ----------------------
  IF vbak-auart = 'ZTEN'.

    SELECT SINGLE klimk skfor FROM knkk
      INTO (lv_credit, lv_exposure)
      WHERE kkber = vbak-kkber
        AND kunnr = vbak-kunnr.

    IF lv_exposure > lv_credit.
      SELECT * FROM vbuk
        INTO TABLE lt_vbuk
        WHERE vbeln = vbak-vbeln.

      LOOP AT lt_vbuk.
        lt_vbuk-cmgst = 'A'.
        MODIFY vbuk FROM lt_vbuk.
      ENDLOOP.
    ENDIF.

  ENDIF.

ENDFORM.
