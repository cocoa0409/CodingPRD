"""Depth tests: transitive cascades across privilege, dose, lot and ledger."""

import pytest

from test_helpers import (
    api_client,
    get_success_data,
    setup_clinic,
    setup_active_patient,
    setup_approvable_carry_patient,
    hold_privilege,
    evaluate_privilege,
    schedule_dose,
    mark_missed,
    list_doses,
    list_transactions,
    set_clock,
    advance_to_maintenance,
    create_diversion_case_payload,
    create_exception_payload,
    validate_success,
    validate_paginated,
)


def _quota(clinic):
    data = validate_success(
        api_client.get_carry_quota(clinic["program"]["id"], clinic["admin_headers"]))
    return data[0] if isinstance(data, list) else data


def _ledger(clinic, patient_id):
    data, _meta = validate_paginated(api_client.list_carry_ledgers(
        clinic["director_headers"], {"patient_id": patient_id}))
    return data[0]


def _setup_approved_carry(clinic, patient_id, requested_carries=1):
    """Active patient -> MAINTENANCE reconciled -> approved privilege -> doses."""
    current = get_success_data(api_client.get_patient(patient_id, clinic["director_headers"]))
    priv = hold_privilege(clinic, patient_id, current["version"], requested_carries)
    validate_success(evaluate_privilege(clinic, priv["id"]))
    priv = get_success_data(api_client.get_privilege(priv["id"], clinic["director_headers"]))
    doses = list_doses(clinic, {"privilege_id": priv["id"]}, clinic["director_headers"])
    return priv, doses


class TestDiversionConfirmationCascade:
    """DiversionCase -> TakeHomePrivilege -> DoseDispense -> InventoryLot."""

    def _setup(self):
        clinic = setup_clinic(allotted_carries=10,
                              lot_overrides={"lot_number": "LOT-A1",
                                             "reusable_for_take_home": True})
        patient, order = setup_approvable_carry_patient(clinic, ordered_daily_mg=90.0)
        priv, doses = _setup_approved_carry(clinic, patient["id"], requested_carries=1)
        case = validate_success(api_client.create_diversion_case(
            create_diversion_case_payload(clinic["program"]["id"], patient["id"],
                                          detection_source="COUNT_MISMATCH", severity="MAJOR"),
            clinic["auditor_headers"]), 201)
        validate_success(api_client.begin_review(case["id"], clinic["auditor_headers"]))
        return clinic, patient, order, priv, doses, case

    def test_confirmation_revokes_the_privilege(self):
        """PRD 3.10: "Confirmation is the heavy step: the case moves to
        `CONFIRMED` and stamps `confirmed_at`, the patient's
        `diversion_standing` becomes `CONFIRMED_DIVERSION`, the patient's
        `risk_score_points` is increased by 25.0 with the tier recut, and every
        privilege the patient holds whose decision is `APPROVED` or
        `APPROVED_WITH_EXCEPTION` is revoked."

        Design: Difficulty/transitive_cascade/diversion_confirmation_cascade_privilege_dose_lot
        """
        clinic, patient, order, priv, doses, case = self._setup()
        validate_success(api_client.confirm_diversion(case["id"], {
            "outcome_summary": "Count mismatch reproduced across two open days at the "
                               "dispensing window."}, clinic["auditor_headers"]))

        confirmed = validate_success(api_client.get_diversion_case(case["id"], clinic["auditor_headers"]))
        assert confirmed["status"] == "CONFIRMED"
        read = validate_success(api_client.get_patient(patient["id"], clinic["director_headers"]))
        assert read["diversion_standing"] == "CONFIRMED_DIVERSION"

        after = validate_success(api_client.get_privilege(priv["id"], clinic["director_headers"]))
        assert after["decision"] == "REVOKED"
        assert after["freed_carries"] == 1
        assert after["approved_carries"] == 0

    def test_cascade_reaches_the_dose_row_and_the_lot(self):
        """PRD 3.10: "Every take-home dose row belonging to this privilege that
        is still `SCHEDULED` is cancelled."
        PRD 3.10: "And, as a third hop, each cancelled take-home dose's
        referenced lot, named by its `inventory_lot_id`, is moved to
        `QUARANTINED`, removing it from the selector pool for everyone."
        PRD 3.10: "That third hop is the depth-three cascade from diversion
        confirmation down through privilege, dose and finally lot."

        Design: Difficulty/transitive_cascade/diversion_confirmation_cascade_privilege_dose_lot
        """
        clinic, patient, order, priv, doses, case = self._setup()
        assert doses, "setup must synthesize a take-home dose row"
        lot_id = doses[0]["inventory_lot_id"] or clinic["lot"]["id"]
        validate_success(api_client.confirm_diversion(case["id"], {
            "outcome_summary": "Count mismatch reproduced across two open days at the "
                               "dispensing window."}, clinic["auditor_headers"]))

        dose_after = validate_success(api_client.get_dose_dispense(doses[0]["id"],
                                                                   clinic["director_headers"]))
        assert dose_after["status"] == "CANCELLED"
        if dose_after["inventory_lot_id"]:
            lot = validate_success(api_client.get_lot(dose_after["inventory_lot_id"],
                                                      clinic["admin_headers"]))
            assert lot["status"] == "QUARANTINED"

        quota = _quota(clinic)
        assert quota["granted_carries"] == 0
        assert quota["available_carries"] == 10

    def test_posture_ladder_moves_the_program_to_restricted(self):
        """PRD 2.6: "Otherwise, if `open_diversion_case_count` is at least 1,
        posture is `RESTRICTED` and the reason code is `DIVERSION_CASE_OPEN`."
        PRD 2.6: "The ladder runs on every mutation of a diversion case, a
        corrective action, inventory variance, or program status; it does not
        wait to be asked."

        Design: Difficulty/transitive_cascade/diversion_confirmation_cascade_privilege_dose_lot
        """
        clinic, patient, order, priv, doses, case = self._setup()
        program = validate_success(
            api_client.get_program(clinic["program"]["id"], clinic["admin_headers"]))
        assert program["posture"] == "RESTRICTED"
        assert program["posture_reason_code"] == "DIVERSION_CASE_OPEN"


