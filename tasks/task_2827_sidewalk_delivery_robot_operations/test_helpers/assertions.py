"""Entity assertions and domain invariant checkers."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_instant_format(value: str, field: str = "timestamp"):
    """Datetimes are ISO-8601 UTC with exactly three fractional digits and a
    trailing Z."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert _INSTANT_RE.match(value), (
        f"{field} must be ISO-8601 UTC with three fractional digits and a "
        f"trailing Z, got {value!r}"
    )


def assert_common_fields(data: dict, entity: str = "entity"):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer of at least 1, got {data.get('version')!r}"
    )


def assert_error_envelope_shape(body: dict):
    """The error envelope carries response_type 'error' and a data object whose
    only keys are error_id and message."""
    assert body.get("response_type") == "error", (
        f"Expected response_type 'error', got {body.get('response_type')!r}"
    )
    assert isinstance(body.get("meta"), dict), "error envelope must carry meta"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert set(body.get("data", {}).keys()) == {"error_id", "message"}, (
        f"error data keys must be exactly error_id and message, got "
        f"{sorted(body.get('data', {}).keys())}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------

def assert_service_zone(data: dict):
    assert_common_fields(data, "ServiceZone")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["municipality_code"], str) and data["municipality_code"]
    assert data["permit_state"] in ["PROVISIONED", "PERMITTED", "RESTRICTED", "REVOKED"]
    assert isinstance(data["ordinance_max_speed_cm_s"], int)
    assert isinstance(data["max_concurrent_robots"], int)
    for field in (
        "remedy_budget_cents",
        "remedy_spent_cents",
        "remedy_budget_remaining_cents",
        "reserved_bay_minutes",
        "open_incident_count",
        "on_mission_robot_count",
        "insurer_notify_threshold_cents",
        "lid_code_sequence",
        "planning_crossings",
        "takeover_confidence_threshold_pct",
    ):
        assert isinstance(data[field], int), f"ServiceZone.{field} must be an integer"
    assert data["remedy_budget_remaining_cents"] == (
        data["remedy_budget_cents"] - data["remedy_spent_cents"]
    ), "remedy_budget_remaining_cents must equal budget minus spent"


def assert_sidewalk_segment(data: dict):
    assert_common_fields(data, "SidewalkSegment")
    assert data["segment_type"] in ["WALKWAY", "CROSSING", "RAMP"]
    assert data["crossing_control"] in ["NONE", "SIGNALIZED", "UNSIGNALIZED", "MIDBLOCK"]
    assert data["status"] in ["MAPPED", "SURVEYED", "APPROVED", "BLOCKED", "RETIRED"]
    assert isinstance(data["connected_segment_ids"], list)
    score = data["crossing_risk_score"]
    if score is not None:
        assert 0.0 <= score <= 100.0, f"crossing_risk_score out of range: {score}"


def assert_segment_closure(data: dict):
    assert_common_fields(data, "SegmentClosure")
    assert data["closure_kind"] in ["HARD", "ADVISORY"]
    assert data["cause"] in ["CONSTRUCTION", "WEATHER", "EVENT", "VANDALISM"]
    assert data["state"] in ["SCHEDULED", "ACTIVE", "LIFTED"]
    assert_instant_format(data["starts_at_utc"], "starts_at_utc")
    assert_instant_format(data["ends_at_utc"], "ends_at_utc")
    assert isinstance(data["reroute_triggered_count"], int)


def assert_merchant(data: dict):
    assert_common_fields(data, "Merchant")
    assert data["integration_state"] in ["PENDING", "ACTIVE", "SUSPENDED"]
    assert data["merchant_grade"] in ["STANDARD", "PREFERRED", "ANCHOR"]
    for field in (
        "handoff_sla_seconds",
        "escrowed_fee_cents",
        "recognized_fee_cents",
        "released_fee_cents",
        "settlement_variance_cents",
        "exception_count",
    ):
        assert isinstance(data[field], int), f"Merchant.{field} must be an integer"


