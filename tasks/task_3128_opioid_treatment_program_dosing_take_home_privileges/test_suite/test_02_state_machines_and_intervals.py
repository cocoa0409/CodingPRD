"""Depth tests: non-linear state machines, fork-join branches and interval semantics."""

import pytest

from test_helpers import (
    api_client,
    get_success_data,
    setup_clinic,
    setup_active_patient,
    setup_active_patient_and_maintenance,
    setup_approvable_carry_patient,
    setup_origin_and_receiving_clinic,
    setup_three_slot_clinic,
    setup_permit_clinic,
    hold_privilege,
    evaluate_privilege,
    schedule_dose,
    check_in_dose,
    verify_dose,
    list_doses,
    list_privileges,
    set_clock,
    advance_to_maintenance,
    create_arrangement_payload,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
)


def _quota(clinic):
    data = validate_success(
        api_client.get_carry_quota(clinic["program"]["id"], clinic["admin_headers"]))
    return data[0] if isinstance(data, list) else data


def _ledger(clinic, patient_id):
    data, _meta = validate_paginated(api_client.list_carry_ledgers(
        clinic["director_headers"], {"patient_id": patient_id}))
    return data[0]


class TestPrivilegeCycleApproveRevokeReissue:
    """The TakeHomePrivilege machine is cyclic, not a pipeline."""

    def _setup(self):
        # The approval branch requires the DIRECTION_B_TAKE_HOME_READINESS
        # reading to clear the phase floor, so the patient must carry a
        # genuinely CURRENT counseling standing before the evaluation runs.
        # Since PRD 2.5 makes a COUNSELING_DEFICIENT standing a six-point
        # readiness penalty, a patient with no completed plan review and no
        # credited counseling minutes (PRD 3.8) sits below the MAINTENANCE
        # floor and the evaluation would evaluate to the denial branch.
        clinic = setup_clinic(allotted_carries=10)
        patient, order = setup_approvable_carry_patient(clinic, ordered_daily_mg=90.0)
        priv = hold_privilege(clinic, patient["id"], patient["version"], requested_carries=1)
        validate_success(evaluate_privilege(clinic, priv["id"]))
        return clinic, patient, order, priv

    def test_revocation_frees_the_carry_and_returns_it_to_the_pool(self):
        """PRD 3.10: "The decision becomes `REVOKED`, `freed_carries` is set to
        the privilege's `approved_carries` so the program pool can reclaim the
        slots, and `approved_carries` is reset to 0."
        PRD 3.7: "On revocation, the program's `granted_carries` is reduced by
        `freed_carries`."
        PRD 2.7: "From these the ledger derives `available_carries`, the global
        conserved quantity C1, which must equal `allotted_carries` minus
        `granted_carries` at all times."

        Design: Difficulty/non_linear_state_machine/take_home_privilege_cycle_approve_revoke_reissue
        """
        clinic, patient, order, priv = self._setup()
        validate_success(api_client.revoke_privilege(priv["id"], clinic["director_headers"]))
        revoked = get_success_data(api_client.get_privilege(priv["id"], clinic["director_headers"]))
        assert revoked["decision"] == "REVOKED"
        assert revoked["freed_carries"] == 1
        assert revoked["approved_carries"] == 0

        quota = _quota(clinic)
        assert quota["granted_carries"] == 0
        assert quota["available_carries"] == 10

    def test_reissue_reopens_the_cycle_at_pending_review(self):
        """PRD 3.6: "A reissue creates a fresh privilege row in `PENDING_REVIEW`
        with `hold_ledger_delta` of -1, raising `charges_held` and
        `carries_held` by one each exactly as a first-time request does."
        PRD 3.6: "This is what closes the cycle `APPROVED` to `REVOKED` back to
        `PENDING_REVIEW` and on to `APPROVED` again."
        PRD 2.7: "`carry_variance` is a second conserved quantity that must stay
        at 0 across every privilege and exception action."

        Design: Difficulty/non_linear_state_machine/take_home_privilege_cycle_approve_revoke_reissue
        """
        clinic, patient, order, priv = self._setup()
        validate_success(api_client.revoke_privilege(priv["id"], clinic["director_headers"]))
        current = get_success_data(api_client.get_patient(patient["id"], clinic["director_headers"]))
        priv2 = hold_privilege(clinic, patient["id"], current["version"], requested_carries=1,
                               reissued_from_privilege_id=priv["id"])
        assert priv2["decision"] == "PENDING_REVIEW"
        assert priv2["reissued_from_privilege_id"] == priv["id"]

        ledger = _ledger(clinic, patient["id"])
        assert ledger["carry_variance"] == 0


