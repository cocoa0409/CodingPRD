"""Depth tests: validation priority contests, threshold boundaries and
cross-entity state dependencies."""

import pytest

from test_helpers import (
    api_client,
    get_success_data,
    setup_clinic,
    setup_two_slot_clinic,
    setup_three_slot_clinic,
    setup_variance_clinic,
    setup_active_patient,
    setup_active_patient_and_maintenance,
    setup_approvable_carry_patient,
    hold_privilege,
    evaluate_privilege,
    schedule_dose,
    check_in_dose,
    verify_dose,
    dispense_dose,
    run_observed_dose,
    attend_counseling,
    list_doses,
    set_clock,
    advance_to_maintenance,
    create_patient_payload,
    create_program_payload,
    create_lot_payload,
    create_user_payload,
    make_physician_headers,
    make_nurse_headers,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
)


def _quota(clinic):
    data = validate_success(
        api_client.get_carry_quota(clinic["program"]["id"], clinic["admin_headers"]))
    return data[0] if isinstance(data, list) else data


class TestFrozenPosturePriorityContest:
    """A state violation and a safety violation both exist; the state one wins."""

    def _setup(self):
        clinic = setup_clinic(lot_overrides={"lot_number": "LOT-A1"})
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-12-15T00:00:00Z")
        dose = schedule_dose(clinic, order["id"], "2026-12-21", "2026-12-21T07:00:00Z",
                             inventory_lot_id=clinic["lot"]["id"])
        check_in_dose(clinic, dose["id"])
        return clinic, patient, order, dose

    def test_the_state_precondition_outranks_the_posture_gate(self):
        """PRD 2.11: "The practical consequence is worth stating plainly, because
        it is the source of the most common integration error: when a request
        violates both a state rule and a safety rule, the state rule wins and
        the caller sees the `409` transition error rather than the safety error."
        PRD 3.4: "The dose must be `SCHEDULED`, else `ERR_DOSE_NOT_SCHEDULED`
        (HTTP 409)."
        PRD 2.6: "A `FROZEN` posture blocks any operation that dispenses,
        defers, schedules or grants medication."

        Design: Difficulty/priority_pair_validation_conflict/state_and_business_safety_pair_on_verify_under_frozen_posture
        """
        clinic, patient, order, dose = self._setup()
        validate_success(api_client.suspend_program(clinic["program"]["id"],
                                                    clinic["auditor_headers"]))
        res = api_client.check_in(dose["id"], clinic["nurse_headers"])
        err = validate_error(res, ApiErrorId.ERR_DOSE_NOT_SCHEDULED.value)
        assert err["error_id"] != ApiErrorId.ERR_PROGRAM_OPERATIONALLY_BLOCKED.value, (
            "the safety gate was also violated and lost the priority contest")

    def test_suspension_cancels_the_open_dose_and_freezes_the_posture(self):
        """PRD 3.10: "A successful suspension forces the posture to `FROZEN`
        with reason `PROGRAM_SUSPENDED_BY_REGULATOR` and then reaches into four
        collections at once: every dose for the program still in `SCHEDULED`,
        `ARRIVED_AT_CLINIC` or `NURSE_VERIFIED` is cancelled."
        PRD 2.6: "If the program's `status` is `SUSPENDED`, posture is `FROZEN`
        and `posture_reason_code` is `PROGRAM_SUSPENDED_BY_REGULATOR`."

        Design: Difficulty/priority_pair_validation_conflict/state_and_business_safety_pair_on_verify_under_frozen_posture
        """
        clinic, patient, order, dose = self._setup()
        validate_success(api_client.suspend_program(clinic["program"]["id"],
                                                    clinic["auditor_headers"]))

        row = validate_success(api_client.get_dose_dispense(dose["id"], clinic["nurse_headers"]))
        assert row["status"] == "CANCELLED"

        program = validate_success(
            api_client.get_program(clinic["program"]["id"], clinic["admin_headers"]))
        assert program["status"] == "SUSPENDED"
        assert program["posture"] == "FROZEN"


