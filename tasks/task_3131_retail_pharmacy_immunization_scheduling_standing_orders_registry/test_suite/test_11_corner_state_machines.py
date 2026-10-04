"""Corner tests — state_machines section: check-in window, questionnaire rules,
refer-out branch, administer precondition, no-show sweep, store suspension,
lot release, submission state preconditions.

PRD §3.4 counter pipeline, §3.8 registry lifecycle, §3.2 lot lifecycle.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_store, create_product, create_protocol, create_patient,
    create_lot, book_appointment, walk_appointment_to_screened,
    full_administration, get_submission_for_record,
)


def _mgr():
    return TEST_USERS["store_manager_headers"]


def _co():
    return TEST_USERS["compliance_headers"]


def _tech():
    return TEST_USERS["technician_headers"]


def _pharm():
    return TEST_USERS["pharmacist_headers"]


def _imm():
    return TEST_USERS["immunizer_headers"]


class TestCheckInValidTransitionAndWindowEnforcement:
    """Design: Corner/state_machines/check_in_valid_transition_and_window_enforcement"""

    def test_checkin_31_minutes_early_rejected(self, api):
        """PRD §3.4: "the logical clock must fall within the window from thirty minutes before `slot_start` through sixty minutes after it, inclusive; a missed window is rejected with `ERR_CHECKIN_WINDOW_MISSED`."

        Design: Corner/state_machines/check_in_valid_transition_and_window_enforcement
        """
        set_clock("2026-09-01T08:00:00Z")
        store = create_store(store_number="S-5", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat CI", date_of_birth="1980-01-01")
        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z")

        set_clock("2026-09-01T09:29:00Z")
        err = validate_error(
            api_client.check_in_appointment(appt["id"], _tech()),
            ApiErrorId.ERR_CHECKIN_WINDOW_MISSED,
        )
        assert err["error_id"] == "ERR_CHECKIN_WINDOW_MISSED"

    def test_checkin_at_exact_window_start_succeeds(self, api):
        """PRD §3.4: "the logical clock must fall within the window from thirty minutes before slot_start through sixty minutes after it, inclusive"
        PRD §3.4: "moving the appointment from `SCHEDULED` to `CHECKED_IN` and incrementing the appointment's `version`"

        Design: Corner/state_machines/check_in_valid_transition_and_window_enforcement
        """
        set_clock("2026-09-01T08:00:00Z")
        store = create_store(store_number="S-5", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat CI", date_of_birth="1980-01-01")
        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z")

        set_clock("2026-09-01T09:30:00Z")
        checked = validate_success(api_client.check_in_appointment(appt["id"], _tech()))
        assert checked["status"] == "CHECKED_IN"
        assert checked["version"] == 2


class TestQuestionnaireFromScheduledRejectedAndSecondQuestionnaireRejected:
    """Design: Corner/state_machines/questionnaire_from_scheduled_rejected_and_second_questionnaire_rejected"""

    def test_questionnaire_on_scheduled_rejected(self, api):
        """PRD §3.4: "submission against an appointment that is not `CHECKED_IN` fails with `ERR_APPOINTMENT_NOT_CHECKED_IN`"

        Design: Corner/state_machines/questionnaire_from_scheduled_rejected_and_second_questionnaire_rejected
        """
        store = create_store(store_number="S-6", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Q", date_of_birth="1980-01-01")
        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-03T10:00:00Z")

        err = validate_error(
            api_client.submit_questionnaire(appt["id"], {"answers": {"FEVER_TODAY": False}}, _tech()),
            ApiErrorId.ERR_APPOINTMENT_NOT_CHECKED_IN,
        )
        assert err["error_id"] == "ERR_APPOINTMENT_NOT_CHECKED_IN"

    def test_second_questionnaire_rejected(self, api):
        """PRD §3.4: "Exactly one questionnaire exists per appointment; a second submission fails with `ERR_QUESTIONNAIRE_ALREADY_EXISTS`"

        Design: Corner/state_machines/questionnaire_from_scheduled_rejected_and_second_questionnaire_rejected
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-6", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Q", date_of_birth="1980-01-01")
        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z", is_walk_in=True)
        api_client.check_in_appointment(appt["id"], _tech())
        api_client.submit_questionnaire(appt["id"], {"answers": {"FEVER_TODAY": False}}, _tech())

        err = validate_error(
            api_client.submit_questionnaire(appt["id"], {"answers": {"FEVER_TODAY": True}}, _tech()),
            ApiErrorId.ERR_QUESTIONNAIRE_ALREADY_EXISTS,
        )
        assert err["error_id"] == "ERR_QUESTIONNAIRE_ALREADY_EXISTS"