def assert_robot(data: dict):
    assert_common_fields(data, "Robot")
    assert data["duty_state"] in [
        "OFFLINE", "STAGING", "AVAILABLE", "ON_MISSION", "CHARGING", "MAINTENANCE", "RETIRED",
    ]
    assert data["health_state"] in ["NOMINAL", "DEGRADED", "IMPAIRED", "QUARANTINED"]
    assert isinstance(data["tamper_flag"], bool)
    assert 0.0 <= data["battery_pct"] <= 100.0
    for field in (
        "max_speed_cm_s",
        "yield_event_count",
        "lifetime_mission_count",
        "lifetime_intervention_count",
        "lifetime_escalation_count",
        "clean_mission_count",
        "rolling_autonomy_index",
        "lifetime_autonomy_index",
    ):
        assert isinstance(data[field], int), f"Robot.{field} must be an integer"
    for field in ("rolling_autonomy_index", "lifetime_autonomy_index"):
        assert 40 <= data[field] <= 100, f"Robot.{field} must be clamped into 40..100"


def assert_depot_bay(data: dict):
    assert_common_fields(data, "DepotBay")
    assert data["bay_type"] in ["CHARGE", "STAGE", "SERVICE"]
    assert data["state"] in ["OPEN", "OUT_OF_SERVICE"]
    assert isinstance(data["committed_minutes"], int)


def assert_bay_reservation(data: dict):
    assert_common_fields(data, "BayReservation")
    assert data["reservation_type"] in ["CHARGE", "SERVICE", "STAGE"]
    assert data["state"] in ["HELD", "ACTIVE", "RELEASED", "CANCELLED"]
    assert isinstance(data["window_minutes"], int)
    assert_instant_format(data["window_start_utc"], "window_start_utc")
    assert_instant_format(data["window_end_utc"], "window_end_utc")


def assert_delivery_order(data: dict):
    assert_common_fields(data, "DeliveryOrder")
    assert data["order_state"] in [
        "RECEIVED", "DISPATCHED", "IN_TRANSIT", "DELIVERED", "EXCEPTION", "CANCELLED", "REFUNDED",
    ]
    assert data["payload_tier"] in ["SMALL", "MEDIUM", "LARGE"]
    assert isinstance(data["urgency_flag"], bool)
    assert isinstance(data["quoted_fee_cents"], int)
    assert isinstance(data["dispatch_attempt_count"], int)
    if data["exception_reason"] is not None:
        assert data["exception_reason"] in [
            "BLOCKED_ROUTE", "WEATHER", "VANDALISM", "ROBOT_FAULT", "LATE",
        ]
    if data["remedy_kind"] is not None:
        assert data["remedy_kind"] in ["REFUND", "REDELIVER", "GOODWILL_CREDIT"]


def assert_delivery_mission(data: dict):
    assert_common_fields(data, "DeliveryMission")
    assert data["mission_state"] in [
        "PLANNED", "LOADED", "EN_ROUTE", "BLOCKED", "HANDOFF_READY", "COMPLETED", "ABORTED",
    ]
    assert isinstance(data["handoff_late"], bool)
    for field in (
        "traversed_crossing_count",
        "blocked_minutes",
        "intervention_count",
        "escalation_count",
        "active_minutes",
    ):
        assert isinstance(data[field], int), f"DeliveryMission.{field} must be an integer"
    if data["abort_reason"] is not None:
        assert data["abort_reason"] in [
            "ROBOT_QUARANTINED", "ZONE_REVOKED", "DISPATCH_CANCELLED", "UNRECOVERABLE_BLOCKAGE",
        ]
    if data["lid_access_code"] is not None:
        assert re.match(r"^\d{6}$", data["lid_access_code"]), (
            f"lid_access_code must be six digits, got {data['lid_access_code']!r}"
        )