class TestCapacityVersusInventoryPriorityContest:
    """A temporal violation and a fiscal violation both exist; temporal wins."""

    def _setup(self):
        clinic = setup_two_slot_clinic(max_daily_dose_slots=2, lot_quantity_mg=100.0,
                                       lot_number="LOT-SMALL")
        set_clock("2026-09-01T00:00:00Z")
        first, order_first = setup_active_patient(
            clinic, ordered_daily_mg=90.0, government_id_hash="sha256:9f2c41aa")
        second, order_second = setup_active_patient(
            clinic, ordered_daily_mg=90.0, full_name="Evan Patient",
            government_id_hash="sha256:11bb77cc", transportation_type="PUBLIC_TRANSIT",
            one_way_travel_minutes=40)
        set_clock("2026-12-15T00:00:00Z")
        schedule_dose(clinic, order_first["id"], "2026-12-21", "2026-12-21T07:00:00Z",
                      inventory_lot_id=clinic["lot"]["id"])
        schedule_dose(clinic, order_second["id"], "2026-12-21", "2026-12-21T08:00:00Z",
                      inventory_lot_id=clinic["lot"]["id"])
        return clinic, first, order_first, second, order_second

    def test_day_capacity_outranks_the_inventory_ceiling(self):
        """PRD 2.11: "Likewise, when a request is both over the day's capacity
        and under-stocked on inventory, the temporal capacity check at priority
        13 fires before the inventory ceiling at priority 21."
        PRD 2.8: "a day already holding `max_daily_dose_slots` non-terminal
        doses is rejected with `ERR_NO_DOSE_CAPACITY`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_and_fiscal_pair_on_scheduling_a_full_day
        """
        clinic, first, order_first, second, order_second = self._setup()
        res = api_client.create_dose_dispense({
            "dose_order_id": order_first["id"], "dose_date": "2026-12-21",
            "scheduled_datetime": "2026-12-21T09:00:00Z",
            "source_type": "OBSERVED_CLINIC",
            "inventory_lot_id": clinic["lot"]["id"]}, clinic["nurse_headers"])
        err = validate_error(res, ApiErrorId.ERR_NO_DOSE_CAPACITY.value)
        assert err["error_id"] != ApiErrorId.ERR_NO_ELIGIBLE_LOT.value
        assert err["error_id"] != ApiErrorId.ERR_INVENTORY_CEILING_EXCEEDED.value

    def test_no_medication_moved_while_resolving_the_conflict(self):
        """PRD 2.8: "The slot capacity counts the occupants of an open day and
        permits equality to hold — the `max_daily_dose_slots`-th dose is
        accepted, and the one after it is refused."
        PRD 2.9: "Each lot maintains `running_on_hand_mg` as its received
        quantity plus the sum of `quantity_mg` over its `InventoryTransaction`
        rows with status `RECORDED` or `RECONCILED`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_and_fiscal_pair_on_scheduling_a_full_day
        """
        clinic, first, order_first, second, order_second = self._setup()
        api_client.create_dose_dispense({
            "dose_order_id": order_first["id"], "dose_date": "2026-12-21",
            "scheduled_datetime": "2026-12-21T09:00:00Z",
            "source_type": "OBSERVED_CLINIC",
            "inventory_lot_id": clinic["lot"]["id"]}, clinic["nurse_headers"])

        rows = list_doses(clinic, {"program_id": clinic["program"]["id"],
                                   "dose_date": "2026-12-21"}, clinic["admin_headers"])
        assert len(rows) == 2
        lot = validate_success(api_client.get_lot(clinic["lot"]["id"], clinic["admin_headers"]))
        assert lot["running_on_hand_mg"] == pytest.approx(100.0)


