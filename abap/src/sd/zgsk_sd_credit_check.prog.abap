*&---------------------------------------------------------------------*
*& Report  ZGSK_SD_CREDIT_CHECK
*&---------------------------------------------------------------------*
*& Customer credit exposure against limit, using classic SD credit
*& management (FI-AR-CR) master data and the SIS credit info structures.
*&
*& Object owner : Commercial IT / Credit Control
*& GxP class    : Non-GxP
*&---------------------------------------------------------------------*
REPORT zgsk_sd_credit_check.

TABLES: knkk, knka, s066, s067, kna1.

TYPES: BEGIN OF ty_exposure,
         kkber TYPE kkber,
         kunnr TYPE kunnr,
         name1 TYPE name1_gp,
         klimk TYPE klimk,
         skfor TYPE skfor,
         ssobl TYPE ssobl,
         oeikw TYPE oeikw,
         olikw TYPE olikw,
         ofakw TYPE ofakw,
         exposure TYPE klimk,
         util_pct TYPE p LENGTH 5 DECIMALS 2,
       END OF ty_exposure.

DATA: gt_exp TYPE STANDARD TABLE OF ty_exposure WITH HEADER LINE.

SELECT-OPTIONS: s_kkber FOR knkk-kkber OBLIGATORY,
                s_kunnr FOR knkk-kunnr.
PARAMETERS: p_thresh TYPE p DECIMALS 2 DEFAULT '80.00'.

START-OF-SELECTION.

  PERFORM read_credit_master.
  PERFORM read_open_values.
  PERFORM calculate_utilisation.

*&---------------------------------------------------------------------*
*&      Form  READ_CREDIT_MASTER
*&---------------------------------------------------------------------*
FORM read_credit_master.

  SELECT kkber kunnr klimk skfor ssobl
    FROM knkk
    INTO CORRESPONDING FIELDS OF TABLE gt_exp
    WHERE kkber IN s_kkber
      AND kunnr IN s_kunnr.

  LOOP AT gt_exp.
    SELECT SINGLE name1 FROM kna1
      INTO gt_exp-name1
      WHERE kunnr = gt_exp-kunnr.
    MODIFY gt_exp.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  READ_OPEN_VALUES
*&---------------------------------------------------------------------*
* Open order / delivery / billing values from the SIS credit
* information structures S066 and S067.
*&---------------------------------------------------------------------*
FORM read_open_values.

  LOOP AT gt_exp.

    SELECT SINGLE oeikw olikw ofakw FROM s066
      INTO (gt_exp-oeikw, gt_exp-olikw, gt_exp-ofakw)
      WHERE kkber = gt_exp-kkber
        AND kunnr = gt_exp-kunnr.

    IF sy-subrc <> 0.
      SELECT SINGLE oeikw olikw ofakw FROM s067
        INTO (gt_exp-oeikw, gt_exp-olikw, gt_exp-ofakw)
        WHERE kkber = gt_exp-kkber
          AND kunnr = gt_exp-kunnr.
    ENDIF.

    MODIFY gt_exp.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  CALCULATE_UTILISATION
*&---------------------------------------------------------------------*
FORM calculate_utilisation.

  LOOP AT gt_exp.

    gt_exp-exposure = gt_exp-skfor + gt_exp-ssobl
                    + gt_exp-oeikw + gt_exp-olikw + gt_exp-ofakw.

    IF gt_exp-klimk > 0.
      gt_exp-util_pct = gt_exp-exposure * 100 / gt_exp-klimk.
    ENDIF.

    MODIFY gt_exp.

    IF gt_exp-util_pct >= p_thresh.
      WRITE: / gt_exp-kunnr, gt_exp-name1, gt_exp-klimk,
               gt_exp-exposure, gt_exp-util_pct.
    ENDIF.

  ENDLOOP.

ENDFORM.