def assert_route_plan(data: dict):
    assert_common_fields(data, "RoutePlan")
    assert data["plan_state"] in ["DRAFT", "VALIDATED", "ACTIVE", "SUPERSEDED", "REJECTED"]
    assert isinstance(data["segment_sequence"], list) and data["segment_sequence"]
    assert isinstance(data["crossing_count"], int)
    assert isinstance(data["planned_duration_min"], int)
    assert isinstance(data["revision_index"], int) and data["revision_index"] >= 1
    if data["rejection_reason"] is not None:
        assert data["rejection_reason"] in [
            "OPERATOR_REJECTED", "SEGMENT_BLOCKED", "REPLACED_BY_NEWER",
        ]


def assert_intervention_event(data: dict):
    assert_common_fields(data, "InterventionEvent")
    assert data["takeover_state"] in [
        "REQUESTED", "ACKNOWLEDGED", "ACTIVE", "RELEASED", "ESCALATED",
    ]
    assert data["trigger_reason"] in [
        "LOW_CONFIDENCE", "PEDESTRIAN_CONFLICT", "OBSTACLE", "CROSSING_ASSIST", "VANDALISM_ALERT",
    ]
    assert isinstance(data["mandatory"], bool)
    assert isinstance(data["control_seconds"], int)
    assert 0 <= data["autonomy_confidence_pct"] <= 100


def assert_incident_report(data: dict):
    assert_common_fields(data, "IncidentReport")
    assert data["report_state"] in [
        "DRAFT", "SUBMITTED_MUNICIPAL", "INSURER_NOTIFIED", "CLOSED", "REJECTED",
    ]
    assert data["category"] in [
        "PEDESTRIAN_CONTACT", "RIGHT_OF_WAY_VIOLATION", "VANDALISM", "OBSTRUCTION",
        "CLEARANCE_BREACH",
    ]
    assert data["severity"] in ["MINOR", "SERIOUS", "CRITICAL"]
    assert isinstance(data["insurer_notification_required"], bool)
    assert isinstance(data["estimated_damage_cents"], int)
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]


def assert_zone_economics(data: dict):
    for field in (
        "robot_active_minutes",
        "fleet_capacity_minutes",
        "allocated_overhead_cents",
        "variable_cost_cents",
        "delivered_count",
    ):
        assert isinstance(data[field], int), f"economics.{field} must be an integer"
    assert isinstance(data["utilization_pct"], (int, float))
    assert isinstance(data["throughput_per_robot_hour"], (int, float))


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------

def assert_merchant_fee_buckets_sum(merchant: dict, expected_total_cents: int):
    """The three merchant money buckets always sum to the total quoted across
    every order the merchant ever placed."""
    total = (
        merchant["escrowed_fee_cents"]
        + merchant["recognized_fee_cents"]
        + merchant["released_fee_cents"]
    )
    assert total == expected_total_cents, (
        f"escrowed + recognized + released must equal {expected_total_cents}, got {total} "
        f"({merchant['escrowed_fee_cents']} + {merchant['recognized_fee_cents']} + "
        f"{merchant['released_fee_cents']})"
    )


def assert_bay_minutes_ledgers(bay: dict, zone: dict, expected_minutes: int):
    """The bay-minutes quantity is mirrored on the bay and on its zone."""
    assert bay["committed_minutes"] == expected_minutes, (
        f"bay.committed_minutes expected {expected_minutes}, got {bay['committed_minutes']}"
    )
    assert zone["reserved_bay_minutes"] == expected_minutes, (
        f"zone.reserved_bay_minutes expected {expected_minutes}, got "
        f"{zone['reserved_bay_minutes']}"
    )


def assert_version_unchanged(before: dict, after: dict, label: str = "row"):
    assert before["version"] == after["version"], (
        f"{label}.version must not advance: was {before['version']}, now {after['version']}"
    )


def assert_version_bumped_by(before: dict, after: dict, delta: int = 1, label: str = "row"):
    assert after["version"] == before["version"] + delta, (
        f"{label}.version expected {before['version'] + delta}, got {after['version']}"
    )
