"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_ehr_implementation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert isinstance(data["vendor_release"], str) and data["vendor_release"]
    assert data["status"] in [
        "PLANNING", "BUILD_IN_PROGRESS", "VALIDATION_IN_PROGRESS", "CUTOVER_READY",
        "GO_LIVE_ACTIVE", "COMMAND_CENTER_ACTIVE", "STABILIZED",
        "POST_LIVE_OPTIMIZATION", "ARCHIVED",
    ]
    assert data["readiness_posture"] in ["OPEN", "RESTRICTED", "ROLLBACK_REQUIRED"]
    assert isinstance(data["current_epoch_index"], int) and data["current_epoch_index"] >= 0
    assert 0.00 <= data["readiness_score"] <= 100.00


def assert_facility(data: dict):
    _assert_common_fields(data)
    assert data["facility_type"] in ["ACUTE_CARE", "CRITICAL_ACCESS", "AMBULATORY", "SPECIALTY"]
    assert data["conversion_scope"] in ["FULL_RECORD", "DEMOGRAPHICS_ONLY", "SCHEDULING_ONLY"]
    assert data["status"] in [
        "SITE_REGISTERED", "BUILD_CONFIGURED", "REMEDIATION_REQUIRED", "VALIDATED",
        "CUTOVER_READY", "LIVE", "STABILIZED", "STABILIZATION_AT_RISK",
    ]
    assert isinstance(data["is_live"], bool)
    assert isinstance(data["bed_count"], int)
    assert isinstance(data["converted_patient_count"], int)


def assert_department(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "BUILD_PENDING", "BUILD_COMPLETE", "TRAINING_IN_PROGRESS",
        "READY_FOR_GO_LIVE", "REMEDIATION_REQUIRED", "LIVE",
    ]
    assert isinstance(data["proficiency_gate_open"], bool)
    assert isinstance(data["proficiency_cleared_count"], int)
    assert isinstance(data["build_blocking_defect_count"], int)
    assert isinstance(data["required_staff_count"], int)


def assert_system_build_item(data: dict):
    _assert_common_fields(data)
    assert data["build_classification"] in [
        "FOUNDATION_ADOPTED", "FOUNDATION_ADAPTED", "LOCAL_CUSTOM",
    ]
    assert data["status"] in [
        "DRAFT", "IN_BUILD", "BUILD_COMPLETE", "IN_TESTING",
        "VALIDATION_COMPLETE", "BUILD_REJECTED",
    ]
    assert isinstance(data["customization_depth"], int) and data["customization_depth"] >= 0
    assert isinstance(data["test_cycles_passed"], int)
    assert isinstance(data["open_defect_count"], int)
    assert isinstance(data["rejection_count"], int)


def assert_staff(data: dict):
    _assert_common_fields(data)
    assert data["staff_type"] in [
        "PROVIDER", "NURSE", "ALLIED_HEALTH", "REGISTRATION", "BILLING", "ANALYST",
    ]
    assert data["status"] in [
        "REGISTERED", "TRAINING_ASSIGNED", "TRAINED", "PROFICIENCY_VERIFIED",
        "CREDENTIALED", "PROFICIENCY_FAILED",
    ]
    assert isinstance(data["accumulated_training_hours"], (int, float))


def assert_training_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ASSIGNED", "IN_PROGRESS", "COMPLETED", "OVERDUE", "WAIVED"]
    assert isinstance(data["completed_hours"], (int, float))
    assert isinstance(data["required_hours"], (int, float))