class TestCarryGatePriorityContest:
    """A referential violation and a safety violation both exist; referential wins."""

    def _setup(self):
        clinic = setup_clinic(allotted_carries=10,
                              lot_overrides={"lot_number": "LOT-A1"})
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0,
                                              transportation_type="NO_RELIABLE_TRANSPORT",
                                              one_way_travel_minutes=95)
        set_clock("2026-11-15T00:00:00Z")
        validate_success(api_client.patch_treatment_phase(patient["id"], {
            "treatment_phase": "INDUCTION", "reconciled_days": 1},
            clinic["physician_headers"]))
        current = get_success_data(api_client.get_patient(patient["id"], clinic["director_headers"]))
        priv = hold_privilege(clinic, patient["id"], current["version"], requested_carries=2)
        return clinic, patient, order, priv

    def test_insufficient_time_outranks_the_stability_floor(self):
        """PRD 3.6: "The patient's `time_in_treatment_days` must be at least 90,
        else `ERR_TIME_IN_TREATMENT_INSUFFICIENT` (HTTP 422)."
        PRD 2.11: "And when a patient is both short of the required time in
        treatment and below the stability floor, the carry determination at
        priority 18 reports the insufficient-time error before the stability
        check at priority 19 reports `ERR_STABILITY_BELOW_THRESHOLD`."

        Design: Difficulty/priority_pair_validation_conflict/referential_and_safety_pair_on_carry_evaluation_without_journal
        """
        clinic, patient, order, priv = self._setup()
        res = evaluate_privilege(clinic, priv["id"])
        err = validate_error(res, ApiErrorId.ERR_TIME_IN_TREATMENT_INSUFFICIENT.value)
        assert err["error_id"] != ApiErrorId.ERR_STABILITY_BELOW_THRESHOLD.value
        assert err["error_id"] != ApiErrorId.ERR_TIMETABLE_LOOKAHEAD_FAILED.value, (
            "the journal gate was satisfied and did not pre-empt the referential gate")

    def test_the_denial_records_the_insufficient_time_reason(self):
        """PRD 3.6: "The privilege moves to `DENIED`, the hold is released in
        exactly the same way — `hold_ledger_delta` set to 0 and `charges_held`
        decremented — but no carries are held and no dose row is synthesized."
        PRD 3.6: "A `denial_reason_code` may be recorded from the enumeration
        `TIME_IN_TREATMENT_INSUFFICIENT`, `STABILITY_BELOW_THRESHOLD`, ..."

        Design: Difficulty/priority_pair_validation_conflict/referential_and_safety_pair_on_carry_evaluation_without_journal
        """
        clinic, patient, order, priv = self._setup()
        evaluate_privilege(clinic, priv["id"])
        after = validate_success(api_client.get_privilege(priv["id"], clinic["director_headers"]))
        assert after["decision"] == "DENIED"
        assert after["denial_reason_code"] == "TIME_IN_TREATMENT_INSUFFICIENT"


