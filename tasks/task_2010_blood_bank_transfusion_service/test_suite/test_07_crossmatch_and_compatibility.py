"""Compatibility matrix, crossmatch lifecycle, and the FEFO selector."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    create_crossmatch_payload,
    crossmatch_result_payload,
    get_success_data,
    get_unit,
    issue_all,
    make_compatible_crossmatch,
    make_issue,
    make_pending_crossmatch,
    make_stock,
    make_typed_patient,
    make_verified_order,
    receive_unit_descriptor,
    set_clock,
    setup_order_with_reserved_units,
    validate_error,
    validate_paginated,
    validate_success,
    TECH_A,
    TECH_B,
    NON_EXISTENT_UUID,
    api_client,
)


def _setup_o_patient_with_ab_units(api):
    """O POS typed patient; one AB POS RBC unit and one AB NEG FFP unit, both
    AVAILABLE; one verified RBC order and one verified FFP order."""
    stock = make_stock([
        receive_unit_descriptor("U-RBC-AB", product_type="RBC", abo_type="AB",
                                rh_type="POS", donor_id="D-610", lot_number="LOT-2"),
        receive_unit_descriptor("U-FFP-AB", product_type="FFP", abo_type="AB",
                                rh_type="NEG", volume_ml=250, donor_id="D-611",
                                lot_number="LOT-2"),
    ])
    patient, _ts = make_typed_patient(mrn="M-9001", abo="O", rh="POS")
    rbc_order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1, urgency="ROUTINE")
    ffp_order = make_verified_order(patient["id"], product_type="FFP",
                                    units_requested=1, urgency="ROUTINE",
                                    indication_code="COAGULOPATHY")
    return stock, patient, rbc_order, ffp_order


class TestAboPlasmaInversion:
    def test_ab_rbc_unit_incompatible_for_o_patient(self, api):
        """PRD §3.4: "For an `RBC` unit: a group O-negative patient may receive
        only O-negative units; an O-positive patient O-negative or O-positive"
        PRD §3.4: "Any failed step renders the pair incompatible: an explicit
        selection is rejected with `ERR_UNIT_INCOMPATIBLE` (HTTP 422), while
        auto-selection simply excludes the unit from the candidate pool."

        Design: Difficulty/combinatorial_formula/compatibility_decision_abo_plasma_inversion
        """
        stock, _patient, rbc_order, _ffp = _setup_o_patient_with_ab_units(api)
        unit = stock["units"]["U-RBC-AB"]
        resp = api.create_crossmatch(
            {"order_id": rbc_order["id"], "unit_id": unit["id"]}, TECH_A)
        validate_error(resp, ApiErrorId.ERR_UNIT_INCOMPATIBLE)
        assert get_unit(unit["id"])["status"] == "AVAILABLE", (
            "an incompatible explicit selection reserves nothing"
        )

    def test_ab_ffp_unit_compatible_for_o_patient(self, api):
        """PRD §3.4: "Plasma-class products run in the opposite direction, donor
        antibodies against patient cells, with Rh ignored: a group O patient may
        receive plasma-class units of any group — O, A, B, or AB"
        PRD §3.5: "The unit moves to `ISSUED` — from `RESERVED`, consuming the
        crossmatch to `CONSUMED`, or directly from `AVAILABLE` for non-crossmatched
        and emergency flows"

        Design: Difficulty/combinatorial_formula/compatibility_decision_abo_plasma_inversion
        """
        stock, _patient, _rbc, ffp_order = _setup_o_patient_with_ab_units(api)
        unit = stock["units"]["U-FFP-AB"]
        issue = validate_success(api.create_issue_record(
            {"order_id": ffp_order["id"], "unit_id": unit["id"],
             "verified_by_user_id": "tech-b"}, TECH_A), 201)
        assert issue["status"] == "ISSUED"
        assert issue["unit_id"] == unit["id"]
        assert get_unit(unit["id"])["status"] == "ISSUED"
        assert get_unit(stock["units"]["U-RBC-AB"]["id"])["status"] == "AVAILABLE"


class TestPlasmaMatrixEdge:
    def test_ffp_ab_patient_only_ab_plasma_compatible(self, api):
        """PRD §3.4: "an AB patient only AB."
        PRD §3.4: "an explicit selection is rejected with `ERR_UNIT_INCOMPATIBLE`
        (HTTP 422)"

        Design: Corner/calculations/ffp_ab_patient_only_ab_plasma_compatible
        """
        stock = make_stock([receive_unit_descriptor(
            "U-200", product_type="FFP", abo_type="A", rh_type="NEG",
            volume_ml=250, donor_id="D-510", lot_number="LOT-2")])
        patient, _ts = make_typed_patient(mrn="M-3002", full_name="Mona Doe",
                                          date_of_birth="1973-03-03", abo="AB",
                                          rh="NEG")
        order = make_verified_order(patient["id"], product_type="FFP",
                                    units_requested=1, urgency="ROUTINE",
                                    indication_code="COAGULOPATHY")
        unit = stock["units"]["U-200"]
        resp = api.create_issue_record(
            {"order_id": order["id"], "unit_id": unit["id"],
             "verified_by_user_id": "tech-b"}, TECH_A)
        validate_error(resp, ApiErrorId.ERR_UNIT_INCOMPATIBLE)
        assert get_unit(unit["id"])["status"] == "AVAILABLE"


class TestCrossmatchMethod:
    def test_crossmatch_method_serologic_for_unconfirmed_patient(self, api):
        """PRD §3.4: "computes its `method` — `ELECTRONIC` exactly when the
        patient's `abo_confirmed` is latched and their `antibody_status` is
        `NEGATIVE`, and `SEROLOGIC_AHG` otherwise."
        PRD §3.4: "When `unit_id` is omitted the server auto-selects a unit per the
        FEFO selector below and sets `auto_selected` true"

        Design: Corner/entities/crossmatch_method_serologic_for_unconfirmed_patient
        """
        stock = make_stock([receive_unit_descriptor("U-100")])
        patient, _ts = make_typed_patient(mrn="M-1003", full_name="Cory Doe",
                                          date_of_birth="1991-01-01", abo="A",
                                          rh="POS")
        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1)
        xm = validate_success(api.create_crossmatch(
            {"order_id": order["id"], "unit_id": stock["units"]["U-100"]["id"]},
            TECH_A), 201)
        assert xm["method"] == "SEROLOGIC_AHG", (
            "a single-specimen patient is not abo_confirmed"
        )
        assert xm["auto_selected"] is False, "an explicit unit_id was supplied"


class TestFefoSelector:
    def test_selector_fefo_earliest_expiry_first(self, api):
        """PRD §3.4: "It ranks candidates by `expires_at` ascending, breaks ties by
        `created_at` ascending, then by `unit_number` ascending, and takes the
        first — a deterministic single winner with no random inputs, never
        consulting the record's `id`."

        Design: Corner/cross_cutting_layers/selector_fefo_earliest_expiry_first
        """
        stock = make_stock([
            receive_unit_descriptor("U-NEW", donor_id="D-530", lot_number="LOT-4",
                                    collected_at="2026-08-01T00:00:00Z"),
            receive_unit_descriptor("U-OLD", donor_id="D-531", lot_number="LOT-4",
                                    collected_at="2026-07-25T00:00:00Z"),
        ])
        patient, _ts = make_typed_patient(mrn="M-6002", full_name="Amy Doe",
                                          date_of_birth="1992-12-12", abo="A",
                                          rh="POS")
        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1)
        xm = validate_success(api.create_crossmatch({"order_id": order["id"]},
                                                    TECH_A), 201)
        # U-OLD expires 2026-09-05 (collected 07-25 + 1008h); U-NEW 2026-09-12.
        assert xm["unit_id"] == stock["units"]["U-OLD"]["id"], (
            "FEFO takes the earliest-expiring eligible unit, not the first received"
        )
        assert xm["auto_selected"] is True

    def test_selector_empty_pool_returns_no_compatible_unit(self, api):
        """PRD §3.4: "when the selector's candidate pool is empty the create is
        rejected with `ERR_NO_COMPATIBLE_UNIT` (HTTP 409)."

        Design: Corner/cross_cutting_layers/selector_empty_pool_returns_no_compatible_unit
        """
        set_clock("2026-08-10T09:00:00Z")
        patient, _ts = make_typed_patient(mrn="M-6003", full_name="Bree Doe",
                                          date_of_birth="1985-01-01", abo="A",
                                          rh="POS")
        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1)
        resp = api.create_crossmatch({"order_id": order["id"]}, TECH_A)
        validate_error(resp, ApiErrorId.ERR_NO_COMPATIBLE_UNIT)
        _data, meta = validate_paginated(
            api.list_crossmatches(TECH_A, params={"order_id": order["id"]}))
        assert meta["total_count"] == 0


class TestReservationWindow:
    def test_reserved_until_min_of_three_clocks(self, api):
        """PRD §3.4: "On success the unit moves from `AVAILABLE` to `RESERVED`
        (decrementing the bucket's usable count and recomputing posture),
        `resulted_at` and `resulted_by_user_id` are stamped, and the reservation
        window is set: `reserved_until` is the earliest of seventy-two hours after
        `resulted_at`, the unit's `expires_at`, and the type-and-screen's
        `expires_at`."

        Design: Corner/calculations/reserved_until_min_of_three_clocks
        """
        set_clock("2026-08-10T09:00:00Z")
        stock = make_stock([receive_unit_descriptor("U-100")], clock=None)
        patient, _ts = make_typed_patient(mrn="M-3001", full_name="Liam Doe",
                                          date_of_birth="1984-08-08", abo="A",
                                          rh="POS")
        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1)
        xm = make_pending_crossmatch(order["id"], stock["units"]["U-100"]["id"])
        xm = validate_success(api.record_crossmatch_result(
            xm["id"], crossmatch_result_payload("COMPATIBLE"), TECH_B))
        # min(resulted_at 09:00 + 72h = 08-13T09:00, unit expiry 09-12,
        #     T&S expiry 08-13T08:00) == the T&S expiry.
        assert_same_instant(xm["reserved_until"], "2026-08-13T08:00:00Z",
                            "the T&S expiry is the earliest of the three clocks")


class TestFulfilledOrderCeiling:
    def test_incompatible_unit_beats_fulfilled_order_error(self, api):
        """PRD §2.9: "Once structural checks pass, the business rules evaluate in a
        fixed order: unit compatibility for an explicitly selected unit
        (`ERR_UNIT_INCOMPATIBLE`); segregation of duties
        (`ERR_SEGREGATION_OF_DUTIES`);"
        PRD §2.9: "the order-fulfillment ceiling at crossmatch creation
        (`ERR_ORDER_FULLY_CROSSMATCHED`); the issue quota
        (`ERR_ORDER_ISSUE_QUOTA_MET`)"

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_on_fulfilled_order_crossmatch
        """
        stock = make_stock([
            receive_unit_descriptor("U-411", donor_id="D-810", lot_number="LOT-8B"),
            receive_unit_descriptor("U-412", abo_type="B", donor_id="D-811",
                                    lot_number="LOT-8B"),
        ])
        patient, _ts = make_typed_patient(mrn="M-9017", full_name="Pat Seventeen",
                                          date_of_birth="1983-01-25")
        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1)
        make_compatible_crossmatch(order["id"], stock["units"]["U-411"]["id"])
        assert get_success_data(api.get_transfusion_order(order["id"], TECH_A))[
            "status"] == "READY"

        resp = api.create_crossmatch(
            {"order_id": order["id"], "unit_id": stock["units"]["U-412"]["id"]},
            TECH_A)
        validate_error(resp, ApiErrorId.ERR_UNIT_INCOMPATIBLE)
        _data, meta = validate_paginated(
            api.list_crossmatches(TECH_A, params={"order_id": order["id"]}))
        assert meta["total_count"] == 1, "the rejected create added no crossmatch"

    def test_fulfilled_order_rejects_further_crossmatch(self, api):
        """PRD §3.4: "Creation is refused once the order is already fulfilled:
        `units_crossmatched` plus `units_issued_net` must be below
        `units_requested`, else `ERR_ORDER_FULLY_CROSSMATCHED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_on_fulfilled_order_crossmatch
        """
        stock = make_stock([
            receive_unit_descriptor("U-411", donor_id="D-810", lot_number="LOT-8B"),
            receive_unit_descriptor("U-413", donor_id="D-812", lot_number="LOT-8B"),
        ])
        patient, _ts = make_typed_patient(mrn="M-9017", full_name="Pat Seventeen",
                                          date_of_birth="1983-01-25")
        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1)
        make_compatible_crossmatch(order["id"], stock["units"]["U-411"]["id"])

        resp = api.create_crossmatch(
            {"order_id": order["id"], "unit_id": stock["units"]["U-413"]["id"]},
            TECH_A)
        validate_error(resp, ApiErrorId.ERR_ORDER_FULLY_CROSSMATCHED)


class TestCrossmatchTerminalLockdown:
    def test_xm_cancel_from_consumed_rejected(self, api):
        """PRD §3.4: "Cancellation — whether invoked directly by a technologist or
        arriving as a cascade from an order cancel, a recall or supplier hold, or a
        T&S expiry — is legal from `PENDING` or `COMPATIBLE` and draws
        `ERR_XM_NOT_CANCELLABLE` elsewhere."
        PRD §3.4: "when the reserved unit is actually issued against the order, the
        crossmatch moves from `COMPATIBLE` to `CONSUMED` as the unit advances from
        `RESERVED` to `ISSUED`"

        Design: Corner/state_machines/xm_cancel_from_consumed_rejected
        """
        ctx = setup_order_with_reserved_units(mrn="M-2001", unit_numbers=["U-100"])
        issue_all(ctx)
        xm = ctx["crossmatches"]["U-100"]
        unit = ctx["units"]["U-100"]
        assert get_success_data(api.get_crossmatch(xm["id"], TECH_A))[
            "status"] == "CONSUMED"

        resp = api.cancel_crossmatch(xm["id"], TECH_A)
        validate_error(resp, ApiErrorId.ERR_XM_NOT_CANCELLABLE)
        assert get_success_data(api.get_crossmatch(xm["id"], TECH_A))[
            "status"] == "CONSUMED"
        assert get_unit(unit["id"])["status"] == "ISSUED"
