"""Cross-entity state dependency tests — record void gated by submission state, and
clinic event close gated by event state + clock.

PRD §3.5 void rules, §3.9 event close rules.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_store, create_product, create_protocol, create_patient,
    create_lot, full_administration, get_submission_for_record,
    create_clinic_event_for_lot,
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


class TestImmunizationRecordVoidGatedByRegistrySubmissionState:
    """Design: Difficulty/cross_entity_state_dependency/immunization_record_void_gated_by_registry_submission_state"""

    def test_void_succeeds_while_submission_pending(self, api):
        """PRD §3.5: "A `Pharmacist` may void an administration by supplying a `reason`, but only while the record is `COMPLETED` (otherwise `ERR_RECORD_ALREADY_VOIDED`) and only while its registry submission is still `PENDING` or `REJECTED`"

        Design: Difficulty/cross_entity_state_dependency/immunization_record_void_gated_by_registry_submission_state
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-1300", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Nine A", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=10)
        record = full_administration(store, patient, product, lot)
        voided = validate_success(api_client.void_immunization_record(record["id"],
            {"reason": "dose drawn from wrong lot"}, _pharm()))
        assert voided["status"] == "VOIDED"
        lot_after = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        assert lot_after["doses_available"] == 10

    def test_void_blocked_once_submission_transmitted(self, api):
        """PRD §3.5: "a submission already transmitted or acknowledged cannot be voided back, and the attempt fails with `ERR_SUBMISSION_ALREADY_TRANSMITTED`."

        Design: Difficulty/cross_entity_state_dependency/immunization_record_void_gated_by_registry_submission_state
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-1300", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"])
        patient_a = create_patient(full_name="Pat Nine A", date_of_birth="1980-01-01")
        patient_b = create_patient(full_name="Pat Nine B", date_of_birth="1981-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=10)

        # R1 administered, submission left PENDING
        record1 = full_administration(store, patient_a, product, lot)
        # R2 administered, submission advanced to SUBMITTED
        record2 = full_administration(store, patient_b, product, lot,
                                      slot_start="2026-09-01T10:10:00Z")
        sub2 = get_submission_for_record(record2["id"])
        api_client.submit_registry_submission(sub2["id"], {}, _co())

        # R2 void fails
        err = validate_error(
            api_client.void_immunization_record(record2["id"],
                {"reason": "attempted void after transmission"}, _pharm()),
            ApiErrorId.ERR_SUBMISSION_ALREADY_TRANSMITTED,
        )
        assert err["error_id"] == "ERR_SUBMISSION_ALREADY_TRANSMITTED"
        record2_after = get_success_data(api_client.get_immunization_record(record2["id"], _pharm()))
        assert record2_after["status"] == "COMPLETED"


class TestClinicEventCloseGatedByEventStateAndClock:
    """Design: Difficulty/cross_entity_state_dependency/clinic_event_close_gated_by_event_state_and_clock"""

    def test_close_while_planned_rejected_not_active(self, api):
        """PRD §3.9: "Closing an event is a `StoreManager` act requiring the event to be `ACTIVE` (`ERR_EVENT_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/clinic_event_close_gated_by_event_state_and_clock
        """
        set_clock("2026-09-01T09:00:00Z")
        store = create_store(store_number="S-1400", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=10)
        event = create_clinic_event_for_lot(store["id"], lot["id"], doses_reserved=4)

        err = validate_error(
            api_client.close_clinic_event(event["id"], _mgr()),
            ApiErrorId.ERR_EVENT_NOT_ACTIVE,
        )
        assert err["error_id"] == "ERR_EVENT_NOT_ACTIVE"

    def test_close_before_event_end_rejected_still_running(self, api):
        """PRD §3.9: "and the logical clock to be at or past `event_end` (`ERR_EVENT_STILL_RUNNING`)."

        Design: Difficulty/cross_entity_state_dependency/clinic_event_close_gated_by_event_state_and_clock
        """
        set_clock("2026-09-01T09:00:00Z")
        store = create_store(store_number="S-1400", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=10)
        event = create_clinic_event_for_lot(store["id"], lot["id"], doses_reserved=4)

        # Activate by moving into window
        set_clock("2026-09-01T11:00:00Z")
        err = validate_error(
            api_client.close_clinic_event(event["id"], _mgr()),
            ApiErrorId.ERR_EVENT_STILL_RUNNING,
        )
        assert err["error_id"] == "ERR_EVENT_STILL_RUNNING"

    def test_close_at_exact_event_end_succeeds_and_reconciles(self, api):
        """PRD §3.9: "Close reconciles the mobile inventory: the unadministered remainder — `doses_reserved` minus `doses_administered` — returns to the lot's `doses_available`, and the event lands in `CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/clinic_event_close_gated_by_event_state_and_clock
        """
        set_clock("2026-09-01T09:00:00Z")
        store = create_store(store_number="S-1400", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=10)
        event = create_clinic_event_for_lot(store["id"], lot["id"], doses_reserved=4)

        set_clock("2026-09-01T11:00:00Z")
        lot_mid = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        assert lot_mid["doses_available"] == 6  # 10 - 4 reserved

        set_clock("2026-09-01T12:00:00Z")
        closed = validate_success(api_client.close_clinic_event(event["id"], _mgr()))
        assert closed["status"] == "CLOSED"
        assert closed["doses_administered"] == 0
        lot_final = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        assert lot_final["doses_available"] == 10  # 6 + 4 returned
