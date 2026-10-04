"""Breadth tests: authorization ordering, witness conditions, referential
checks and action-endpoint cascades."""

import pytest

from test_helpers import (
    api_client,
    get_success_data,
    setup_clinic,
    setup_active_patient,
    setup_approvable_carry_patient,
    setup_denied_privilege_and_routed_exception,
    hold_privilege,
    evaluate_privilege,
    schedule_dose,
    check_in_dose,
    verify_dose,
    list_doses,
    list_privileges,
    set_clock,
    create_lot_payload,
    create_transaction_payload,
    create_patient_payload,
    create_dose_order_payload,
    build_user_headers,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
)


class TestAuthorizationPrecedesExistence:
    """A missing header outranks a missing resource."""

    def test_an_unauthenticated_read_of_an_absent_patient_is_an_auth_error(self):
        """PRD 2.1: "If either header is absent, or if the supplied role is not
        one of the six declared roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD 2.11: "The request fails with the 404 code corresponding to the
        first identifier that does not resolve."

        Design: Corner/validations/auth_error_precedes_existence_on_a_nurse_reading_an_absent_patient
        """
        set_clock("2026-09-01T00:00:00Z")
        # A declared role reading an absent patient: existence is reported.
        declared = build_user_headers("op-1", "ProgramAdministrator")
        validate_error(api_client.get_patient(NON_EXISTENT_UUID, declared),
                       ApiErrorId.ERR_PATIENT_NOT_FOUND.value)

        # An undeclared role reading the same absent patient: auth is reported.
        undeclared = build_user_headers("op-2", "RegisteredNurse")
        err = validate_error(api_client.get_patient(NON_EXISTENT_UUID, undeclared),
                             ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)
        assert err["error_id"] != ApiErrorId.ERR_PATIENT_NOT_FOUND.value, (
            "the auth check is ordered above existence")