class TestExceptionGrantCascade:
    """TakeHomeException -> TakeHomePrivilege -> DoseDispense -> CarryQuotaLedger
    -> Patient."""

    def _setup(self):
        clinic = setup_clinic(allotted_carries=20,
                              lot_overrides={"lot_number": "LOT-A1",
                                             "reusable_for_take_home": True})
        # PRD 2.5 makes a COUNSELING_DEFICIENT standing a six-point readiness
        # penalty, and PRD 3.8 makes a patient with no completed plan review
        # read COUNSELING_DEFICIENT once the clock is three days past admission.
        # The patient is therefore admitted at the clock's own instant rather
        # than 105 days earlier: the tenure still clears the 90-day time gate
        # (the admission sweep counts whole days from the admission datetime),
        # while the review grace band keeps the standing off the deficient
        # reading that would floor domain B.
        set_clock("2026-12-15T00:00:00Z")
        patient, order = setup_approvable_carry_patient(
            clinic, clock="2026-12-15T00:00:00Z", admission_clock="2026-09-01T00:00:00Z",
            ordered_daily_mg=90.0)
        # Move to STABILIZATION so the ordinary path denies, then reconcile the
        # journal again so the exception path is well-formed.
        validate_success(api_client.patch_treatment_phase(patient["id"], {
            "treatment_phase": "STABILIZATION", "reconciled_days": 1},
            clinic["physician_headers"]))
        current = get_success_data(api_client.get_patient(patient["id"], clinic["director_headers"]))
        priv = hold_privilege(clinic, patient["id"], current["version"], requested_carries=6)
        res = api_client.evaluate_privilege(priv["id"], clinic["director_headers"])
        assert not (200 <= res.status_code < 300), (
            "setup expected the ordinary evaluation path to deny this privilege")
        priv = get_success_data(api_client.get_privilege(priv["id"], clinic["director_headers"]))
        assert priv["decision"] == "DENIED"

        exc = validate_success(api_client.create_exception(
            create_exception_payload(patient["id"], 4, clinic["director"]["id"], priv["version"]),
            clinic["physician_headers"]), 201)
        # Return the patient to MAINTENANCE *before* routing. PRD 3.9 sets
        # `evaluated_domain_b` at the routing step, to true exactly when the
        # readiness score has cleared the applicable floor, and a STABILIZATION
        # reading of 74.0 does not clear that phase's 75.0-or-over floor.
        validate_success(api_client.patch_treatment_phase(patient["id"], {
            "treatment_phase": "MAINTENANCE", "reconciled_days": 1},
            clinic["physician_headers"]))
        exc = validate_success(
            api_client.route_exception(exc["id"], clinic["physician_headers"]))
        return clinic, patient, order, priv, exc

    def test_grant_flips_the_exception_then_the_privilege(self):
        """PRD 3.9: "The grant then cascades into the privilege. The privilege
        whose `exception_id` equals this exception, and whose decision is
        `DENIED`, moves to `APPROVED_WITH_EXCEPTION`; its `evaluation_basis`
        becomes `PHASE_STABILITY`, recording that the phase table was the one
        read."
        PRD 3.9: "The exception itself becomes `GRANTED`."

        Design: Difficulty/transitive_cascade/exception_grant_cascade_privilege_carries_patient
        """
        clinic, patient, order, priv, exc = self._setup()
        granted = validate_success(api_client.decide_exception(
            exc["id"], {"decision": "GRANT", "granted_carries": 4}, clinic["director_headers"]))
        assert granted["status"] == "GRANTED"
        assert granted["granted_carries"] == 4
        assert granted["evaluated_domain_b"] is True

        after = validate_success(api_client.get_privilege(priv["id"], clinic["director_headers"]))
        assert after["decision"] == "APPROVED_WITH_EXCEPTION"
        assert after["evaluation_basis"] == "PHASE_STABILITY"
        assert after["exception_id"] == exc["id"]

    def test_grant_synthesizes_take_home_rows_and_debits_the_quota(self):
        """PRD 3.9: "Take-home dose rows are synthesized for each of the first
        `granted_carries` open days, with their `ordered_mg` summed into
        `carried_issued_mg`."
        PRD 2.7: "The ledger maintains `granted_carries` as the sum of
        `approved_carries` across all of the program's privilege rows whose
        `decision` is `APPROVED` or `APPROVED_WITH_EXCEPTION`."

        Design: Difficulty/transitive_cascade/exception_grant_cascade_privilege_carries_patient
        """
        clinic, patient, order, priv, exc = self._setup()
        validate_success(api_client.decide_exception(
            exc["id"], {"decision": "GRANT", "granted_carries": 4}, clinic["director_headers"]))

        rows = list_doses(clinic, {"privilege_id": priv["id"]}, clinic["director_headers"])
        assert len(rows) == 4, f"expected 4 synthesized take-home rows, got {len(rows)}"
        assert all(r["source_type"] == "TAKE_HOME_ISSUANCE" for r in rows)

        quota = _quota(clinic)
        assert quota["granted_carries"] == 4
        assert quota["available_carries"] == 16

    def test_grant_updates_the_patient_carry_ledger_milligrams(self):
        """PRD 2.7: "`carried_issued_mg` is the sum of `ordered_mg` over
        take-home dose rows ever created for the patient."
        PRD 2.7: "`carried_balance_mg` carries the expression `carried_issued_mg`
        minus `carried_voided_mg` minus `carried_dispensed_mg` minus
        `carried_consumed_mg`, and must remain 0.0 across every take-home
        dispense, waste, return and privilege void."

        Design: Difficulty/transitive_cascade/exception_grant_cascade_privilege_carries_patient
        """
        clinic, patient, order, priv, exc = self._setup()
        validate_success(api_client.decide_exception(
            exc["id"], {"decision": "GRANT", "granted_carries": 4}, clinic["director_headers"]))

        ledger = _ledger(clinic, patient["id"])
        assert ledger["carried_issued_mg"] == pytest.approx(360.0, abs=0.01)
        assert ledger["carried_voided_mg"] == pytest.approx(0.0, abs=0.01)
        assert ledger["carried_dispensed_mg"] == pytest.approx(0.0, abs=0.01)
        assert ledger["carried_balance_mg"] == pytest.approx(360.0, abs=0.01)


