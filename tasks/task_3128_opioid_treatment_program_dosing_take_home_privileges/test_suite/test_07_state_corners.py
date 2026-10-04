"""Breadth tests: state-machine corners and automatic transitions."""

import pytest

from test_helpers import (
    api_client,
    get_success_data,
    setup_clinic,
    setup_active_patient,
    schedule_dose,
    mark_missed,
    check_in_dose,
    verify_dose,
    dispense_dose,
    list_doses,
    set_clock,
    create_lot_payload,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
)


class TestDoseOrderTerminalState:
    """DISCONTINUED is terminal; no edge leads out of it."""

    def test_activating_a_discontinued_order_reports_the_draft_gate(self):
        """PRD 3.3: "`DISCONTINUED` is terminal, and orders are driven there
        automatically when their patient is discharged or completes a medically
        managed withdrawal."
        PRD 3.3: "Discontinuation is available from `DRAFT`, `ACTIVE` or
        `SUSPENDED` and is refused with `ERR_DOSE_ORDER_NOT_DISCONTINUABLE`
        (HTTP 409) once the order is already `DISCONTINUED`."
        PRD 3.3: "Moving the order from `DRAFT` to `ACTIVE` requires five things
        to hold. The order must genuinely be `DRAFT`, else
        `ERR_DOSE_ORDER_NOT_DRAFT` (HTTP 409)."

        Design: Corner/state_machines/dose_order_activate_from_discontinued_returns_invalid_state
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        validate_success(api_client.discontinue_dose_order(order["id"],
                                                           clinic["physician_headers"]))
        discontinued = validate_success(
            api_client.get_dose_order(order["id"], clinic["physician_headers"]))
        assert discontinued["status"] == "DISCONTINUED"

        res = api_client.activate_dose_order(order["id"], clinic["physician_headers"])
        validate_error(res, ApiErrorId.ERR_DOSE_ORDER_NOT_DRAFT.value)

        after = validate_success(
            api_client.get_dose_order(order["id"], clinic["physician_headers"]))
        assert after["status"] == "DISCONTINUED"
        assert after["version"] == discontinued["version"], (
            "the rejected call must not have mutated the order")


class TestPatientDischargeIdempotency:
    """Administrative discharge is terminal and cannot be repeated."""

    def _setup(self):
        clinic = setup_clinic(lot_overrides={"lot_number": "LOT-A1"})
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-12-15T00:00:00Z")
        dose = schedule_dose(clinic, order["id"], "2026-12-21", "2026-12-21T07:00:00Z",
                             inventory_lot_id=clinic["lot"]["id"])
        return clinic, patient, order, dose

    def test_a_second_discharge_is_refused_as_not_dischargeable(self):
        """PRD 3.14: "Administrative discharge is a `Physician`'s act and
        requires the patient's status to be one of `ADMITTED`, `ACTIVE` or
        `SUSPENDED_NON_COMPLIANT` — a patient already in a terminal status
        yields `ERR_PATIENT_NOT_DISCHARGEABLE` (HTTP 409)."
        PRD 3.14: "A patient leaves the program by one of two doors, and neither
        is reversible."

        Design: Corner/state_machines/patient_discharge_is_idempotent_after_terminal
        """
        clinic, patient, order, dose = self._setup()
        discharged = validate_success(api_client.discharge_patient(
            patient["id"], {"reason_code": "TRANSFER"}, clinic["physician_headers"]))
        assert discharged["status"] == "ADMINISTRATIVELY_DISCHARGED"

        res = api_client.discharge_patient(patient["id"], {"reason_code": "TRANSFER"},
                                           clinic["physician_headers"])
        validate_error(res, ApiErrorId.ERR_PATIENT_NOT_DISCHARGEABLE.value)

        after = validate_success(api_client.get_patient(patient["id"], clinic["physician_headers"]))
        assert after["version"] == discharged["version"], (
            "the rejected second discharge must not have bumped the version")

    def test_discharge_cancels_open_work_only_once(self):
        """PRD 3.14: "A discharge sweeps the patient's open work: `ACTIVE` dose
        orders become `DISCONTINUED`; doses still in `SCHEDULED`,
        `ARRIVED_AT_CLINIC` or `NURSE_VERIFIED` are cancelled."
        PRD 3.14: "and guest arrangements still in `DRAFT`,
        `PENDING_RECEIVING_ACK` or `ACTIVE` are cancelled."

        Design: Corner/state_machines/patient_discharge_is_idempotent_after_terminal
        """
        clinic, patient, order, dose = self._setup()
        validate_success(api_client.discharge_patient(
            patient["id"], {"reason_code": "TRANSFER"}, clinic["physician_headers"]))

        dose_after = validate_success(api_client.get_dose_dispense(dose["id"],
                                                                   clinic["nurse_headers"]))
        assert dose_after["status"] == "CANCELLED"
        order_after = validate_success(api_client.get_dose_order(order["id"],
                                                                 clinic["physician_headers"]))
        assert order_after["status"] == "DISCONTINUED"


class TestMissedDoseBubblesToOrder:
    """The leaf dose row and its ancestor order move together."""

    def _setup(self):
        clinic = setup_clinic(allotted_carries=20)
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-12-15T00:00:00Z")
        doses = []
        for date in ("2026-12-21", "2026-12-22", "2026-12-23"):
            doses.append(schedule_dose(clinic, order["id"], date, f"{date}T07:00:00Z",
                                       inventory_lot_id=clinic["lot"]["id"]))
        return clinic, patient, order, doses

    def test_the_third_miss_suspends_the_order_without_an_order_call(self):
        """PRD 3.5: "When the recomputed `missed_dose_streak` reaches 3 or more,
        the patient's own transition to `SUSPENDED_NON_COMPLIANT` fires
        automatically, and every one of the patient's `ACTIVE` dose orders is
        moved to `SUSPENDED`."
        PRD 3.5: "The streak threshold is three consecutive misses: two missed
        doses suspend nothing, and the third triggers the whole cascade in a
        single chain."

        Design: Corner/state_machines/missed_dose_recompute_bubbles_to_the_order_status
        """
        clinic, patient, order, doses = self._setup()
        mark_missed(clinic, doses[0]["id"])
        mark_missed(clinic, doses[1]["id"])
        order_after_two = validate_success(
            api_client.get_dose_order(order["id"], clinic["physician_headers"]))
        assert order_after_two["status"] == "ACTIVE", (
            "two missed doses suspend nothing")

        missed = mark_missed(clinic, doses[2]["id"])
        assert missed["status"] == "MISSED"

        order_after = validate_success(
            api_client.get_dose_order(order["id"], clinic["physician_headers"]))
        assert order_after["status"] == "SUSPENDED"

        read = validate_success(api_client.get_patient(patient["id"], clinic["physician_headers"]))
        assert read["missed_dose_streak"] == 3

    def test_the_order_left_active_so_an_explicit_suspend_now_fails(self):
        """PRD 3.3: "Suspending or reactivating an order in the wrong status
        reports `ERR_DOSE_ORDER_NOT_ACTIVE` (HTTP 409)."
        PRD 3.5: "That cascade is thorough."

        Design: Corner/state_machines/missed_dose_recompute_bubbles_to_the_order_status
        """
        clinic, patient, order, doses = self._setup()
        for dose in doses:
            mark_missed(clinic, dose["id"])

        res = api_client.suspend_dose_order(order["id"], clinic["physician_headers"])
        validate_error(res, ApiErrorId.ERR_DOSE_ORDER_NOT_ACTIVE.value)


class TestLotDepletesAtZero:
    """The DEPLETED transition is automatic and threshold-driven."""

    def test_a_lot_emptied_to_zero_becomes_depleted(self):
        """PRD 2.9: "It becomes `IN_USE` automatically when the first
        transaction referencing it is recorded, and `DEPLETED` automatically
        once `running_on_hand_mg` falls to 0.0001 or below, after which no
        further `DISPENSE` transaction may be recorded against it."

        Design: Corner/state_machines/inventory_lot_depletes_automatically_at_zero_on_hand
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        lot = validate_success(api_client.create_lot(
            create_lot_payload(clinic["program"]["id"], lot_number="LOT-TINY",
                               quantity_received_mg=90.0, reusable_for_take_home=False),
            clinic["admin_headers"]), 201)
        assert lot["status"] == "RECEIVED"

        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-09-02T06:30:00Z")
        dose = schedule_dose(clinic, order["id"], "2026-09-02", "2026-09-02T07:00:00Z",
                             inventory_lot_id=lot["id"])
        check_in_dose(clinic, dose["id"])
        verify_dose(clinic, dose["id"], True)
        dispense_dose(clinic, dose["id"], 90.0, 0.0, 0.0, lot["id"])

        after = validate_success(api_client.get_lot(lot["id"], clinic["admin_headers"]))
        assert after["running_on_hand_mg"] == pytest.approx(0.0, abs=0.0001)
        assert after["status"] == "DEPLETED"

    def test_a_depleted_lot_is_no_longer_a_selector_candidate(self):
        """PRD 2.9: "The candidate set is every lot satisfying all of the
        following: it belongs to the dose's program; its medication matches the
        order's medication; its status is `IN_USE`; it is not expired; its
        `running_on_hand_mg` is at least the dose's `ordered_mg`."
        PRD 2.9: "If the candidate set is empty the dispense fails with
        `ERR_NO_ELIGIBLE_LOT` (HTTP 409)."

        Design: Corner/state_machines/inventory_lot_depletes_automatically_at_zero_on_hand
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        lot = validate_success(api_client.create_lot(
            create_lot_payload(clinic["program"]["id"], lot_number="LOT-TINY",
                               quantity_received_mg=90.0, reusable_for_take_home=False),
            clinic["admin_headers"]), 201)
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-09-02T06:30:00Z")
        first = schedule_dose(clinic, order["id"], "2026-09-02", "2026-09-02T07:00:00Z",
                              inventory_lot_id=lot["id"])
        check_in_dose(clinic, first["id"])
        verify_dose(clinic, first["id"], True)
        dispense_dose(clinic, first["id"], 90.0, 0.0, 0.0, lot["id"])

        depleted = validate_success(api_client.get_lot(lot["id"], clinic["admin_headers"]))
        assert depleted["status"] == "DEPLETED"

        second = schedule_dose(clinic, order["id"], "2026-09-03", "2026-09-03T07:00:00Z",
                               inventory_lot_id=lot["id"])
        check_in_dose(clinic, second["id"])
        verify_dose(clinic, second["id"], True)
        # No inventory_lot_id: the selector must run and find no `IN_USE` lot,
        # since the only lot in the program emptied to DEPLETED. Naming the lot
        # explicitly would take the explicit-lot path instead and report the
        # priority-21 ceiling rather than the empty candidate set.
        res = api_client.dispense_dose(second["id"], {
            "dispensed_mg": 90.0, "wasted_mg": 0.0, "returned_mg": 0.0},
            clinic["nurse_headers"])
        validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_LOT.value)