class TestDoseDispenseForkJoin:
    """From one state, three triggers fork to divergent branches."""

    def _setup(self):
        clinic = setup_clinic(lot_overrides={"lot_number": "LOT-A1",
                                             "reusable_for_take_home": True})
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-12-15T00:00:00Z")
        fork_a = schedule_dose(clinic, order["id"], "2026-12-21", "2026-12-21T07:00:00Z",
                               inventory_lot_id=clinic["lot"]["id"])
        fork_b = schedule_dose(clinic, order["id"], "2026-12-22", "2026-12-22T07:00:00Z",
                               inventory_lot_id=clinic["lot"]["id"])
        fork_c = schedule_dose(clinic, order["id"], "2026-12-23", "2026-12-23T07:00:00Z",
                               inventory_lot_id=clinic["lot"]["id"])
        for dose in (fork_a, fork_b, fork_c):
            check_in_dose(clinic, dose["id"])
        return clinic, patient, order, fork_a, fork_b, fork_c

    def test_verify_success_and_failure_branches_diverge(self):
        """PRD 3.4: "A successful verification moves the dose to
        `NURSE_VERIFIED` and sets `verification_result` to `PASSED`."
        PRD 3.4: "A failed verification moves the dose to
        `VERIFICATION_FAILED`, sets `verification_result` to `FAILED`."
        PRD 3.4: "A patient who arrives and cannot prove identity is turned away
        without being penalised as a defaulter."

        Design: Difficulty/non_linear_state_machine/dose_dispense_fork_join_three_way_branch
        """
        clinic, patient, order, fork_a, fork_b, fork_c = self._setup()
        a = verify_dose(clinic, fork_a["id"], True)
        b = verify_dose(clinic, fork_b["id"], False)

        assert a["status"] == "NURSE_VERIFIED"
        assert a["verification_result"] == "PASSED"
        assert b["status"] == "VERIFICATION_FAILED"
        assert b["verification_result"] == "FAILED"

    def test_cancel_branch_stamps_completed_at_and_stays_terminal(self):
        """PRD 3.4: "Cancellation is available from `SCHEDULED`,
        `ARRIVED_AT_CLINIC` or `NURSE_VERIFIED` and moves the dose to
        `CANCELLED` with `completed_at` stamped."
        PRD 3.4: "The terminal statuses of this state machine are `COMPLETED`,
        `VERIFICATION_FAILED`, `REFUSED`, `MISSED` and `CANCELLED`."

        Design: Difficulty/non_linear_state_machine/dose_dispense_fork_join_three_way_branch
        """
        clinic, patient, order, fork_a, fork_b, fork_c = self._setup()
        verify_dose(clinic, fork_a["id"], True)
        verify_dose(clinic, fork_b["id"], False)
        c = validate_success(api_client.cancel_dose(fork_c["id"], clinic["nurse_headers"]))
        assert c["status"] == "CANCELLED"
        assert c["completed_at"] is not None

    def test_only_the_verified_branch_can_reach_dispensed(self):
        """PRD 3.4: "The dose must be `NURSE_VERIFIED`, else
        `ERR_DOSE_NOT_VERIFIED` (HTTP 409)."
        PRD 2.9: "A lot's `status` moves through `RECEIVED`, `IN_USE`, `DEPLETED`,
        `QUARANTINED` and `DESTROYED`. It becomes `IN_USE` automatically when
        the first transaction referencing it is recorded."

        Design: Difficulty/non_linear_state_machine/dose_dispense_fork_join_three_way_branch
        """
        clinic, patient, order, fork_a, fork_b, fork_c = self._setup()
        verify_dose(clinic, fork_a["id"], True)
        verify_dose(clinic, fork_b["id"], False)
        api_client.cancel_dose(fork_c["id"], clinic["nurse_headers"])

        res = api_client.dispense_dose(fork_b["id"], {
            "dispensed_mg": 90.0, "wasted_mg": 0.0, "returned_mg": 0.0,
            "inventory_lot_id": clinic["lot"]["id"]}, clinic["nurse_headers"])
        validate_error(res, ApiErrorId.ERR_DOSE_NOT_VERIFIED.value)

        lot_txs = [t for t in _all_transactions(clinic) if t["lot_id"] == clinic["lot"]["id"]]
        assert len(lot_txs) == 0, "no inventory movement may occur from a failed branch"


