"""Non-linear state machine tests — RegistrySubmission reject/resubmit cycle with
lateness stickiness, and VaccineLot quarantine/release/retire cycle.

PRD §3.8 registry lifecycle, §3.2 lot lifecycle.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_store, create_product, create_protocol, create_patient,
    create_lot, full_administration, get_submission_for_record,
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


class TestRegistrySubmissionRejectResubmitCycleLateStickiness:
    """Design: Difficulty/non_linear_state_machine/registry_submission_reject_resubmit_cycle_late_stickiness"""

    def test_rejected_submission_sweeps_to_late_unresolved_past_due(self, api):
        """PRD §3.8: "a submission still `PENDING` or `REJECTED` whose `due_at` has passed transitions to `LATE_UNRESOLVED`."

        Design: Difficulty/non_linear_state_machine/registry_submission_reject_resubmit_cycle_late_stickiness
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-500", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"], registry_deadline_hours=4)
        patient = create_patient(full_name="Pat Three", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        set_clock("2026-09-01T10:00:00Z")
        record = full_administration(store, patient, product, lot)
        sub = get_submission_for_record(record["id"])

        # Submit at 10:30
        set_clock("2026-09-01T10:30:00Z", as_role="ComplianceOfficer")
        api_client.submit_registry_submission(sub["id"], {}, _co())
        # Reject at 10:45
        set_clock("2026-09-01T10:45:00Z", as_role="ComplianceOfficer")
        api_client.reject_registry_submission(sub["id"], _co())
        # Advance past due_at (10:00 + 4h = 14:00) to 15:00
        set_clock("2026-09-01T15:00:00Z", as_role="ComplianceOfficer")

        sub_now = get_success_data(api_client.get_registry_submission(sub["id"], _co()))
        assert sub_now["status"] == "LATE_UNRESOLVED"

    def test_resubmit_after_late_unresolved_still_late_on_acknowledge(self, api):
        """PRD §3.8: "Late is not hopeless — a LATE_UNRESOLVED submission may still be submitted and acknowledged — but it is permanent: `is_late`, once true, never flips back to false, and submissions resolved from `LATE_UNRESOLVED` carry the flag forever."

        Design: Difficulty/non_linear_state_machine/registry_submission_reject_resubmit_cycle_late_stickiness
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-500", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"], registry_deadline_hours=4)
        patient = create_patient(full_name="Pat Three", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)
        set_clock("2026-09-01T10:00:00Z")
        record = full_administration(store, patient, product, lot)
        sub = get_submission_for_record(record["id"])
        assert sub["due_at"] == "2026-09-01T14:00:00Z"

        set_clock("2026-09-01T10:30:00Z", as_role="ComplianceOfficer")
        api_client.submit_registry_submission(sub["id"], {}, _co())
        set_clock("2026-09-01T10:45:00Z", as_role="ComplianceOfficer")
        api_client.reject_registry_submission(sub["id"], _co())
        set_clock("2026-09-01T15:00:00Z", as_role="ComplianceOfficer")

        # Resubmit from LATE_UNRESOLVED
        api_client.submit_registry_submission(sub["id"], {"corrected_payload": "MSH|^~\\&|CORRECTED"}, _co())
        ack = validate_success(api_client.acknowledge_registry_submission(sub["id"], _co()))
        assert ack["status"] == "ACKNOWLEDGED"
        assert ack["is_late"] is True


class TestVaccineLotQuarantineReleaseRetireCycle:
    """Design: Difficulty/non_linear_state_machine/vaccine_lot_quarantine_release_retire_cycle_and_terminal_lock"""

    def test_quarantine_release_roundtrip_preserves_inventory(self, api):
        """PRD §3.2: "Either release clears `quarantine_reason` and increments the lot's `version`."
        PRD §3.2: "A StoreManager may also quarantine a lot by hand; manual quarantine requires the lot to be RELEASED (otherwise ERR_LOT_NOT_RELEASED) and records quarantine_reason as MANUAL."

        Design: Difficulty/non_linear_state_machine/vaccine_lot_quarantine_release_retire_cycle_and_terminal_lock
        """
        store = create_store(store_number="S-600", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=8)

        api_client.quarantine_lot(lot["id"], _mgr())
        released = validate_success(api_client.release_lot(lot["id"],
            {"excursion_disposition": "RELEASE_OK"}, _mgr()))
        assert released["status"] == "RELEASED"
        assert released["doses_available"] == 8
        assert released.get("quarantine_reason") in (None, "", "null")

    def test_retire_from_quarantined_then_repeat_retire_rejected(self, api):
        """PRD §3.2: "A StoreManager may retire a lot from either RELEASED or QUARANTINED; retiring an already `RETIRED` lot fails with `ERR_LOT_NOT_RETIRABLE`."
        PRD §3.2: "Retirement permanently writes off the remaining doses — doses_available becomes zero"

        Design: Difficulty/non_linear_state_machine/vaccine_lot_quarantine_release_retire_cycle_and_terminal_lock
        """
        store = create_store(store_number="S-600", state_code="CA")
        product = create_product()
        lot = create_lot(store["id"], product["id"], doses_received=8)

        # First cycle: manual quarantine + release
        api_client.quarantine_lot(lot["id"], _mgr())
        api_client.release_lot(lot["id"], {"excursion_disposition": "RELEASE_OK"}, _mgr())

        # Second cycle: excursion quarantine
        api_client.create_temperature_reading(lot["id"],
            {"recorded_at": "2026-09-01T12:00:00Z", "temperature_c": 9.5}, _mgr())
        lot_now = get_success_data(api_client.get_lot(lot["id"], _mgr()))
        assert lot_now["status"] == "QUARANTINED"

        # Retire from QUARANTINED
        retired = validate_success(api_client.retire_lot(lot["id"], _mgr()))
        assert retired["status"] == "RETIRED"
        assert retired["doses_available"] == 0

        # Repeat retire fails
        err = validate_error(api_client.retire_lot(lot["id"], _mgr()),
                             ApiErrorId.ERR_LOT_NOT_RETIRABLE)
        assert err["error_id"] == "ERR_LOT_NOT_RETIRABLE"