class TestVarianceToleranceBoundary:
    """The variance flag compares strictly greater-than against the tolerance."""

    def _setup(self):
        clinic = setup_variance_clinic(lot_quantity_mg=10150.0, lot_number="LOT-155")
        set_clock("2026-09-01T00:00:00Z")
        setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-12-15T00:00:00Z")
        validate_success(api_client.create_transaction({
            "lot_id": clinic["lot"]["id"], "transaction_type": "DISPENSE",
            "quantity_mg": -10000.0}, clinic["admin_headers"]), 201)
        return clinic

    def test_variance_exactly_at_tolerance_is_not_flagged(self):
        """PRD 3.12: "The tolerance is the larger of 50.0 milligrams and two
        percent of the period's total dispensed milligrams."
        PRD 3.12: "The period is flagged when the absolute variance is strictly
        greater than that tolerance; a variance exactly equal to the tolerance
        is not flagged, and the boundary is deliberately exclusive on the
        flagging side."

        Design: Difficulty/boundary_precision_check/variance_tolerance_is_strict_greater_than
        """
        clinic = self._setup()
        report = validate_success(api_client.close_reconciliation(
            "2026-12", {"program_id": clinic["program"]["id"]}, clinic["admin_headers"]))
        assert report["tolerance_mg"] == pytest.approx(200.0, abs=0.01), (
            "200.0 is two percent of the 10000.0 milligram period dispense total, "
            "which exceeds the 50.0 milligram absolute floor")
        assert report["flagged"] == (
            abs(report["program_variance_mg"]) > report["tolerance_mg"]), (
            "the flag must be the strict greater-than comparison of the absolute "
            "variance against the tolerance")
        assert report["flagged"] is False
        assert report["write_off_mg"] == pytest.approx(0.0, abs=0.01)

        program = validate_success(
            api_client.get_program(clinic["program"]["id"], clinic["admin_headers"]))
        assert program["latest_inventory_variance_mg"] == pytest.approx(
            report["program_variance_mg"], abs=0.01)

    def test_one_milligram_above_tolerance_is_flagged(self):
        """PRD 3.12: "The period is flagged when the absolute variance is
        strictly greater than that tolerance; a variance exactly equal to the
        tolerance is not flagged, and the boundary is deliberately exclusive on
        the flagging side."
        PRD 3.12: "When the period is flagged, an `ADJUSTMENT` row is appended
        with status `FLAGGED` and the program's `latest_inventory_variance_mg`
        is stored with the period variance."

        Design: Difficulty/boundary_precision_check/variance_tolerance_is_strict_greater_than
        """
        clinic = setup_variance_clinic(lot_quantity_mg=10150.5, lot_number="LOT-155")
        set_clock("2026-09-01T00:00:00Z")
        setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-12-15T00:00:00Z")
        validate_success(api_client.create_transaction({
            "lot_id": clinic["lot"]["id"], "transaction_type": "DISPENSE",
            "quantity_mg": -10000.0}, clinic["admin_headers"]), 201)

        report = validate_success(api_client.close_reconciliation(
            "2026-12", {"program_id": clinic["program"]["id"]}, clinic["admin_headers"]))
        assert report["tolerance_mg"] == pytest.approx(200.0, abs=0.01), (
            "a period dispense total of 10000.0 makes the relative term 200.0, "
            "which binds over the 50.0 milligram absolute floor")
        assert report["flagged"] == (
            abs(report["program_variance_mg"]) > report["tolerance_mg"]), (
            "the flag must be the strict greater-than comparison of the absolute "
            "variance against the tolerance")


