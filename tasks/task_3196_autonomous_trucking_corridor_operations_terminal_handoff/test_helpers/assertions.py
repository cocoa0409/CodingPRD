"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


# ─── Common-field assertions ────────────────────────────────────────────────

def assert_common_fields(data: dict):
    """Every mutable entity carries id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a plain UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer starting at 1"


# ─── Per-entity assertions ──────────────────────────────────────────────────

def assert_terminal(data: dict):
    assert_common_fields(data)
    for f in ("terminal_code", "terminal_name", "state_code"):
        assert isinstance(data.get(f), str) and data[f], f"{f} must be a non-empty string"
    assert data["terminal_state"] in ["COMMISSIONING", "OPERATIONAL", "DEGRADED", "CLOSED"]
    for f in ("reserved_apron_units", "transfer_turnaround_minutes"):
        assert isinstance(data.get(f), (int, float)), f"{f} must be numeric"
    assert isinstance(data["approved_window_count"], int)
    assert isinstance(data["total_handoff_minutes"], int)


def assert_corridor(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("corridor_name"), str) and data["corridor_name"]
    assert data["corridor_status"] in [
        "PLANNED", "READINESS_REVIEW", "ACTIVE", "LIMITED", "SUSPENDED", "RETIRED"]
    assert data["posture"] in ["OPEN", "RESTRICTED", "FROZEN"]
    assert data["check_pass_count"] >= 0
    assert data["check_count"] >= 0
    assert data["check_pass_count"] <= data["check_count"]
    assert isinstance(data["has_blocking_incident"], bool)
    assert isinstance(data["readiness_score"], (int, float))
    assert data["readiness_score"] >= 0


def assert_launch_readiness_check(data: dict):
    assert_common_fields(data)
    assert data["check_type"] in ["SENSOR_CALIBRATION", "ROUTE_VALIDATION", "LOAD_SECUREMENT"]
    assert data["check_result"] in ["PASS", "FAIL", "PENDING"]
    assert data["check_status"] in [
        "INITIALIZED", "CALIBRATION_PASSED", "VALIDATED", "EXPIRED_FAILED"]
    assert isinstance(data["calibration_variance_ms"], (int, float))
    assert isinstance(data["is_test_payload"], bool)


def assert_carrier(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("carrier_name"), str) and data["carrier_name"]
    assert isinstance(data.get("dot_number"), str) and data["dot_number"]
    assert data["carrier_status"] in ["ONBOARDING", "ACTIVE", "SUSPENDED", "OFFBOARDED"]
    assert data["safety_tier"] in ["HIGH", "MEDIUM", "LOW"]
    assert data["incident_band"] in ["CLEAN", "WATCH", "SUSPENDED"]
    assert isinstance(data["safety_score"], int)


def assert_shipper_commitment(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("shipper_name"), str) and data["shipper_name"]
    assert data["commitment_status"] in ["DRAFT", "CONFIRMED", "SHIPPED", "REVOKED"]
    assert data["consumed_slots"] >= 0
    assert data["remaining_slots"] >= 0
    assert data["verified_ride_along_count"] >= 0


def assert_run_plan(data: dict):
    assert_common_fields(data)
    assert data["run_status"] in [
        "DRAFT", "READINESS_PENDING", "DISPATCH_READY", "IN_TRANSIT", "COMPLETED", "ABORTED"]
    assert data["trailer_count"] in [1, 2] or data["run_status"] is None
    assert isinstance(data["per_mile_rate_cents"], (int, float))
    assert isinstance(data["committed_rate_cents"], (int, float))
    assert data["safety_band"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def assert_terminal_service_window(data: dict):
    assert_common_fields(data)
    assert data["service_type"] in [
        "HANDOFF_INBOUND", "HANDOFF_OUTBOUND", "YARD_TRANSFER", "MAINTENANCE_STAGING"]
    assert data["window_status"] in [
        "REQUESTED", "APPROVED", "IN_SERVICE", "COMPLETED", "DISPLACED", "CANCELLED"]
    assert data["window_start_minute"] < data["window_end_minute"]
    assert isinstance(data["buffer_seconds"], int)


def assert_remote_support_assignment(data: dict):
    assert_common_fields(data)
    assert data["geofence_type"] in ["GEOFENCE_ONLY", "GEOFENCE_PLUS_BUFFER"]
    assert data["intervention_protocol"] in [
        "MONITOR_ONLY", "VOICE_ADVISORY", "STANDBY_TAKEOVER", "REMOTE_DISENGAGE"]
    assert data["assignment_status"] in ["SCHEDULED", "MONITORING", "RELEASED", "EXPIRED"]
    assert isinstance(data["intervention_count"], int)
    assert isinstance(data["safe_stop_fee_cents"], (int, float))


def assert_incident_report(data: dict):
    assert_common_fields(data)
    assert data["severity"] in ["MINOR", "MODERATE", "CRITICAL"]
    assert data["incident_tier"] in ["TIER_1", "TIER_2", "TIER_3"]
    assert data["report_status"] in [
        "FILED", "INVESTIGATING", "CORRECTIVE_ACTION", "SUBMITTED", "CLOSED"]
    assert isinstance(data["regulatory_notice_required"], bool)
    assert data["report_sequence_number"] >= 1


def assert_driver_prospect(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("prospect_name"), str) and data["prospect_name"]
    assert data["pathway"] in [
        "FIRST_LAST_MILE", "REMOTE_SUPPORT", "FLEET_TECHNICIAN", "TRANSFER_HUB",
        "RIDE_ALONG_EVALUATOR"]
    assert isinstance(data["safety_reliability_score"], (int, float))


def assert_driver_transition(data: dict):
    assert_common_fields(data)
    assert data["transition_status"] in [
        "ENROLLED", "RIDE_ALONG_VERIFIED", "CREDENTIAL_LAPSED", "CANCELLED", "REJECTED"]
    assert data["transition_days_count"] >= 1
    assert isinstance(data["credential_event_count"], int)


def assert_safety_case(data: dict):
    assert_common_fields(data)
    assert data["case_status"] in ["DRAFT", "SUBMITTED", "FILED"]
    assert data["case_status_summary"] in ["NOT_FILED", "CURRENT", "STALE", "SUPERSEDED"]
    assert isinstance(data["residual_risk_score"], (int, float))


def assert_maintenance_program(data: dict):
    assert_common_fields(data)
    assert data["program_status"] in ["DRAFT", "SCHEDULED", "INSPECTED", "VOIDED", "CLOSED"]
    assert data["inspection_programs_status"] in [
        "PENDING", "COMPLIANT", "OVERDUE", "UNFILLED"]


def assert_fleet_unit(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("unit_id"), str) and data["unit_id"]
    assert data["unit_status"] in ["ACTIVE", "MAINTENANCE_HOLD", "RETIRED"]
    assert isinstance(data["is_watch_squad"], bool)
    assert data["remain_hours"] >= 0


def assert_state_authority(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("state_code"), str) and data["state_code"]
    assert data["hours_used"] >= 0
    assert data["remaining_autonomous_hours"] >= 0
    assert isinstance(data["filing_required_next"], bool)


def assert_regulatory_engagement(data: dict):
    assert_common_fields(data)
    assert data["engagement_type"] in [
        "SAFETY_BRIEFING", "OPERATIONAL_NOTICE", "INCIDENT_DISCLOSURE",
        "HOURS_ALLOCATION_REQUEST"]
    assert data["engagement_status"] in ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"]
    assert data["state_status"] in ["FORMAL", "INFORMAL", "EXEMPT"]


def assert_ledger_checkpoint(data: dict):
    assert_common_fields(data)
    assert data["checkpoint_status"] in ["OPEN", "ADOPTED", "ROLLED_OVER"]
    assert isinstance(data["hours_per_epoch"], int)


def assert_security_record(data: dict):
    assert_common_fields(data)
    assert data["record_status"] in ["PENDING", "ACTIVE", "REPORTING", "CLOSED"]
    assert data["convention_status"] in ["NORMAL", "SENSITIVE", "HIGH_CONSEQUENCE"]


def assert_run_plan_hauler(data: dict):
    assert_common_fields(data)
    assert data["hauler_role"] in ["FIRST_MILE_DRIVER", "LAST_MILE_DRIVER", "YARD_SHUTTLE"]
    assert data["hauler_status"] in [
        "TRUCK_HOLDER_BLENDED", "HAULER_ON_SITE", "RECEIVED_ON_SITE", "OFF_TARIFF"]


def assert_clause_variant(data: dict):
    assert_common_fields(data)
    assert data["variant_status"] in ["PENDING", "ELECTED", "DECLINED"]
    assert data["variant_status_summary"] in ["NOT_ELECTED", "ELECTED", "DECLINED_PENDING"]


def assert_agreement_code(data: dict):
    assert_common_fields(data)
    assert data["code_status"] in ["ACTIVE", "EXECUTED"]
    assert isinstance(data["exec_sequence"], int)


# ─── Domain invariant checkers ──────────────────────────────────────────────

def assert_commitment_invariants(data: dict):
    """Slot conservation holds after any operation on a commitment."""
    assert data["consumed_slots"] >= 0
    assert data["remaining_slots"] == data["committed_slots"] - data["consumed_slots"], \
        "remaining_slots must equal committed_slots - consumed_slots"
    assert_cost_precision(data.get("ride_along_credit_cents", 0))
    assert_cost_precision(data.get("billed_ride_along_cents", 0))


def assert_corridor_invariants(data: dict):
    """Derived corridor readings stay internally consistent."""
    assert data["check_pass_count"] <= data["check_count"]
    assert data["readiness_score"] >= 0
    if data["corridor_status"] == "RETIRED":
        assert data["posture"] == "FROZEN", "a retired corridor's posture is terminal FROZEN"


def assert_terminal_invariants(data: dict):
    assert data["reserved_apron_units"] >= 0
    assert data["approved_window_count"] >= 0
    assert data["total_handoff_minutes"] >= 0
    if data["approved_window_count"] == 0:
        assert data["transfer_turnaround_minutes"] == 0, \
            "the empty approved set collapses the turnaround reading to 0"