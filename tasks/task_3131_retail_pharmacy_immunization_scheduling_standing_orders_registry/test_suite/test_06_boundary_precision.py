"""Boundary precision tests — observation completion at exact required_minutes, and
registry acknowledgement exactly at due_at.

PRD §3.7 observation window, §3.8 registry lateness.
"""
import pytest
from prd_bench_local_runner.testing import build_user_headers
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_store, create_product, create_protocol, create_patient,
    create_lot, full_administration, get_observation_session_for_record,
    get_submission_for_record,
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


class TestObservationCompletionAtExactRequiredMinutesBoundary:
    """Design: Difficulty/boundary_precision_check/observation_completion_at_exact_required_minutes_boundary"""

    def test_completion_one_second_early_rejected(self, api):
        """PRD §3.7: "requires the logical clock to have reached `started_at` plus `required_minutes` — completion at exactly that instant is allowed, and earlier attempts fail with `ERR_OBSERVATION_TOO_EARLY`"

        Design: Difficulty/boundary_precision_check/observation_completion_at_exact_required_minutes_boundary
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-1100", state_code="CA")
        product = create_product(observation_minutes=15)
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Seven", date_of_birth="1980-01-01", high_risk_flag=True)
        lot = create_lot(store["id"], product["id"], doses_received=5)

        set_clock("2026-09-01T10:00:00Z")
        record = full_administration(store, patient, product, lot,
                                     tech_user_id="user-tech-1", pharm_user_id="user-pharm-1",
                                     imm_user_id="user-imm-1")
        obs = get_observation_session_for_record(record["id"])
        assert obs["required_minutes"] == 30

        # One second early
        set_clock("2026-09-01T10:29:59Z")
        err = validate_error(
            api_client.complete_observation_session(obs["id"], _obs()),
            ApiErrorId.ERR_OBSERVATION_TOO_EARLY,
        )
        assert err["error_id"] == "ERR_OBSERVATION_TOO_EARLY"

    def test_completion_at_exact_boundary_succeeds(self, api):
        """PRD §3.7: "completion at exactly that instant is allowed"

        Design: Difficulty/boundary_precision_check/observation_completion_at_exact_required_minutes_boundary
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-1100", state_code="CA")
        product = create_product(observation_minutes=15)
        create_protocol(vaccine_product_id=product["id"])
        patient = create_patient(full_name="Pat Seven", date_of_birth="1980-01-01", high_risk_flag=True)
        lot = create_lot(store["id"], product["id"], doses_received=5)

        set_clock("2026-09-01T10:00:00Z")
        record = full_administration(store, patient, product, lot,
                                     tech_user_id="user-tech-1", pharm_user_id="user-pharm-1",
                                     imm_user_id="user-imm-1")
        obs = get_observation_session_for_record(record["id"])

        set_clock("2026-09-01T10:30:00Z")
        # Complete as the session's recorded observer (PRD §3.7 requires the
        # caller's X-User-ID to equal observer_id); the ObservationMonitor
        # role header carries the observer's opaque identifier.
        observer_headers = build_user_headers(obs["observer_id"], "ObservationMonitor")
        completed = validate_success(api_client.complete_observation_session(obs["id"], observer_headers))
        assert completed["status"] == "COMPLETED"
        assert completed["ended_at"] == "2026-09-01T10:30:00Z"


class TestRegistryAcknowledgementExactlyAtDueAtIsOnTime:
    """Design: Difficulty/boundary_precision_check/registry_acknowledgement_exactly_at_due_at_is_on_time"""

    def test_acknowledgement_exactly_at_due_at_is_on_time(self, api):
        """PRD §3.8: "acknowledgement stamps `acknowledged_at` and computes `is_late` as true when the acknowledgement time is strictly after `due_at` — an acknowledgement landing exactly at the deadline is on time."

        Design: Difficulty/boundary_precision_check/registry_acknowledgement_exactly_at_due_at_is_on_time
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-1200", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"], registry_format="STATE_API_JSON",
                        registry_deadline_hours=4)
        patient = create_patient(full_name="Pat Eight", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)

        set_clock("2026-09-01T10:00:00Z")
        record = full_administration(store, patient, product, lot,
                                     tech_user_id="user-tech-1", pharm_user_id="user-pharm-1",
                                     imm_user_id="user-imm-1")
        sub = get_submission_for_record(record["id"])
        assert sub["due_at"] == "2026-09-01T14:00:00Z"

        set_clock("2026-09-01T11:00:00Z", as_role="ComplianceOfficer")
        api_client.submit_registry_submission(sub["id"], {}, _co())
        set_clock("2026-09-01T14:00:00Z", as_role="ComplianceOfficer")
        ack = validate_success(api_client.acknowledge_registry_submission(sub["id"], _co()))
        assert ack["acknowledged_at"] == "2026-09-01T14:00:00Z"
        assert ack["status"] == "ACKNOWLEDGED"
        assert ack["is_late"] is False

    def test_acknowledgement_one_second_late_is_late(self, api):
        """PRD §3.8: "`is_late` as true when the acknowledgement time is strictly after `due_at`"

        Design: Difficulty/boundary_precision_check/registry_acknowledgement_exactly_at_due_at_is_on_time
        """
        set_clock("2026-09-01T09:55:00Z")
        store = create_store(store_number="S-1200", state_code="CA")
        product = create_product()
        create_protocol(vaccine_product_id=product["id"], registry_format="STATE_API_JSON",
                        registry_deadline_hours=4)
        patient = create_patient(full_name="Pat Eight", date_of_birth="1980-01-01")
        lot = create_lot(store["id"], product["id"], doses_received=5)

        set_clock("2026-09-01T10:00:00Z")
        record = full_administration(store, patient, product, lot,
                                     tech_user_id="user-tech-1", pharm_user_id="user-pharm-1",
                                     imm_user_id="user-imm-1")
        sub = get_submission_for_record(record["id"])

        set_clock("2026-09-01T11:00:00Z", as_role="ComplianceOfficer")
        api_client.submit_registry_submission(sub["id"], {}, _co())
        set_clock("2026-09-01T14:00:01Z", as_role="ComplianceOfficer")
        ack = validate_success(api_client.acknowledge_registry_submission(sub["id"], _co()))
        assert ack["is_late"] is True
