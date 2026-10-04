"""Compensating invariant tests — administer-then-void conserves lot doses, and
clinic event activation/checkout/close conserves mobile lot inventory.

PRD §3.5 void compensation, §3.9 reconciliation invariant.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_store, create_product, create_protocol, create_patient,
    create_lot, full_administration, get_submission_for_record,
    get_observation_session_for_record, create_clinic_event_for_lot,
    walk_appointment_to_consented, administer_appointment,
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


def _obs():
    return TEST_USERS["observer_headers"]


class TestAdministerThenVoidConservesLotDosesAvailable:
    """Design: Difficulty/compensating_invariant/administer_then_void_conserves_lot_doses_available"""

    def test_void_restores_dose_and_removes_submission(self, api):
        """PRD §3.5: "A void compensates on every front at once: the record moves to `VOIDED`; the source lot's `doses_available` increments by one with its `version` bumped; the record's registry submission is removed from the reporting queue outright (the row is deleted while the record keeps its history); the parent observation session, if still `IN_PROGRESS`, transitions to `COMPLETED` with `ended_at` stamped from the logical clock — observation is moot once the dose is voided, and this system transition bypasses the minimum-duration floor that manual completion enforces"

        Design: Difficulty/compensating_invariant/administer_then_void_conserves_lot_doses_available
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-1700", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Eleven", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=7)

        record = full_administration(store, patient, product, lot)
        lot_mid = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        assert lot_mid["doses_available"] == 6
        assert lot_mid["version"] == 2

        voided = validate_success(api_client.void_immunization_record(record["id"],
            {"reason": "patient developed cold feet; dose never actually injected"}, _pharm()))
        assert voided["status"] == "VOIDED"

        lot_after = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        assert lot_after["doses_available"] == 7
        assert lot_after["version"] == 3

        # Submission removed from queue
        subs_resp = api_client.list_record_registry_submissions(record["id"], _co())
        subs = get_success_data(subs_resp)
        assert subs == []

        # Observation auto-completed
        obs = get_observation_session_for_record(record["id"])
        assert obs["status"] == "COMPLETED"

    def test_void_bypasses_observation_minimum_duration_floor(self, api):
        """PRD §3.5: "this system transition bypasses the minimum-duration floor that manual completion enforces"

        Design: Difficulty/compensating_invariant/administer_then_void_conserves_lot_doses_available
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-1700", state_code="CA")
        product = create_product(observation_minutes=15)
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Eleven", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=7)

        set_clock("2026-09-01T10:00:00Z")
        record = full_administration(store, patient, product, lot)
        # Void immediately at 10:00 — before 15-minute observation floor
        validate_success(api_client.void_immunization_record(record["id"],
            {"reason": "test"}, _pharm()))
        obs = get_observation_session_for_record(record["id"])
        assert obs["status"] == "COMPLETED"
        assert obs["ended_at"] == "2026-09-01T10:00:00Z"


# NOTE: difficulty instance
#   clinic_event_activation_checkout_and_close_return_conserve_mobile_lot_inventory
# is SKIPPED. Its `assert` block expects lot_avail_final == 8 for
# (10 available, 6 reserved, 2 administered), but the PRD's operational rules
# uniquely derive 10 − 6 (activation checkout) − 2 (administrations) + 4
# (close return of unadministered remainder) = 6. The instance's expected
# value is not uniquely derivable from the PRD, so per the PRD-first
# two-condition filter the instance is not translated.