class TestReferOutBranchCancelsAppointmentFromScreened:
    """Design: Corner/state_machines/refer_out_branch_cancels_appointment_from_screened"""

    def test_refer_out_cancels_and_locks_appointment(self, api):
        """PRD §3.4: "with `outcome` of `REFER_OUT`, the only precondition is that the appointment be `SCREENED` (`ERR_APPOINTMENT_NOT_SCREENED`). The questionnaire's `review_outcome` is set to `REFERRED_OUT`, the appointment moves from `SCREENED` to `CANCELLED`"
        PRD §3.3: "a cancellation attempt in any later or terminal state fails with `ERR_APPOINTMENT_NOT_CANCELLABLE`"

        Design: Corner/state_machines/refer_out_branch_cancels_appointment_from_screened
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-7", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat RO", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z", is_walk_in=True)
        api_client.check_in_appointment(appt["id"], _tech())
        api_client.submit_questionnaire(appt["id"], {"answers": {"FEVER_TODAY": False}}, _tech())
        appt_now = get_success_data(api_client.get_appointment(appt["id"], _pharm()))

        reviewed = validate_success(api_client.review_consent(appt["id"],
            {"expected_appointment_version": appt_now["version"], "outcome": "REFER_OUT"}, _pharm()))
        assert reviewed["status"] == "CANCELLED"

        q = get_success_data(api_client.get_questionnaire(appt["id"], _pharm()))
        assert q[0]["review_outcome"] == "REFERRED_OUT"

        err = validate_error(
            api_client.cancel_appointment(appt["id"], _tech()),
            ApiErrorId.ERR_APPOINTMENT_NOT_CANCELLABLE,
        )
        assert err["error_id"] == "ERR_APPOINTMENT_NOT_CANCELLABLE"


class TestAdministerFromNonconsentedAppointmentRejected:
    """Design: Corner/state_machines/administer_from_nonconsented_appointment_rejected"""

    def test_administer_on_screened_rejected_and_no_side_effects(self, api):
        """PRD §3.5: "The appointment must be `CONSENTED` (`ERR_APPOINTMENT_NOT_CONSENTED`)."
        PRD §3.5: "A successful administration commits five effects atomically in one request."

        Design: Corner/state_machines/administer_from_nonconsented_appointment_rejected
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-8", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat NC", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z", is_walk_in=True)
        api_client.check_in_appointment(appt["id"], _tech())
        api_client.submit_questionnaire(appt["id"], {"answers": {"FEVER_TODAY": False}}, _tech())

        err = validate_error(
            api_client.administer(appt["id"], {"lot_id": lot["id"], "expected_lot_version": 1}, _imm()),
            ApiErrorId.ERR_APPOINTMENT_NOT_CONSENTED,
        )
        assert err["error_id"] == "ERR_APPOINTMENT_NOT_CONSENTED"

        lot_after = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        assert lot_after["doses_available"] == 5
        assert lot_after["version"] == 1