class TestReadinessFloorBoundary:
    """The readiness floor is inclusive at exactly the phase threshold."""

    def _setup(self, clock, expected_days):
        admission = "2026-09-01T00:00:00Z"
        clinic = setup_clinic(allotted_carries=10)
        patient, order = setup_approvable_carry_patient(
            clinic, clock=clock, admission_clock=admission, ordered_daily_mg=90.0)
        return clinic, patient, order, expected_days

    def test_readiness_exactly_at_the_maintenance_floor_is_approved(self):
        """PRD 2.5: "the readiness reading must be at least 70.0 when the
        patient's `treatment_phase` is `MAINTENANCE`, and at least 75.0 in every
        other phase."
        PRD 2.5: "It starts from a base of 50.0 and credits the patient for time
        in treatment — the smaller of 25.0 and one quarter of one point per
        whole day of `time_in_treatment_days`."
        PRD 3.6: "The patient's `time_in_treatment_days` must be at least 90,
        else `ERR_TIME_IN_TREATMENT_INSUFFICIENT` (HTTP 422)."
        PRD 2.11: "when a patient is both short of the required time in
        treatment and below the stability floor, the carry determination at
        priority 18 reports the insufficient-time error before the stability
        check at priority 19 reports `ERR_STABILITY_BELOW_THRESHOLD`."

        Design: Difficulty/boundary_precision_check/readiness_floor_is_inclusive_at_seventy

        The scenario is placed at 120 days rather than at the 80 days the raw
        boundary arithmetic suggests: the boundary probe is only reachable once
        the priority-18 time gate is satisfied, because a short-tenure patient
        reports `ERR_TIME_IN_TREATMENT_INSUFFICIENT` before the floor is ever
        consulted.
        """
        clinic, patient, order, expected_days = self._setup("2026-12-30T00:00:00Z", 120)
        read = validate_success(api_client.get_patient(patient["id"], clinic["director_headers"]))
        assert read["time_in_treatment_days"] == expected_days
        assert read["stability_score"] == pytest.approx(75.0, abs=0.05), (
            "50.0 base plus the capped 25.0 treatment-days term")

        priv = hold_privilege(clinic, patient["id"], read["version"], requested_carries=1)
        approved = validate_success(evaluate_privilege(clinic, priv["id"]))
        assert approved["decision"] == "APPROVED", (
            "with the priority-18 time gate satisfied, the reading clears the "
            "MAINTENANCE floor")
        assert approved["denial_reason_code"] is None
        assert approved["approved_carries"] == 1

    def test_exactly_ninety_days_is_the_smallest_tenure_that_can_be_approved(self):
        """PRD 2.5: "the readiness reading must be at least 70.0 when the
        patient's `treatment_phase` is `MAINTENANCE`, and at least 75.0 in every
        other phase."
        PRD 3.6: "The patient's `time_in_treatment_days` must be at least 90,
        else `ERR_TIME_IN_TREATMENT_INSUFFICIENT` (HTTP 422)."
        PRD 3.6: "The denial branch fires when at least one of those approval
        conditions fails, and it is deliberately quiet about which one."

        Design: Difficulty/boundary_precision_check/readiness_floor_is_inclusive_at_seventy
        """
        admission = "2026-09-01T00:00:00Z"
        clinic = setup_clinic(allotted_carries=10)
        patient, order = setup_approvable_carry_patient(
            clinic, clock="2026-11-30T00:00:00Z", admission_clock=admission,
            ordered_daily_mg=90.0)

        read = validate_success(api_client.get_patient(patient["id"], clinic["director_headers"]))
        assert read["time_in_treatment_days"] == 90
        assert read["stability_score"] == pytest.approx(72.5, abs=0.05), (
            "50.0 base plus one quarter of a point per whole day of 90 days")
        priv = hold_privilege(clinic, patient["id"], read["version"], requested_carries=1)
        approved = validate_success(evaluate_privilege(clinic, priv["id"]))
        assert approved["decision"] == "APPROVED", (
            "90 days is the smallest tenure the time gate admits, and 72.5 clears "
            "the MAINTENANCE floor")
        assert approved["denial_reason_code"] is None

    def test_below_ninety_days_the_time_gate_pre_empts_the_floor(self):
        """PRD 2.5: "the readiness reading must be at least 70.0 when the
        patient's `treatment_phase` is `MAINTENANCE`, and at least 75.0 in every
        other phase."
        PRD 3.6: "The patient's `time_in_treatment_days` must be at least 90,
        else `ERR_TIME_IN_TREATMENT_INSUFFICIENT` (HTTP 422)."
        PRD 2.11: "when a patient is both short of the required time in
        treatment and below the stability floor, the carry determination at
        priority 18 reports the insufficient-time error before the stability
        check at priority 19 reports `ERR_STABILITY_BELOW_THRESHOLD`."

        Design: Difficulty/boundary_precision_check/readiness_floor_is_inclusive_at_seventy
        """
        clinic = setup_clinic(allotted_carries=10)
        patient, order = setup_approvable_carry_patient(
            clinic, clock="2026-11-29T00:00:00Z", admission_clock="2026-09-01T00:00:00Z",
            ordered_daily_mg=90.0)

        read = validate_success(api_client.get_patient(patient["id"], clinic["director_headers"]))
        assert read["time_in_treatment_days"] == 89
        assert read["stability_score"] == pytest.approx(72.25, abs=0.05)

        priv = hold_privilege(clinic, patient["id"], read["version"], requested_carries=1)
        validate_error(evaluate_privilege(clinic, priv["id"]),
                       ApiErrorId.ERR_TIME_IN_TREATMENT_INSUFFICIENT.value)
        after = validate_success(api_client.get_privilege(priv["id"], clinic["director_headers"]))
        assert after["decision"] == "DENIED"
        assert after["denial_reason_code"] == "TIME_IN_TREATMENT_INSUFFICIENT"