class TestClinicDaySlotCapacity:
    """Day-slot capacity counts occupants and permits equality."""

    def test_equality_with_the_slot_limit_is_accepted(self):
        """PRD 2.8: "The slot capacity counts the occupants of an open day and
        permits equality to hold — the `max_daily_dose_slots`-th dose is
        accepted, and the one after it is refused."
        PRD 2.8: "a day already holding `max_daily_dose_slots` non-terminal
        doses is rejected with `ERR_NO_DOSE_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/clinic_open_day_slot_capacity_uses_count_semantics_with_equality_allowed
        """
        clinic = setup_three_slot_clinic(max_daily_dose_slots=3)
        set_clock("2026-09-01T00:00:00Z")
        patients, orders = [], []
        for i, name in enumerate(("Ada Patient", "Bea Patient", "Cara Patient")):
            patient, order = setup_active_patient(
                clinic, ordered_daily_mg=30.0, full_name=name,
                government_id_hash=f"sha256:aaaa000{i + 1}")
            patients.append(patient)
            orders.append(order)
        set_clock("2026-12-15T00:00:00Z")

        scheduled = []
        for i, order in enumerate(orders):
            res = api_client.create_dose_dispense({
                "dose_order_id": order["id"], "dose_date": "2026-12-21",
                "scheduled_datetime": f"2026-12-21T0{7 + i}:00:00Z",
                "source_type": "OBSERVED_CLINIC",
                "inventory_lot_id": clinic["lot"]["id"]}, clinic["nurse_headers"])
            assert res.status_code == 201, (
                f"slot {i + 1} of 3 should be accepted, got {res.status_code}: {res.text}")
            scheduled.append(validate_success(res, 201))
        rows = list_doses(clinic, {"program_id": clinic["program"]["id"],
                                   "dose_date": "2026-12-21"}, clinic["admin_headers"])
        assert len(rows) == 3

    def test_the_next_occupant_is_refused_as_capacity(self):
        """PRD 2.8: "a day already holding `max_daily_dose_slots` non-terminal
        doses is rejected with `ERR_NO_DOSE_CAPACITY`."
        PRD 2.8: "a patient who already has a non-terminal dose on the same
        `dose_date` is rejected with `ERR_DUPLICATE_ACTIVE_DOSE`."

        Design: Difficulty/resource_temporal_overlap/clinic_open_day_slot_capacity_uses_count_semantics_with_equality_allowed
        """
        clinic = setup_three_slot_clinic(max_daily_dose_slots=3)
        set_clock("2026-09-01T00:00:00Z")
        patients, orders = [], []
        for i, name in enumerate(("Ada Patient", "Bea Patient", "Cara Patient")):
            patient, order = setup_active_patient(
                clinic, ordered_daily_mg=30.0, full_name=name,
                government_id_hash=f"sha256:aaaa000{i + 1}")
            patients.append(patient)
            orders.append(order)
        set_clock("2026-12-15T00:00:00Z")

        for i, order in enumerate(orders):
            api_client.create_dose_dispense({
                "dose_order_id": order["id"], "dose_date": "2026-12-21",
                "scheduled_datetime": f"2026-12-21T0{7 + i}:00:00Z",
                "source_type": "OBSERVED_CLINIC",
                "inventory_lot_id": clinic["lot"]["id"]}, clinic["nurse_headers"])

        res = api_client.create_dose_dispense({
            "dose_order_id": orders[0]["id"], "dose_date": "2026-12-21",
            "scheduled_datetime": "2026-12-21T10:00:00Z",
            "source_type": "OBSERVED_CLINIC",
            "inventory_lot_id": clinic["lot"]["id"]}, clinic["nurse_headers"])
        err = validate_error(res, ApiErrorId.ERR_NO_DOSE_CAPACITY.value)
        assert err["error_id"] != ApiErrorId.ERR_DUPLICATE_ACTIVE_DOSE.value, (
            "the rejection must be the day-capacity bucket, not the per-patient permit")


