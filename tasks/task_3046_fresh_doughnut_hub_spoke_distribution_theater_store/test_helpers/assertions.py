"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

NETWORK_POSTURES = ["OPEN", "DEGRADED", "SUSPENDED", "CLOSED"]
DOOR_KINDS = ["THEATER", "SPOKE", "GROCERY", "PARTNER"]
DOOR_STATUSES = ["ACTIVE", "SUSPENDED", "CLOSED"]
LINE_STATUSES = ["OPERATIONAL", "DEGRADED", "MAINTENANCE", "DECOMMISSIONED"]
BATCH_STATUSES = ["SCHEDULED", "COMMITTED", "RUNNING", "COMPLETED", "SHORTFALL", "CANCELLED"]
ROUTE_STATUSES = ["PLANNING", "LOCKED", "DISPATCHED", "COMPLETED", "RECONCILED"]
STOP_STATUSES = ["PENDING", "ARRIVED", "DELIVERED", "MISSED", "CREDITED"]
DELIVERY_STATUSES = ["STAGED", "IN_TRANSIT", "DELIVERED", "PARTIAL", "FAILED"]
CREDIT_STATUSES = ["NONE", "PENDING_PULL", "CREDITED", "DISPUTED"]
CREDIT_STATES = ["PROVISIONAL", "FINALIZED", "DISPUTED", "RESOLVED"]
FUNDRAISER_STATUSES = [
    "SUBMITTED", "APPROVED", "SCHEDULED", "READY", "FULFILLED", "CANCELLED", "EXPIRED",
]
WINDOW_STATUSES = ["SCHEDULED", "LIT", "EXTENDED", "COMPLETED", "CANCELLED"]
MIX_PLAN_STATUSES = ["DRAFT", "PUBLISHED", "SUPERSEDED", "LOCKED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_network(data: dict):
    _assert_common(data)
    assert isinstance(data["network_code"], str) and data["network_code"]
    assert isinstance(data["display_name"], str)
    assert data["network_posture"] in NETWORK_POSTURES
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 0
    assert isinstance(data["stale_credit_pool_cents"], int)


def assert_hub(data: dict):
    _assert_common(data)
    assert isinstance(data["hub_code"], str) and data["hub_code"]
    assert isinstance(data["daily_capacity_dozens"], int) and data["daily_capacity_dozens"] > 0
    assert isinstance(data["committed_dozens_today"], int) and data["committed_dozens_today"] >= 0
    assert isinstance(data["territory_region"], str)


def assert_door(data: dict):
    _assert_common(data)
    assert data["door_kind"] in DOOR_KINDS
    assert data["ownership"] in ["COMPANY", "FRANCHISE"]
    assert data["door_status"] in DOOR_STATUSES
    assert isinstance(data["credit_balance_cents"], int) and data["credit_balance_cents"] >= 0
    assert isinstance(data["open_dispute_count"], int) and data["open_dispute_count"] >= 0


def assert_equipment_line(data: dict):
    _assert_common(data)
    assert data["line_kind"] in ["CONTINUOUS_FRYER", "GLAZE_WATERFALL"]
    assert data["line_status"] in LINE_STATUSES
    assert isinstance(data["rated_dozens_per_hour"], int) and data["rated_dozens_per_hour"] > 0
    assert isinstance(data["effective_dozens_per_hour"], int)
    assert isinstance(data["service_interval_hours"], int) and data["service_interval_hours"] > 0


def assert_variety(data: dict):
    _assert_common(data)
    assert data["collection_kind"] in ["CORE", "SEASONAL", "LICENSED"]
    assert data["variety_status"] in ["ACTIVE", "EXPIRED"]
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0


def assert_mix_plan(data: dict):
    _assert_common(data)
    assert data["mix_plan_status"] in MIX_PLAN_STATUSES
    assert isinstance(data["total_planned_dozens"], int) and data["total_planned_dozens"] >= 0
    assert isinstance(data["license_quota_dozens"], int) and data["license_quota_dozens"] >= 0


def assert_mix_plan_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("mix_plan_id", "")), "mix_plan_id must be a UUID"
    assert isinstance(data["planned_dozens"], int) and data["planned_dozens"] >= 0
    assert isinstance(data["allocated_dozens"], int) and data["allocated_dozens"] >= 0


def assert_production_batch(data: dict):
    _assert_common(data)
    assert data["batch_status"] in BATCH_STATUSES
    assert isinstance(data["planned_dozens"], int) and data["planned_dozens"] > 0


def assert_route(data: dict):
    _assert_common(data)
    assert data["route_status"] in ROUTE_STATUSES
    assert isinstance(data["vehicle_capacity_dozens"], int) and data["vehicle_capacity_dozens"] > 0
    assert isinstance(data["loaded_dozens"], int) and data["loaded_dozens"] >= 0


def assert_route_stop(data: dict):
    _assert_common(data)
    assert data["stop_status"] in STOP_STATUSES
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["delivery_status"] in DELIVERY_STATUSES
    assert data["credit_status"] in CREDIT_STATUSES
    assert isinstance(data["dozens_shipped"], int) and data["dozens_shipped"] > 0


def assert_stale_credit(data: dict):
    _assert_common(data)
    assert data["credit_state"] in CREDIT_STATES
    assert isinstance(data["pulled_dozens"], int) and data["pulled_dozens"] > 0
    assert isinstance(data["provisional_credit_cents"], int)


def assert_fundraiser_order(data: dict):
    _assert_common(data)
    assert data["fundraiser_status"] in FUNDRAISER_STATUSES
    assert isinstance(data["requested_dozens"], int) and data["requested_dozens"] > 0


def assert_hot_light_window(data: dict):
    _assert_common(data)
    assert data["window_status"] in WINDOW_STATUSES


def assert_door_invariants(data: dict):
    """Domain invariants that must hold on a door after any operation."""
    assert data["credit_balance_cents"] >= 0
    assert data["open_dispute_count"] >= 0


def assert_network_invariants(data: dict):
    """Domain invariants that must hold on a network after any operation."""
    assert data["stale_credit_pool_cents"] >= 0, "stale credit pool must never go negative"
    assert data["ops_run_index"] >= 0