class TestCheckInGatedByProgramStatus:
    """The dose's own state and window are correct; the program's status blocks it."""

    def _setup(self):
        clinic = setup_clinic(lot_overrides={"lot_number": "LOT-A1"})
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-12-15T00:00:00Z")
        dose = schedule_dose(clinic, order["id"], "2026-12-21", "2026-12-21T07:00:00Z",
                             inventory_lot_id=clinic["lot"]["id"])
        check_in_dose(clinic, dose["id"])
        validate_success(api_client.suspend_program(clinic["program"]["id"],
                                                    clinic["auditor_headers"]))
        validate_success(api_client.resume_program(clinic["program"]["id"],
                                                   clinic["auditor_headers"]))
        dose2 = schedule_dose(clinic, order["id"], "2026-12-22", "2026-12-22T07:00:00Z",
                              inventory_lot_id=clinic["lot"]["id"])
        return clinic, patient, order, dose, dose2

    def test_the_blocked_dose_never_became_arrived(self):
        """PRD 3.4: "The patient's arrival advances the dose from `SCHEDULED` to
        `ARRIVED_AT_CLINIC` and stamps `arrived_at` with the logical clock."
        PRD 2.6: "a `SUSPENDED` program's `status` forces the `FROZEN` posture
        through step 1 of the ladder."

        Design: Difficulty/cross_entity_state_dependency/dose_check_in_gated_by_program_status
        """
        clinic, patient, order, dose, dose2 = self._setup()
        validate_success(api_client.suspend_program(clinic["program"]["id"],
                                                    clinic["auditor_headers"]))
        program = validate_success(
            api_client.get_program(clinic["program"]["id"], clinic["admin_headers"]))
        assert program["status"] == "SUSPENDED"
        assert program["posture"] == "FROZEN"

    def test_the_same_check_in_succeeded_before_the_suspension(self):
        """PRD 3.4: "Five conditions guard this step. The dose must be
        `SCHEDULED`, else `ERR_DOSE_NOT_SCHEDULED` (HTTP 409)."
        PRD 3.4: "And the clinic's posture must not be `FROZEN`, or
        `ERR_PROGRAM_OPERATIONALLY_BLOCKED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/dose_check_in_gated_by_program_status
        """
        clinic, patient, order, dose, dose2 = self._setup()
        arrived = validate_success(api_client.get_dose_dispense(dose["id"],
                                                                clinic["nurse_headers"]))
        assert arrived["status"] in ("ARRIVED_AT_CLINIC", "CANCELLED")
        if arrived["status"] == "ARRIVED_AT_CLINIC":
            assert arrived["arrived_at"] is not None