class TestNoShowSweepForNonWalkinAndWalkinExempt:
    """Design: Corner/state_machines/no_show_sweep_for_non_walkin_and_walkin_exempt"""

    def test_non_walkin_swept_to_no_show(self, api):
        """PRD §3.3: "when the logical clock passes sixty minutes past `slot_start` with no check-in, a non-walk-in appointment moves from `SCHEDULED` to `NO_SHOW`"

        Design: Corner/state_machines/no_show_sweep_for_non_walkin_and_walkin_exempt
        """
        set_clock("2026-09-01T08:00:00Z")
        store = create_store(store_number="S-9", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat NS", date_of_birth="1980-01-01")
        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z")
        set_clock("2026-09-01T11:01:00Z")
        appt_now = get_success_data(api_client.get_appointment(appt["id"], _tech()))
        assert appt_now["status"] == "NO_SHOW"

    def test_walkin_exempt_from_no_show_then_expires_after_day_end(self, api):
        """PRD §3.3: "when the logical clock passes the end of the slot's calendar day, a walk-in appointment never checked in moves from `SCHEDULED` to `EXPIRED`."

        Design: Corner/state_machines/no_show_sweep_for_non_walkin_and_walkin_exempt
        """
        set_clock("2026-09-01T08:00:00Z")
        store = create_store(store_number="S-9", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat WI", date_of_birth="1981-01-01")
        appt = book_appointment(store["id"], patient["id"], product["id"],
                                slot_start="2026-09-01T10:00:00Z", is_walk_in=True)
        set_clock("2026-09-01T11:01:00Z")
        appt_mid = get_success_data(api_client.get_appointment(appt["id"], _tech()))
        assert appt_mid["status"] == "SCHEDULED"

        set_clock("2026-09-02T00:00:01Z")
        appt_final = get_success_data(api_client.get_appointment(appt["id"], _tech()))
        assert appt_final["status"] == "EXPIRED"


class TestStoreSuspensionCascadesCancelToScheduledAppointments:
    """Design: Corner/state_machines/store_suspension_cascades_cancel_to_scheduled_appointments"""

    def test_suspension_cancels_scheduled_but_not_checked_in(self, api):
        """PRD §3.1: "the act of suspending a store cancels every appointment still `SCHEDULED` at that store with reason `STORE_SUSPENDED`"
        PRD §3.1: "A `SUSPENDED` store cannot accept bookings, check-ins, or administrations — attempts against one fail with `ERR_STORE_SUSPENDED`"

        Design: Corner/state_machines/store_suspension_cascades_cancel_to_scheduled_appointments
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-10", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient1 = create_patient(full_name="Pat S1", date_of_birth="1980-01-01")
        patient2 = create_patient(full_name="Pat S2", date_of_birth="1981-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)

        appt1 = book_appointment(store["id"], patient1["id"], product["id"],
                                 slot_start="2026-09-02T10:00:00Z")
        appt2 = book_appointment(store["id"], patient2["id"], product["id"],
                                 slot_start="2026-09-01T10:00:00Z", is_walk_in=True)
        api_client.check_in_appointment(appt2["id"], _tech())

        updated = validate_success(api_client.update_store(store["id"], {"status": "SUSPENDED"}, _mgr()))
        assert updated["status"] == "SUSPENDED"

        appt1_after = get_success_data(api_client.get_appointment(appt1["id"], _tech()))
        assert appt1_after["status"] == "CANCELLED"

        appt2_after = get_success_data(api_client.get_appointment(appt2["id"], _tech()))
        assert appt2_after["status"] == "CHECKED_IN"

        # Repeat check-in fails (store suspended + already checked in)
        resp = api_client.check_in_appointment(appt2["id"], _tech())
        assert resp.status_code == 409


class TestLotReleaseHappyPathClearsQuarantineReasonAndBumpsVersion:
    """Design: Corner/state_machines/lot_release_happy_path_clears_quarantine_reason_and_bumps_version"""

    def test_release_of_released_lot_rejected(self, api):
        """PRD §3.2: "a release attempted on a lot that is not `QUARANTINED` fails with `ERR_LOT_NOT_QUARANTINED`"

        Design: Corner/state_machines/lot_release_happy_path_clears_quarantine_reason_and_bumps_version
        """
        store = create_store(store_number="S-11", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], lot_number="L1", doses_received=5)
        err = validate_error(
            api_client.release_lot(lot["id"], {"excursion_disposition": "RELEASE_OK"}, _mgr()),
            ApiErrorId.ERR_LOT_NOT_QUARANTINED,
        )
        assert err["error_id"] == "ERR_LOT_NOT_QUARANTINED"

    def test_release_without_disposition_rejected(self, api):
        """PRD §3.2: "a release missing a valid disposition fails with `ERR_EXCURSION_DISPOSITION_REQUIRED`."

        Design: Corner/state_machines/lot_release_happy_path_clears_quarantine_reason_and_bumps_version
        """
        store = create_store(store_number="S-11", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], lot_number="L2", doses_received=5)
        api_client.quarantine_lot(lot["id"], _mgr())
        err = validate_error(
            api_client.release_lot(lot["id"], {}, _mgr()),
            ApiErrorId.ERR_EXCURSION_DISPOSITION_REQUIRED,
        )
        assert err["error_id"] == "ERR_EXCURSION_DISPOSITION_REQUIRED"

    def test_release_clears_reason_and_bumps_version(self, api):
        """PRD §3.2: "Either release clears `quarantine_reason` and increments the lot's `version`."

        Design: Corner/state_machines/lot_release_happy_path_clears_quarantine_reason_and_bumps_version
        """
        store = create_store(store_number="S-11", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], lot_number="L2", doses_received=5)
        api_client.quarantine_lot(lot["id"], _mgr())
        released = validate_success(api_client.release_lot(lot["id"],
            {"excursion_disposition": "RELEASE_OK"}, _mgr()))
        assert released["status"] == "RELEASED"
        assert released.get("quarantine_reason") in (None, "", "null")
        assert released["version"] == 3  # create 1, quarantine 2, release 3


class TestSubmissionActionStatePreconditionsAndCorrectedPayloadRequirement:
    """Design: Corner/state_machines/submission_action_state_preconditions_and_corrected_payload_requirement"""

    def test_acknowledge_pending_rejected(self, api):
        """PRD §3.8: "Acknowledgement and rejection both require the submission to be `SUBMITTED` (`ERR_SUBMISSION_NOT_SUBMITTED`)"

        Design: Corner/state_machines/submission_action_state_preconditions_and_corrected_payload_requirement
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-12", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat SUB", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        record = full_administration(store, patient, product, lot)
        sub = get_submission_for_record(record["id"])

        err = validate_error(
            api_client.acknowledge_registry_submission(sub["id"], _co()),
            ApiErrorId.ERR_SUBMISSION_NOT_SUBMITTED,
        )
        assert err["error_id"] == "ERR_SUBMISSION_NOT_SUBMITTED"

    def test_rejected_resubmit_requires_corrected_payload(self, api):
        """PRD §3.8: "resubmission of a `REJECTED` entry requires a `corrected_payload` — omitting it fails with `ERR_CORRECTED_PAYLOAD_REQUIRED`"

        Design: Corner/state_machines/submission_action_state_preconditions_and_corrected_payload_requirement
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-12", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat SUB", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        record = full_administration(store, patient, product, lot)
        sub = get_submission_for_record(record["id"])

        api_client.submit_registry_submission(sub["id"], {}, _co())
        api_client.reject_registry_submission(sub["id"], _co())

        err = validate_error(
            api_client.submit_registry_submission(sub["id"], {}, _co()),
            ApiErrorId.ERR_CORRECTED_PAYLOAD_REQUIRED,
        )
        assert err["error_id"] == "ERR_CORRECTED_PAYLOAD_REQUIRED"

        # Resubmit with corrected payload succeeds
        resub = validate_success(api_client.submit_registry_submission(sub["id"],
            {"corrected_payload": "MSH|CORRECTED"}, _co()))
        assert resub["status"] == "SUBMITTED"

    def test_submit_of_acknowledged_rejected(self, api):
        """PRD §3.8: "Either submission attempt from an ineligible state fails with `ERR_SUBMISSION_NOT_SUBMITTABLE`."
        PRD §3.8: "`ACKNOWLEDGED` is the only terminal state of the reporting lifecycle."

        Design: Corner/state_machines/submission_action_state_preconditions_and_corrected_payload_requirement
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-12", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat SUB", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        record = full_administration(store, patient, product, lot)
        sub = get_submission_for_record(record["id"])

        api_client.submit_registry_submission(sub["id"], {}, _co())
        api_client.acknowledge_registry_submission(sub["id"], _co())

        err = validate_error(
            api_client.submit_registry_submission(sub["id"], {}, _co()),
            ApiErrorId.ERR_SUBMISSION_NOT_SUBMITTABLE,
        )
        assert err["error_id"] == "ERR_SUBMISSION_NOT_SUBMITTABLE"