class TestRoleAuthorizationPrecedesStateGate:
    """The role gate and the state gate are distinct and ordered."""

    def test_a_counselor_is_refused_before_the_state_check_is_reached(self):
        """PRD 2.1: "Role membership alone is not sufficient to perform an
        operation: if the acting role is not among the roles authorized for
        that operation, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD 3.6: "The privilege must still be `PENDING_REVIEW`, else
        `ERR_PRIVILEGE_NOT_PENDING` (HTTP 409)."
        PRD 3.6: "Evaluation is also available against a privilege already in
        `DENIED`."

        Design: Corner/validations/role_denial_precedes_the_state_gate_for_a_counselor_granting_a_carry
        """
        clinic = setup_clinic(allotted_carries=10, with_counselor=True)
        patient, order = setup_approvable_carry_patient(clinic, ordered_daily_mg=90.0)
        priv = hold_privilege(clinic, patient["id"], patient["version"], requested_carries=1)
        validate_success(evaluate_privilege(clinic, priv["id"]))
        after = validate_success(api_client.get_privilege(priv["id"], clinic["director_headers"]))
        assert after["decision"] == "APPROVED"

        counselor_res = api_client.evaluate_privilege(priv["id"], clinic["counselor_headers"])
        err_authz = validate_error(counselor_res,
                                   ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

        director_res = api_client.evaluate_privilege(priv["id"], clinic["director_headers"])
        err_state = validate_error(director_res, ApiErrorId.ERR_PRIVILEGE_NOT_PENDING.value)
        assert err_authz["error_id"] != err_state["error_id"], (
            "the role gate and the state gate are distinct and ordered")


class TestDoseOrderForeignKeys:
    """Body foreign keys resolve against the patient, not the path."""

    def test_a_foreign_key_is_validated_and_a_program_is_denormalized(self):
        """PRD 2.11: "Foreign keys supplied in a request body are validated in
        the order the endpoint's input list declares them, and a failure yields
        the same family of 404 codes."
        PRD 3.3: "At creation the system snapshots the applicable regulatory
        ceiling into `medication_ceiling_mg`: the program's
        `max_daily_mg_methadone` when the medication is methadone."
        PRD 3.3: "The order is created in `DRAFT` status."

        Design: Corner/validations/cross_entity_validation_of_patient_program_against_the_dose_order
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        patient = get_success_data(api_client.create_patient(
            create_patient_payload(clinic["program"]["id"]), clinic["physician_headers"]))

        res = api_client.create_dose_order(
            create_dose_order_payload(NON_EXISTENT_UUID), clinic["physician_headers"])
        validate_error(res, ApiErrorId.ERR_PATIENT_NOT_FOUND.value)

        order = validate_success(api_client.create_dose_order(
            create_dose_order_payload(patient["id"]), clinic["physician_headers"]), 201)
        assert order["status"] == "DRAFT"
        assert order["patient_id"] == patient["id"]
        assert order["program_id"] == clinic["program"]["id"]
        assert order["medication_ceiling_mg"] == pytest.approx(120.0, abs=0.01)


class TestSlotBucketIsCollective:
    """The day bucket is global to the program, not per patient."""

    def test_a_third_dose_on_a_two_slot_day_is_a_collective_violation(self):
        """PRD 2.8: "The slot capacity counts the occupants of an open day and
        permits equality to hold — the `max_daily_dose_slots`-th dose is
        accepted, and the one after it is refused."
        PRD 2.8: "a day already holding `max_daily_dose_slots` non-terminal
        doses is rejected with `ERR_NO_DOSE_CAPACITY`."

        Design: Corner/validations/aggregate_validation_blocks_the_dose_that_exceeds_the_slot_bucket
        """
        clinic = setup_clinic(
            program_overrides={"name": "BayMark Mesa", "max_daily_dose_slots": 2},
            lot_overrides={"lot_number": "LOT-MESA", "quantity_received_mg": 900.0})
        set_clock("2026-09-01T00:00:00Z")
        one, order_one = setup_active_patient(clinic, ordered_daily_mg=30.0,
                                              government_id_hash="sha256:aaaa0001")
        two, order_two = setup_active_patient(clinic, ordered_daily_mg=30.0,
                                              full_name="Bea Patient",
                                              government_id_hash="sha256:aaaa0002")
        set_clock("2026-09-02T05:00:00Z")

        first = schedule_dose(clinic, order_one["id"], "2026-09-02", "2026-09-02T07:00:00Z",
                              inventory_lot_id=clinic["lot"]["id"])
        second = schedule_dose(clinic, order_two["id"], "2026-09-02", "2026-09-02T08:00:00Z",
                               inventory_lot_id=clinic["lot"]["id"])
        assert first["id"] != second["id"]

        res = api_client.create_dose_dispense({
            "dose_order_id": order_one["id"], "dose_date": "2026-09-02",
            "scheduled_datetime": "2026-09-02T09:00:00Z",
            "source_type": "OBSERVED_CLINIC",
            "inventory_lot_id": clinic["lot"]["id"]}, clinic["nurse_headers"])
        err = validate_error(res, ApiErrorId.ERR_NO_DOSE_CAPACITY.value)
        assert err["error_id"] != ApiErrorId.ERR_DUPLICATE_ACTIVE_DOSE.value

        rows, _meta = validate_paginated(api_client.list_dose_dispenses(
            clinic["nurse_headers"],
            {"program_id": clinic["program"]["id"], "dose_date": "2026-09-02"}))
        assert len(rows) == 2


class TestDiscontinueCascadesToScheduledDoses:
    """The discontinue side effect is executed, not merely declared."""

    def _setup(self):
        clinic = setup_clinic(lot_overrides={"lot_number": "LOT-A1"})
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        doses = []
        for date in ("2026-09-02", "2026-09-03"):
            doses.append(schedule_dose(clinic, order["id"], date, f"{date}T07:00:00Z",
                                       inventory_lot_id=clinic["lot"]["id"]))
        return clinic, patient, order, doses

    def test_the_scheduled_doses_are_cancelled_by_the_order_action(self):
        """PRD 3.3: "Discontinuation is available from `DRAFT`, `ACTIVE` or
        `SUSPENDED` ... it likewise cancels the order's `SCHEDULED` doses."
        PRD 3.4: "Cancellation is available from `SCHEDULED`,
        `ARRIVED_AT_CLINIC` or `NURSE_VERIFIED` and moves the dose to
        `CANCELLED`."

        Design: Corner/endpoints/dose_order_discontinue_cascades_to_scheduled_doses
        """
        clinic, patient, order, doses = self._setup()
        discontinued = validate_success(
            api_client.discontinue_dose_order(order["id"], clinic["physician_headers"]))
        assert discontinued["status"] == "DISCONTINUED"

        for dose in doses:
            after = validate_success(api_client.get_dose_dispense(dose["id"],
                                                                  clinic["nurse_headers"]))
            assert after["status"] == "CANCELLED"

    def test_a_later_check_in_against_the_cancelled_dose_fails(self):
        """PRD 3.4: "The dose must be `SCHEDULED`, else `ERR_DOSE_NOT_SCHEDULED`
        (HTTP 409)."
        PRD 2.9: "`running_on_hand_mg` as its received quantity plus the sum of
        `quantity_mg` over its `InventoryTransaction` rows."

        Design: Corner/endpoints/dose_order_discontinue_cascades_to_scheduled_doses
        """
        clinic, patient, order, doses = self._setup()
        validate_success(api_client.discontinue_dose_order(order["id"],
                                                           clinic["physician_headers"]))
        validate_error(api_client.check_in(doses[0]["id"], clinic["nurse_headers"]),
                       ApiErrorId.ERR_DOSE_NOT_SCHEDULED.value)

        remaining = list_doses(clinic, {"dose_order_id": order["id"], "status": "SCHEDULED"},
                               clinic["admin_headers"])
        assert remaining == []
        lot = validate_success(api_client.get_lot(clinic["lot"]["id"], clinic["admin_headers"]))
        assert lot["running_on_hand_mg"] == pytest.approx(50000.0, abs=0.01)


class TestWitnessRequirementIsConditional:
    """A receipt needs no witness; a destruction cannot be self-witnessed."""

    def test_the_witness_condition_binds_only_waste_and_destruction(self):
        """PRD 3.12: "A `witness_staff_id` is required for `WASTE` and
        `DESTRUCTION` movements, and must differ from the acting user, else
        `ERR_WITNESS_REQUIRED` (HTTP 422)."
        PRD 3.12: "New rows begin in `RECORDED`, and the lot's
        `running_on_hand_mg` is recomputed after each one."

        Design: Corner/endpoints/inventory_movement_rejects_a_witness_that_is_the_actor
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        lot = validate_success(api_client.create_lot(
            create_lot_payload(clinic["program"]["id"], lot_number="LOT-W",
                               quantity_received_mg=500.0), clinic["admin_headers"]), 201)

        receipt = validate_success(api_client.create_transaction(
            create_transaction_payload(lot["id"], "RECEIPT", 100.0),
            clinic["admin_headers"]), 201)
        assert receipt["status"] == "RECORDED"

        actor_headers = build_user_headers("operator-77", "ProgramAdministrator")
        validate_error(api_client.create_transaction(
            create_transaction_payload(lot["id"], "DESTRUCTION", -10.0,
                                       witness_staff_id="operator-77"), actor_headers),
            ApiErrorId.ERR_WITNESS_REQUIRED.value)

        destroyed = validate_success(api_client.create_transaction(
            create_transaction_payload(lot["id"], "DESTRUCTION", -10.0,
                                       witness_staff_id="staff-witness-77"), actor_headers), 201)
        assert destroyed["witness_staff_id"] == "staff-witness-77"

        rows, _meta = validate_paginated(api_client.list_transactions(
            clinic["admin_headers"], {"lot_id": lot["id"]}))
        assert len(rows) == 2
        after = validate_success(api_client.get_lot(lot["id"], clinic["admin_headers"]))
        assert after["running_on_hand_mg"] == pytest.approx(590.0, abs=0.01)


class TestReissueSourceMustBeRevoked:
    """The reissue link is only legal against a revoked source."""

    def test_a_non_revoked_source_is_refused_and_a_missing_one_is_not_found(self):
        """PRD 3.6: "When the request carries a `reissued_from_privilege_id`,
        that privilege's decision must be `REVOKED`, else the request is refused
        with `ERR_REISSUE_SOURCE_NOT_REVOKED` (HTTP 409)."
        PRD 3.6: "This is what closes the cycle `APPROVED` to `REVOKED` back to
        `PENDING_REVIEW` and on to `APPROVED` again."

        Design: Corner/endpoints/reissue_of_a_non_revoked_privilege_is_rejected
        """
        clinic = setup_clinic(allotted_carries=10)
        patient, order = setup_approvable_carry_patient(clinic, ordered_daily_mg=90.0)
        priv = hold_privilege(clinic, patient["id"], patient["version"], requested_carries=1)
        validate_success(evaluate_privilege(clinic, priv["id"]))
        approved = validate_success(api_client.get_privilege(priv["id"], clinic["director_headers"]))
        assert approved["decision"] == "APPROVED"

        current = get_success_data(api_client.get_patient(patient["id"], clinic["director_headers"]))
        res_not_revoked = api_client.create_privilege({
            "patient_id": patient["id"], "requested_carries": 1, "carry_interval_days": 7,
            "expected_patient_version": current["version"],
            "reissued_from_privilege_id": priv["id"]}, clinic["director_headers"])
        err_not_revoked = validate_error(res_not_revoked,
                                         ApiErrorId.ERR_REISSUE_SOURCE_NOT_REVOKED.value)

        res_missing = api_client.create_privilege({
            "patient_id": patient["id"], "requested_carries": 1, "carry_interval_days": 7,
            "expected_patient_version": current["version"],
            "reissued_from_privilege_id": NON_EXISTENT_UUID}, clinic["director_headers"])
        err_missing = validate_error(res_missing, ApiErrorId.ERR_PRIVILEGE_NOT_FOUND.value)

        assert err_not_revoked["error_id"] != err_missing["error_id"], (
            "the referential check and the state check are distinct")

        rows = list_privileges(clinic, {"patient_id": patient["id"]}, clinic["director_headers"])
        assert len(rows) == 1


class TestDoseMassBalance:
    """The mass-balance rule is an exact equality."""

    def _setup(self):
        clinic = setup_clinic(lot_overrides={"lot_number": "LOT-A1"})
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-09-02T06:30:00Z")
        dose = schedule_dose(clinic, order["id"], "2026-09-02", "2026-09-02T07:00:00Z",
                             inventory_lot_id=clinic["lot"]["id"])
        check_in_dose(clinic, dose["id"])
        verify_dose(clinic, dose["id"], True)
        return clinic, patient, order, dose

    def test_a_short_dispense_is_refused_then_the_exact_one_succeeds(self):
        """PRD 3.4: "The dispensed, wasted and returned milligrams must sum
        exactly to the dose's `ordered_mg`, with every component non-negative,
        else `ERR_DOSE_MASS_MISMATCH` (HTTP 422)."

        Design: Corner/errors/err_dose_mass_mismatch_on_a_partial_dispense
        """
        clinic, patient, order, dose = self._setup()
        res = api_client.dispense_dose(dose["id"], {
            "dispensed_mg": 89.5, "wasted_mg": 0.0, "returned_mg": 0.0,
            "inventory_lot_id": clinic["lot"]["id"]}, clinic["nurse_headers"])
        validate_error(res, ApiErrorId.ERR_DOSE_MASS_MISMATCH.value)

        after = validate_success(api_client.get_dose_dispense(dose["id"], clinic["nurse_headers"]))
        assert after["status"] == "NURSE_VERIFIED", (
            "a failed dispense must leave the dose where it was")
        lot = validate_success(api_client.get_lot(clinic["lot"]["id"], clinic["admin_headers"]))
        assert lot["running_on_hand_mg"] == pytest.approx(50000.0, abs=0.01), (
            "no movement may be written by the failed attempt")

    def test_the_exact_mass_balance_is_accepted(self):
        """PRD 3.4: "on success the dose's `scheduled_datetime` is replaced and
        the tariff is recomputed."
        PRD 3.4: "A `DISPENSE` movement is appended with a negative `quantity_mg`
        equal to the dispensed milligrams and the selected lot recorded as
        `lot_id`."

        Design: Corner/errors/err_dose_mass_mismatch_on_a_partial_dispense
        """
        clinic, patient, order, dose = self._setup()
        dispensed = validate_success(api_client.dispense_dose(dose["id"], {
            "dispensed_mg": 90.0, "wasted_mg": 0.0, "returned_mg": 0.0,
            "inventory_lot_id": clinic["lot"]["id"]}, clinic["nurse_headers"]))
        assert dispensed["status"] == "DISPENSED"

        rows, _meta = validate_paginated(api_client.list_transactions(
            clinic["admin_headers"], {"lot_id": clinic["lot"]["id"]}))
        assert len(rows) == 1
        assert rows[0]["quantity_mg"] == pytest.approx(-90.0)


class TestWithdrawalCompletionPhaseGate:
    """The withdrawal gate reads the phase dimension."""

    def test_completing_withdrawal_from_the_wrong_phase_is_refused(self):
        """PRD 3.14: "It requires the patient to be `ACTIVE`, else
        `ERR_PATIENT_NOT_ACTIVE` (HTTP 409); the patient's `treatment_phase`
        must be `MEDICAL_WITHDRAWAL`, else `ERR_NOT_IN_WITHDRAWAL_PHASE`
        (HTTP 409)."
        PRD 3.14: "On success the patient moves to `COMPLETED_WITHDRAWAL`,
        `ACTIVE` dose orders become `DISCONTINUED`."

        Design: Corner/errors/err_not_in_withdrawal_phase_on_completing_withdrawal_too_early
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)

        res = api_client.complete_withdrawal(patient["id"], clinic["director_headers"])
        validate_error(res, ApiErrorId.ERR_NOT_IN_WITHDRAWAL_PHASE.value)
        still_active = validate_success(api_client.get_patient(patient["id"],
                                                               clinic["director_headers"]))
        assert still_active["status"] == "ACTIVE"

        validate_success(api_client.patch_treatment_phase(patient["id"], {
            "treatment_phase": "MEDICAL_WITHDRAWAL"}, clinic["director_headers"]))
        withdrawn = validate_success(api_client.complete_withdrawal(
            patient["id"], clinic["director_headers"]))
        assert withdrawn["status"] == "COMPLETED_WITHDRAWAL"

        order_after = validate_success(api_client.get_dose_order(order["id"],
                                                                 clinic["physician_headers"]))
        assert order_after["status"] == "DISCONTINUED"

    def test_the_phase_move_is_visible_before_the_completion(self):
        """PRD 3.2: "The `treatment_phase` dimension takes one of four values —
        `INDUCTION`, `STABILIZATION`, `MAINTENANCE` or `MEDICAL_WITHDRAWAL` —
        and defaults to `INDUCTION` at registration."
        PRD 3.14: "Completion of a medically managed withdrawal is the other
        door, and it is a `MedicalDirector`'s act."

        Design: Corner/errors/err_not_in_withdrawal_phase_on_completing_withdrawal_too_early
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        moved = validate_success(api_client.patch_treatment_phase(patient["id"], {
            "treatment_phase": "MEDICAL_WITHDRAWAL"}, clinic["director_headers"]))
        assert moved["treatment_phase"] == "MEDICAL_WITHDRAWAL"


class TestDualEnrollmentScreening:
    """The registry key is the pair of hash and date of birth."""

    def test_a_colliding_pair_blocks_the_second_admission(self):
        """PRD 3.1: "The registry matches on the pair formed by the
        `government_id_hash` and the `date_of_birth`, using the hash verbatim as
        the screening key. The hash is stored opaquely, so two records collide
        only when both the hash and the date of birth agree."
        PRD 3.1: "The patient's time-in-treatment tracker row must report a
        dual-enrollment screening flag of false, or the request is refused with
        `ERR_DUAL_ENROLLMENT_DETECTED` (HTTP 409)."

        Design: Corner/errors/err_dual_enrollment_detected_blocks_a_second_admission
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        first = get_success_data(api_client.create_patient(
            create_patient_payload(clinic["program"]["id"], government_id_hash="sha256:dup00001"),
            clinic["physician_headers"]))
        second = get_success_data(api_client.create_patient(
            create_patient_payload(clinic["program"]["id"], full_name="Dana P Patient",
                                   government_id_hash="sha256:dup00001"),
            clinic["physician_headers"]))

        # Both rows share the screening key from registration. The PRD fixes two
        # things here: the pair collides, and an admission whose tracker row
        # reports a true dual-enrollment flag is refused with
        # ERR_DUAL_ENROLLMENT_DETECTED. It does not declare which rows the
        # registry screen counts, so it does not fix whether the first or the
        # second admission is the one refused — both readings are faithful, and
        # the assertions below hold under either.
        results = [
            (who, api_client.confirm_diagnosis(row["id"], clinic["physician_headers"]))
            for who, row in (("first", first), ("second", second))
        ]
        refused = [(who, res) for who, res in results if not (200 <= res.status_code < 300)]
        assert refused, "a colliding pair must refuse at least one admission"
        for _who, res in refused:
            validate_error(res, ApiErrorId.ERR_DUAL_ENROLLMENT_DETECTED.value)

        rows = {"first": first, "second": second}
        for who, res in results:
            if not (200 <= res.status_code < 300):
                blocked = validate_success(api_client.get_patient(
                    rows[who]["id"], clinic["physician_headers"]))
                assert blocked["diagnosis_confirmed"] is False
                break

        flagged = validate_success(api_client.get_time_in_treatment_tracker(
            second["id"], clinic["physician_headers"]))
        row = flagged[0] if isinstance(flagged, list) else flagged
        assert row["dual_enrollment_flag"] is True, (
            "the time-in-treatment tracker row reports the collision")

    def test_a_distinct_hash_admits_normally(self):
        """PRD 3.1: "The hash is stored opaquely, so two records collide only
        when both the hash and the date of birth agree."
        PRD 3.1: "Confirmation has consequences that ripple through the rest of
        the patient's record. The `diagnosis_confirmed` flag is set true."

        Design: Corner/errors/err_dual_enrollment_detected_blocks_a_second_admission
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        first = get_success_data(api_client.create_patient(
            create_patient_payload(clinic["program"]["id"], government_id_hash="sha256:dup00001"),
            clinic["physician_headers"]))
        validate_success(api_client.confirm_diagnosis(first["id"], clinic["physician_headers"]))

        distinct = get_success_data(api_client.create_patient(
            create_patient_payload(clinic["program"]["id"], full_name="Faye Patient",
                                   government_id_hash="sha256:uniq00002"),
            clinic["physician_headers"]))
        admitted = validate_success(api_client.confirm_diagnosis(
            distinct["id"], clinic["physician_headers"]))
        assert admitted["status"] == "ADMITTED"
        assert admitted["diagnosis_confirmed"] is True