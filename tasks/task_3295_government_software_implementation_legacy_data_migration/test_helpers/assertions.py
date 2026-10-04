"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data, versioned=True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_agency(data):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert isinstance(data["agency_code"], str) and data["agency_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]


def assert_contract(data):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "POSTED", "Q&A_OPEN", "Q&A_CLOSED", "EVALUATION",
        "AWARD_PENDING", "AWARDED", "IMPLEMENTATION", "CLOSED",
        "PROTESTED", "CANCELLED",
    )
    assert isinstance(data["contract_value_cents"], int)


def assert_phase(data):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "ACTIVE", "COMPLETED", "CANCELLED")
    assert isinstance(data["sequence_no"], int)


def assert_milestone(data):
    _assert_common(data)
    assert data["status"] in (
        "PLANNED", "READY_FOR_REVIEW", "ACCEPTED", "REJECTED", "INVOICED", "PAID",
    )
    assert isinstance(data["billable_amount_cents"], int)
    assert data["billing_variant"] in ("PAYMENT_ON_ACCEPTANCE", "RETAINAGE_HELD")
    assert isinstance(data["rejection_count"], int)


def assert_criterion(data):
    _assert_common(data)
    assert data["result"] in ("PENDING", "SATISFIED", "FAILED", "WAIVED")


def assert_workflow_process(data):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "MAPPED", "IN_REVIEW", "REWORK", "APPROVED", "RETIRED")
    assert isinstance(data["map_revision"], int)


def assert_decision(data):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "RATIFIED", "REJECTED", "SUPERSEDED")


def assert_batch(data):
    _assert_common(data)
    assert data["status"] in (
        "DEFINED", "EXTRACTED", "CLEANSED", "LOADED", "RECONCILED",
        "RECONCILE_FAILED", "ACCEPTED",
    )
    assert data["domain"] in (
        "ACCOUNTS_RECEIVABLE", "PROPERTY_TAX", "COURT_CASES", "LICENSES", "PAYROLL",
    )


def assert_migration_record(data):
    # append-only: id + created_at only, no version / updated_at
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "MigrationRecord must not carry a version field"
    assert "updated_at" not in data, "MigrationRecord must not carry updated_at"
    assert isinstance(data["legacy_primary_key"], str) and data["legacy_primary_key"]


def assert_reconciliation_report(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert "version" not in data, "ReconciliationReport must not carry a version field"
    assert data["run_variant"] in ("FORWARD", "CHRONOLOGICAL")
    assert isinstance(data["count_delta"], int)
    assert isinstance(data["value_delta_cents"], int)
    assert isinstance(data["within_tolerance"], bool)
    assert data["count_delta"] == data["loaded_record_count"] - data["expected_record_count"]
    assert data["value_delta_cents"] == data["loaded_net_value_cents"] - data["expected_net_value_cents"]


def assert_interface(data):
    _assert_common(data)
    assert data["status"] in (
        "PLANNED", "IN_DEVELOPMENT", "IN_TESTING", "CERTIFIED", "SUSPENDED", "RETIRED",
    )


def assert_certification(data):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED", "CANCELLED")
    assert isinstance(data["attempt_no"], int)


def assert_uat_cycle(data):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "BLOCKED", "PASSED", "FAILED")


def assert_uat_session(data):
    _assert_common(data)
    assert data["result"] in ("SCHEDULED", "PASSED", "FAILED", "BLOCKED", "SKIPPED")


def assert_training_session(data):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "DELIVERED", "CANCELLED")
    assert isinstance(data["capacity"], int)


def assert_enrollment(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert "version" not in data, "TrainingEnrollment must not carry a version field"
    assert data["outcome"] in ("ENROLLED", "COMPLETED", "NO_SHOW", "WITHDRAWN")
    assert data["seat_weight"] in (1, 2)


def assert_go_live_event(data):
    _assert_common(data)
    assert data["status"] in (
        "PROPOSED", "READINESS_CHECKED", "APPROVED", "EXECUTED", "ROLLED_BACK", "CANCELLED",
    )
    assert isinstance(data["readiness_score"], int)
    assert 0 <= data["readiness_score"] <= 100


def assert_support_transition(data):
    _assert_common(data)
    assert data["status"] in ("WARRANTY", "STABILIZATION", "STEADY_STATE", "SUNSET")
    assert isinstance(data["open_sev1_count"], int)
    assert isinstance(data["sla_breach_count"], int)


def assert_ticket(data):
    _assert_common(data)
    assert data["severity"] in ("SEV1", "SEV2", "SEV3")
    assert data["resolution"] in (None, "RESOLVED", "WORKAROUND", "DEFERRED", "DUPLICATE")


def assert_maintenance_agreement(data):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "LAPSED", "RENEWED")
    assert isinstance(data["annual_fee_cents"], int)
    assert isinstance(data["renewal_index"], int)
    assert isinstance(data["escalated_fee_cents"], int)


def assert_audit_entry(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert "version" not in data, "AuditLogEntry must not carry a version field"
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_id"], str) and data["actor_id"]
    assert isinstance(data["action"], str) and data["action"]
    assert isinstance(data["entry_hash"], str)