class TestMissedDoseCascade:
    """DoseDispense -> Patient -> DoseOrder -> DoseDispense -> TakeHomeCarryLedger."""

    def _setup(self, declare_carry=True):
        clinic = setup_clinic(allotted_carries=20,
                              lot_overrides={"lot_number": "LOT-A1",
                                             "reusable_for_take_home": True})
        patient, order = setup_approvable_carry_patient(clinic, ordered_daily_mg=90.0)
        priv = None
        if declare_carry:
            priv = hold_privilege(clinic, patient["id"], patient["version"], requested_carries=1)
            validate_success(evaluate_privilege(clinic, priv["id"]))
            priv = get_success_data(api_client.get_privilege(priv["id"],
                                                             clinic["director_headers"]))
        return clinic, patient, order, priv

    def test_third_streak_suspends_the_patient_and_the_order(self):
        """PRD 3.5: "When the recomputed `missed_dose_streak` reaches 3 or more,
        the patient's own transition to `SUSPENDED_NON_COMPLIANT` fires
        automatically, and every one of the patient's `ACTIVE` dose orders is
        moved to `SUSPENDED`."
        PRD 3.5: "the streak counts consecutive `MISSED` rows with no
        intervening `COMPLETED` row, ordered oldest `created_at` first."

        Design: Difficulty/transitive_cascade/missed_dose_cascade_patient_order_dose_ledger
        """
        clinic, patient, order, priv = self._setup()
        for date in ("2026-12-21", "2026-12-22"):
            dose = schedule_dose(clinic, order["id"], date, f"{date}T07:00:00Z",
                                 inventory_lot_id=clinic["lot"]["id"])
            mark_missed(clinic, dose["id"])
        third_date = "2026-12-23"
        third = schedule_dose(clinic, order["id"], third_date, f"{third_date}T07:00:00Z",
                              inventory_lot_id=clinic["lot"]["id"])
        missed = mark_missed(clinic, third["id"])
        assert missed["status"] == "MISSED"

        read = validate_success(api_client.get_patient(patient["id"], clinic["director_headers"]))
        assert read["missed_dose_streak"] == 3
        assert read["status"] == "SUSPENDED_NON_COMPLIANT"

        order_after = validate_success(api_client.get_dose_order(order["id"],
                                                                 clinic["physician_headers"]))
        assert order_after["status"] == "SUSPENDED"

    def test_cascade_cancels_remaining_scheduled_doses(self):
        """PRD 3.5: "Every dose for the patient still in `SCHEDULED`,
        `ARRIVED_AT_CLINIC` or `NURSE_VERIFIED` is cancelled."
        PRD 3.5: "That cascade is thorough."

        Design: Difficulty/transitive_cascade/missed_dose_cascade_patient_order_dose_ledger
        """
        clinic, patient, order, priv = self._setup()
        for date in ("2026-12-21", "2026-12-22", "2026-12-23"):
            dose = schedule_dose(clinic, order["id"], date, f"{date}T07:00:00Z",
                                 inventory_lot_id=clinic["lot"]["id"])
            if date != "2026-12-23":
                mark_missed(clinic, dose["id"])
            else:
                mark_missed(clinic, dose["id"])

        remaining = list_doses(clinic, {"dose_order_id": order["id"], "status": "SCHEDULED"},
                               clinic["admin_headers"])
        assert remaining == [], f"expected no SCHEDULED doses, got {len(remaining)}"

    def test_cascade_revokes_the_privilege_and_voids_the_carried_milligrams(self):
        """PRD 3.5: "Every privilege the patient holds with decision `APPROVED`
        or `APPROVED_WITH_EXCEPTION` is revoked, with `freed_carries` set to
        that privilege's `approved_carries`."
        PRD 3.5: "Take-home dose rows still `SCHEDULED` are cancelled, and the
        sum of their `ordered_mg` is added to the carry ledger's
        `carried_voided_mg` — which is what keeps the milligram identity of
        §2.7 balanced when carries are snatched back."

        Design: Difficulty/transitive_cascade/missed_dose_cascade_patient_order_dose_ledger
        """
        clinic, patient, order, priv = self._setup()
        assert priv is not None and priv["decision"] == "APPROVED"
        for date in ("2026-12-21", "2026-12-22", "2026-12-23"):
            dose = schedule_dose(clinic, order["id"], date, f"{date}T07:00:00Z",
                                 inventory_lot_id=clinic["lot"]["id"])
            mark_missed(clinic, dose["id"])

        priv_after = validate_success(api_client.get_privilege(priv["id"],
                                                               clinic["director_headers"]))
        assert priv_after["decision"] == "REVOKED"

        ledger = _ledger(clinic, patient["id"])
        assert ledger["carried_issued_mg"] == pytest.approx(90.0, abs=0.01)
        assert ledger["carried_voided_mg"] == pytest.approx(90.0, abs=0.01)
        assert ledger["carried_balance_mg"] == pytest.approx(0.0, abs=0.01)