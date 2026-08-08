*&---------------------------------------------------------------------*
*& Report  ZBIO_IF_ICT_ANTIGEN_OUT
*&---------------------------------------------------------------------*
*& Outbound intercompany interface: Vaccines to the core system.
*&
*& Wavre supplies antigen bulk and finished vaccine to the Pharma
*& company codes for onward commercial distribution. Because the two
*& are separate ECC systems, every transfer is a real intercompany
*& sale: this program builds the outbound delivery, issues an ORDERS /
*& DESADV IDoc pair to GEP and posts the intercompany price so the
*& profit in stock can be eliminated at group level.
*&
*& Disposition: DECOMMISSION. Once GEP and GVP are one S/4HANA client
*& this whole interface disappears - the transfer becomes a stock
*& transport order inside one system, and intercompany profit in stock
*& is handled by actual costing rather than by this program. It is
*& modelled here because "interfaces that stop existing" is a real
*& class of work in a two-into-one merge and is easy to forget when
*& sizing the estate.
*&
*& Source system : GVP (GSK Vaccines ECC 6.0)
*& Object owner  : Vaccines Finance Systems (Wavre)
*& GxP class     : GxP-relevant (shipment records for supplied product)
*&---------------------------------------------------------------------*
REPORT zbio_if_ict_antigen_out.

TABLES: likp, lips, edidc, mseg.

TYPES: BEGIN OF ty_ship,
         vbeln TYPE vbeln_vl,
         posnr TYPE posnr_vl,
         matnr TYPE char18,
         charg TYPE charg_d,
         lfimg TYPE lfimg,
         vrkme TYPE vrkme,
         werks TYPE werks_d,
         kunnr TYPE kunnr,
         ict_price TYPE dmbtr,
         docnum TYPE edi_docnum,
       END OF ty_ship.

DATA: gt_ship TYPE STANDARD TABLE OF ty_ship WITH HEADER LINE,
      gv_sent TYPE i,
      gv_fail TYPE i.

SELECT-OPTIONS: s_vstel FOR likp-vstel OBLIGATORY,
                s_wadat FOR likp-wadat_ist OBLIGATORY.
PARAMETERS: p_rcvprt TYPE edi_rcvprn DEFAULT 'GEPCLNT100'.

START-OF-SELECTION.

  PERFORM collect_shipments.
  PERFORM price_intercompany.
  PERFORM send_idocs.

  WRITE: / 'IDocs sent:', gv_sent, 'failed:', gv_fail.

*&---------------------------------------------------------------------*
*&      Form  COLLECT_SHIPMENTS
*&---------------------------------------------------------------------*
FORM collect_shipments.

  DATA: lt_likp TYPE STANDARD TABLE OF likp WITH HEADER LINE.

  SELECT * FROM likp
    INTO TABLE lt_likp
    WHERE vstel     IN s_vstel
      AND wadat_ist IN s_wadat.

  LOOP AT lt_likp.

    SELECT vbeln posnr matnr charg lfimg vrkme werks
      FROM lips
      APPENDING CORRESPONDING FIELDS OF TABLE gt_ship
      WHERE vbeln = lt_likp-vbeln.

  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  PRICE_INTERCOMPANY
*&---------------------------------------------------------------------*
* Intercompany price is the standard cost of the supplying plant plus
* the transfer mark-up held in a Z table. The core system applies the
* mirror of this calculation on receipt, and the two have drifted.
*&---------------------------------------------------------------------*
FORM price_intercompany.

  DATA: lv_stprs TYPE stprs,
        lv_markup TYPE p LENGTH 5 DECIMALS 2.

  LOOP AT gt_ship.

    SELECT SINGLE stprs FROM mbew
      INTO lv_stprs
      WHERE matnr = gt_ship-matnr
        AND bwkey = gt_ship-werks.

    SELECT SINGLE markup FROM zbio_ict_markup
      INTO lv_markup
      WHERE matnr = gt_ship-matnr.

    IF sy-subrc <> 0.
      lv_markup = '12.50'.
    ENDIF.

    gt_ship-ict_price = lv_stprs * gt_ship-lfimg * ( 1 + lv_markup / 100 ).
    MODIFY gt_ship.

  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*&      Form  SEND_IDOCS
*&---------------------------------------------------------------------*
FORM send_idocs.

  DATA: ls_control TYPE edidc,
        lt_data    TYPE STANDARD TABLE OF edidd WITH HEADER LINE,
        lt_comm    TYPE STANDARD TABLE OF edidc WITH HEADER LINE.

  LOOP AT gt_ship.

    CLEAR ls_control.
    ls_control-mestyp = 'DESADV'.
    ls_control-idoctp = 'DELVRY03'.
    ls_control-rcvprt = 'LS'.
    ls_control-rcvprn = p_rcvprt.
    ls_control-sndprt = 'LS'.
    ls_control-sndprn = 'GVPCLNT200'.

    CLEAR lt_data.
    lt_data-segnam = 'E1EDL20'.
    lt_data-sdata  = gt_ship-vbeln.
    APPEND lt_data.

    lt_data-segnam = 'E1EDL24'.
    CONCATENATE gt_ship-matnr gt_ship-charg gt_ship-lfimg
           INTO lt_data-sdata SEPARATED BY space.
    APPEND lt_data.

    CALL FUNCTION 'MASTER_IDOC_DISTRIBUTE'
      EXPORTING
        master_idoc_control        = ls_control
      TABLES
        communication_idoc_control = lt_comm
        master_idoc_data           = lt_data
      EXCEPTIONS
        error_in_idoc_control      = 1
        error_writing_idoc_status  = 2
        error_in_idoc_data         = 3
        sending_logical_system_unknown = 4
        OTHERS                     = 5.

    IF sy-subrc = 0.
      READ TABLE lt_comm INDEX 1.
      gt_ship-docnum = lt_comm-docnum.
      MODIFY gt_ship.
      ADD 1 TO gv_sent.
      COMMIT WORK.
    ELSE.
      ADD 1 TO gv_fail.
    ENDIF.

  ENDLOOP.

ENDFORM.