class TestDailyDosePermit:
    """The per-patient daily permit forecloses equality."""

    def _setup(self):
        clinic = setup_permit_clinic(max_daily_dose_slots=20)
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=60.0,
                                              split_dose_authorized=True)
        set_clock("2026-12-15T00:00:00Z")
        first = schedule_dose(clinic, order["id"], "2026-12-21", "2026-12-21T07:00:00Z",
                              inventory_lot_id=clinic["lot"]["id"])
        return clinic, patient, order, first

    def test_a_second_dose_on_the_same_date_is_refused(self):
        """PRD 2.8: "The per-patient daily rule is a uniqueness constraint and
        forecloses equality: two non-terminal doses for the same patient on the
        same `dose_date` are never permitted, though doses on adjacent dates
        obviously are."
        PRD 2.8: "a patient who already has a non-terminal dose on the same
        `dose_date` is rejected with `ERR_DUPLICATE_ACTIVE_DOSE`."

        Design: Difficulty/resource_temporal_overlap/daily_dose_permit_uses_equality_forbidden_semantics_per_patient
        """
        clinic, patient, order, first = self._setup()
        res = api_client.create_dose_dispense({
            "dose_order_id": order["id"], "dose_date": "2026-12-21",
            "scheduled_datetime": "2026-12-21T10:30:00Z",
            "source_type": "OBSERVED_CLINIC",
            "inventory_lot_id": clinic["lot"]["id"]}, clinic["nurse_headers"])
        err = validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVE_DOSE.value)
        assert err["error_id"] != ApiErrorId.ERR_NO_DOSE_CAPACITY.value, (
            "the shared day bucket had spare room and the per-patient permit was binding")

    def test_no_medication_moved_on_the_refused_scheduling(self):
        """PRD 3.4: "The `ordered_mg` is snapshotted from the active order's
        `ordered_daily_mg` together with its ceiling tariff, so that the dose is
        priced and checked against the values in force on the `dose_date`."
        PRD 2.9: "Each lot maintains `running_on_hand_mg` as its received
        quantity plus the sum of `quantity_mg` over its `InventoryTransaction`
        rows with status `RECORDED` or `RECONCILED`."

        Design: Difficulty/resource_temporal_overlap/daily_dose_permit_uses_equality_forbidden_semantics_per_patient
        """
        clinic, patient, order, first = self._setup()
        assert first["dose_date"] == "2026-12-21"
        api_client.create_dose_dispense({
            "dose_order_id": order["id"], "dose_date": "2026-12-21",
            "scheduled_datetime": "2026-12-21T10:30:00Z",
            "source_type": "OBSERVED_CLINIC",
            "inventory_lot_id": clinic["lot"]["id"]}, clinic["nurse_headers"])

        rows = list_doses(clinic, {"dose_order_id": order["id"],
                                   "dose_date": "2026-12-21"}, clinic["admin_headers"])
        assert len(rows) == 1
        lot = validate_success(api_client.get_lot(clinic["lot"]["id"], clinic["admin_headers"]))
        assert lot["running_on_hand_mg"] == pytest.approx(900.0)