def assert_credentialed_trainer(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PENDING_OBSERVATION", "CERTIFIED", "EXPIRED", "REVOKED"]
    assert data["certification_level"] in ["STANDARD", "ADVANCED"]
    assert isinstance(data["observation_hours"], (int, float))


def assert_proficiency_exam(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED_PASS", "COMPLETED_FAIL", "NO_SHOW"]
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1


def assert_test_scenario(data: dict):
    _assert_common_fields(data)
    assert data["scenario_class"] in ["UNIT", "INTEGRATED", "CHARGE_CAPTURE_TO_CLAIM"]
    assert data["status"] in ["DEFINED", "PASSED", "FAILED"]
    assert isinstance(data["open_defect_count"], int)


def assert_test_defect(data: dict):
    _assert_common_fields(data)
    assert data["severity"] in ["SEV1", "SEV2", "SEV3", "SEV4"]
    assert data["status"] in ["OPEN", "IN_REMEDIATION", "RESOLVED", "DEFERRED", "REOPENED"]
    assert isinstance(data["blocks_go_live"], bool)
    assert isinstance(data["attempt_count"], int)


def assert_conversion_batch(data: dict):
    _assert_common_fields(data)
    assert data["payload_class"] in [
        "PATIENT_DEMOGRAPHICS", "APPOINTMENTS", "ORDERS", "BALANCES",
    ]
    assert data["status"] in ["STAGED", "VALIDATING", "LOADED", "RECONCILED", "FAILED", "ROLLED_BACK"]
    assert isinstance(data["source_count"], int)
    assert isinstance(data["reconciled_count"], int)


def assert_patient_order(data: dict):
    _assert_common_fields(data)
    assert data["order_type"] in ["MEDICATION", "LAB", "IMAGING", "PROCEDURE"]
    assert data["clinical_state"] in ["CONVERTED", "RECONCILED", "PAPER_BACKFILL_REQUIRED"]
    assert data["billing_state"] in [
        "UNPOSTED", "CHARGE_POSTED", "CLAIM_SUBMITTED", "CLAIM_ACCEPTED",
        "CLAIM_DENIED", "CLAIM_PAID",
    ]
    assert isinstance(data["paper_backfill_count"], int)
    assert isinstance(data["balance_cents"], int)


def assert_interface_channel(data: dict):
    _assert_common_fields(data)
    assert data["channel_type"] in ["LAB", "IMAGING", "PHARMACY", "DEVICE"]
    assert data["message_format"] in ["HL7_V2", "FHIR", "DICOM", "CSV"]
    assert data["status"] in [
        "DEFINED", "BUILDING", "IN_MESSAGE_VALIDATION", "VALIDATED", "VALIDATION_FAILED",
    ]
    assert isinstance(data["validated_message_count"], int)
    assert isinstance(data["rejected_message_count"], int)


def assert_interface_message(data: dict):
    """InterfaceMessage is append-only: it carries id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["validation_status"] in ["RECEIVED", "VALIDATED", "REJECTED"]
    assert data["direction"] in ["INBOUND", "OUTBOUND"]
    assert is_iso8601_timestamp(data.get("received_utc", "")), "received_utc must be ISO 8601"


def assert_cutover_task(data: dict):
    _assert_common_fields(data)
    assert data["task_class"] in [
        "DOWNTIME_PREP", "ORDER_RECONCILIATION", "PAPER_BACKFILL",
        "DRESS_REHEARSAL", "GO_NO_GO_DECISION",
    ]
    assert data["status"] in ["PLANNED", "IN_PROGRESS", "COMPLETE", "SKIPPED", "BLOCKED"]
    assert isinstance(data["sequence_index"], int)
    assert isinstance(data["duration_minutes"], (int, float))


def assert_command_center_ticket(data: dict):
    _assert_common_fields(data)
    assert data["severity"] in ["SEV1", "SEV2", "SEV3", "SEV4"]
    assert data["triage_state"] in ["REPORTED", "TRIAGED", "IN_RESOLUTION", "RESOLVED", "ESCALATED"]
    assert isinstance(data["resolution_sla_minutes"], int)
    assert is_iso8601_timestamp(data.get("reported_utc", "")), "reported_utc must be ISO 8601"


def assert_staffing_shift(data: dict):
    _assert_common_fields(data)
    assert data["support_role"] in [
        "AT_THE_ELBOW", "TRIAGE_COMMANDER", "APPLICATION_ANALYST", "CHARGE_CAPTURE_SPECIALIST",
    ]
    assert data["status"] in ["SCHEDULED", "ACTIVE", "COMPLETED", "NO_SHOW", "REASSIGNED"]
    assert isinstance(data["handoff_buffer_minutes"], int)


def assert_optimization_backlog_item(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["NEW", "TRIAGED", "SCHEDULED", "IN_PROGRESS", "RELEASED", "REJECTED"]
    assert isinstance(data["effort_points"], int)
    assert isinstance(data["requested_epoch"], int)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_readiness_invariants(data: dict):
    """Invariants that hold after any child mutation of a program."""
    assert 0.00 <= data["readiness_score"] <= 100.00
    assert_cost_precision(data["readiness_score"])
    assert 0.00 <= data["optimistic_readiness_score"] <= 100.00
    score = data["readiness_score"]
    posture = data["readiness_posture"]
    if score >= 60.00:
        assert posture == "OPEN"
    elif score >= 40.00:
        assert posture == "RESTRICTED"
    else:
        assert posture == "ROLLBACK_REQUIRED"


def assert_department_proficiency_invariants(data: dict):
    """Gate/ratio consistency after any proficiency-affecting mutation."""
    ratio = data["proficiency_cleared_ratio"]
    assert 0.00 <= ratio <= 100.00
    assert data["proficiency_gate_open"] is (ratio >= 80.00)


def assert_interface_channel_rate_invariants(data: dict):
    """The published pass rate must match the counters it is derived from."""
    decided = data["validated_message_count"] + data["rejected_message_count"]
    if decided == 0:
        assert data["interface_message_validation_pass_rate"] == 0.00
    else:
        expected = round(100.00 * data["validated_message_count"] / decided, 2)
        assert abs(data["interface_message_validation_pass_rate"] - expected) < 0.005