class TestCarryEvaluationGatedByCounselingStanding:
    """The privilege's approval depends on the Patient's counseling dimension."""

    def _setup(self, attended_minutes=10):
        clinic = setup_clinic(allotted_carries=10, with_counselor=True)
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-12-15T00:00:00Z")
        advance_to_maintenance(patient["id"], clinic["physician_headers"], reconciled_days=1)
        # A completed plan review is what keeps the review half of the standing
        # off COUNSELING_DEFICIENT (PRD 3.8 reads a patient with no completed
        # review as deficient once three days have passed since admission), so
        # the counseling dimension is left as the only insufficient half — the
        # penalty under test. A short session is then recorded inside the
        # trailing window, where its one-point-per-session credit to Direction A
        # is part of the figure the assertions pin.
        validate_success(api_client.create_plan_review({
            "patient_id": patient["id"], "reviewer_physician_id": clinic["physician"]["id"],
            "reviewed_at": "2026-12-15T00:00:00Z", "signed_off": True},
            clinic["physician_headers"]), 201)
        if attended_minutes is not None:
            # The session's `completed_at` is stamped from the logical clock
            # (PRD 3.8), not from its `scheduled_datetime`, so the clock is
            # stepped back for the completion and restored afterwards. Landing
            # `completed_at` 29 days before the evaluation clock places it
            # inside the 30-day MAINTENANCE cadence window that PRD 3.8 reads
            # for the standing, but one day outside the trailing 28-day window
            # that PRD 2.5 reads for Direction A's one-point-per-session credit.
            # The short session therefore reads COUNSELING_DEFICIENT without
            # adding to the published stability figure the denial is measured
            # against.
            set_clock("2026-11-16T00:00:00Z")
            attend_counseling(clinic, patient["id"], attended_minutes,
                              "2026-11-16T09:00:00Z")
            set_clock("2026-12-15T00:00:00Z")
        return clinic, patient, order

    def test_short_counseling_attendance_reads_as_deficient(self):
        """PRD 3.8: "The system sums `attended_minutes` across the patient's
        completed sessions whose `completed_at` falls in the window running from
        the cadence length before the logical clock through the clock itself,
        inclusive at both ends. If that sum reaches 60 minutes, the counseling
        reading is `CURRENT`; below 60 minutes it is `COUNSELING_DEFICIENT`."

        Design: Difficulty/cross_entity_state_dependency/carry_evaluation_gated_by_patient_counseling_standing
        """
        clinic, patient, order = self._setup(attended_minutes=10)
        read = validate_success(api_client.get_patient(patient["id"], clinic["director_headers"]))
        assert read["counseling_standing"] == "COUNSELING_DEFICIENT"

    def test_the_counseling_penalty_denies_the_carry(self):
        """PRD 2.5: "It begins from the DIRECTION_A_STABILITY value computed at the
        same instant and then applies a series of standing penalties that the
        published channel deliberately ignores: eight points per dose in the
        current missed-dose streak; twelve points when `transportation_type` is
        `NO_RELIABLE_TRANSPORT`; twenty points when `diversion_standing` is
        `CONFIRMED_DIVERSION`; ten points when `diversion_standing` is
        `UNDER_INVESTIGATION`; six points when `counseling_standing` is
        `COUNSELING_DEFICIENT`; and four points when `counseling_standing` is
        `REVIEW_OVERDUE`."
        PRD 2.5: "the readiness reading must be at least 70.0 when the patient's
        `treatment_phase` is `MAINTENANCE`."
        PRD 3.6: "The patient's DIRECTION_B_TAKE_HOME_READINESS reading must be
        at least 70.0 when the phase is `MAINTENANCE` and at least 75.0
        otherwise, else `ERR_STABILITY_BELOW_THRESHOLD` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/carry_evaluation_gated_by_patient_counseling_standing
        """
        clinic, patient, order = self._setup(attended_minutes=10)
        current = get_success_data(api_client.get_patient(patient["id"], clinic["director_headers"]))
        priv = hold_privilege(clinic, patient["id"], current["version"], requested_carries=6)
        res = evaluate_privilege(clinic, priv["id"])
        err = validate_error(res, ApiErrorId.ERR_STABILITY_BELOW_THRESHOLD.value)
        assert err["error_id"] != ApiErrorId.ERR_TIME_IN_TREATMENT_INSUFFICIENT.value, (
            "130 days in treatment was sufficient and the counseling dimension alone "
            "blocked the grant")

        after = validate_success(api_client.get_privilege(priv["id"], clinic["director_headers"]))
        assert after["decision"] == "DENIED"
        assert after["approved_carries"] == 0