class TestGuestTravelWindowOverlap:
    """The travel window must intersect the receiving clinic's open days."""

    def _setup(self):
        origin, receiving = setup_origin_and_receiving_clinic()
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(origin, ordered_daily_mg=16.0,
                                              medication="BUPRENORPHINE",
                                              government_id_hash="sha256:cccc0001")
        set_clock("2026-12-15T00:00:00Z")
        return origin, receiving, patient, order

    def test_a_window_landing_on_the_open_day_is_accepted(self):
        """PRD 3.11: "And the receiving program must have an open clinic day
        whose window overlaps the requested travel window, else
        `ERR_NO_OVERLAPPING_VISIT_WINDOW` (HTTP 409) — an arrangement to dose at
        a clinic that is closed for the whole trip is not an arrangement."
        PRD 3.11: "On success, two things are written. The arrangement receives
        a server-issued one-time `dose_authorization_token`, and its
        `authorized_mg` is set to the patient's active dose order's
        `ordered_daily_mg`."

        Design: Difficulty/resource_temporal_overlap/guest_travel_window_uses_half_open_intersection_semantics
        """
        origin, receiving, patient, order = self._setup()
        current = get_success_data(api_client.get_patient(patient["id"], origin["physician_headers"]))
        arr = validate_success(api_client.create_arrangement(
            create_arrangement_payload(patient["id"], receiving["program"]["id"],
                                       current["version"], "2026-12-19", "2026-12-19"),
            origin["admin_headers"]), 201)
        transmitted = validate_success(
            api_client.transmit_arrangement(arr["id"], origin["admin_headers"]))
        assert transmitted["status"] == "PENDING_RECEIVING_ACK"
        assert transmitted["dose_authorization_token"] is not None
        assert transmitted["authorized_mg"] == pytest.approx(16.0, abs=0.01)

    def test_a_window_outside_the_receiving_open_days_is_refused(self):
        """PRD 3.11: "And the receiving program must have an open clinic day
        whose window overlaps the requested travel window, else
        `ERR_NO_OVERLAPPING_VISIT_WINDOW` (HTTP 409)."
        PRD 3.11: "The receiving program must have `guest_dosing_enabled` true,
        else `ERR_GUEST_DOSING_NOT_ENABLED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/guest_travel_window_uses_half_open_intersection_semantics
        """
        origin, receiving, patient, order = self._setup()
        current = get_success_data(api_client.get_patient(patient["id"], origin["physician_headers"]))
        arr_ok = validate_success(api_client.create_arrangement(
            create_arrangement_payload(patient["id"], receiving["program"]["id"],
                                       current["version"], "2026-12-19", "2026-12-19"),
            origin["admin_headers"]), 201)
        validate_success(api_client.transmit_arrangement(arr_ok["id"], origin["admin_headers"]))

        # Transmitting the first arrangement advanced the patient's version, so
        # the second create must re-read it (PRD 2.10).
        fresh = get_success_data(api_client.get_patient(patient["id"], origin["physician_headers"]))
        arr_bad = validate_success(api_client.create_arrangement(
            create_arrangement_payload(patient["id"], receiving["program"]["id"],
                                       fresh["version"], "2026-12-20", "2026-12-20"),
            origin["admin_headers"]), 201)
        res = api_client.transmit_arrangement(arr_bad["id"], origin["admin_headers"])
        err = validate_error(res, ApiErrorId.ERR_NO_OVERLAPPING_VISIT_WINDOW.value)
        assert err["error_id"] != ApiErrorId.ERR_GUEST_DOSING_NOT_ENABLED.value, (
            "the receiving clinic does accept guests, so the failure is the window")

        bad = get_success_data(api_client.get_arrangement(arr_bad["id"], origin["admin_headers"]))
        assert bad["status"] == "DRAFT"
        assert bad["dose_authorization_token"] is None


def _all_transactions(clinic):
    data, _meta = validate_paginated(api_client.list_transactions(clinic["admin_headers"]))
    return data