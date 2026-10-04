"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_STATUSES = {
    "region": ["ACTIVE", "CLOSED"],
    "dealer": ["ACTIVE", "SUSPENDED", "CLOSED"],
    "model_line": ["ACTIVE", "DISCONTINUED"],
    "commodity": ["CONSTRAINED", "RESOLVED"],
    "restriction": ["ACTIVE", "SUPERSEDED", "EXPIRED"],
    "run": ["DRAFT", "PUBLISHED", "LOCKED", "SUPERSEDED"],
    "dealer_allocation": ["OPEN", "LOCKED"],
    "order": [
        "DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED",
        "SCHEDULED", "BUILT", "DELIVERED", "CANCELLED",
    ],
    "build": ["NOT_APPLICABLE", "PENDING_RETROFIT", "RETROFITTED"],
    "trade": ["PROPOSED", "COUNTERED", "ACCEPTED", "DECLINED", "EXPIRED", "CANCELLED", "EXECUTED"],
    "appeal": ["FILED", "UNDER_REVIEW", "GRANTED", "DENIED", "WITHDRAWN"],
    "program": ["ACTIVE", "CLOSED"],
    "carrier": ["ACTIVE", "SUSPENDED"],
    "shipment": ["PLANNED", "PICKED_UP", "DELIVERED", "CANCELLED"],
}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_region(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["status"] in COMMON_STATUSES["region"]


def assert_dealer(data: dict):
    _assert_common(data)
    assert isinstance(data["region_id"], str)
    assert isinstance(data["dealer_code"], str) and data["dealer_code"]
    assert data["status"] in COMMON_STATUSES["dealer"]
    assert "opened_on" in data


def assert_model_line(data: dict):
    _assert_common(data)
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert data["status"] in COMMON_STATUSES["model_line"]


def assert_commodity(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["status"] in COMMON_STATUSES["commodity"]


def assert_commodity_restriction(data: dict):
    _assert_common(data)
    assert isinstance(data["commodity_id"], str)
    assert isinstance(data["model_line_id"], str)
    assert 0 <= data["install_rate_pct"] <= 100
    assert data["status"] in COMMON_STATUSES["restriction"]


def assert_allocation_run(data: dict):
    _assert_common(data)
    assert isinstance(data["period"], str)
    assert isinstance(data["model_line_id"], str)
    assert isinstance(data["base_units"], int) and data["base_units"] >= 0
    assert 0 <= data["retail_priority_pct"] <= 100
    assert data["status"] in COMMON_STATUSES["run"]


def assert_dealer_allocation(data: dict):
    _assert_common(data)
    assert isinstance(data["run_id"], str)
    assert isinstance(data["dealer_id"], str)
    for field in (
        "base_units", "adjustment_units", "final_units",
        "consumed_units", "retail_reserved_units", "retail_consumed_units",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["status"] in COMMON_STATUSES["dealer_allocation"]


def assert_dealer_model_line(data: dict):
    _assert_common(data)
    assert isinstance(data["dealer_id"], str)
    assert isinstance(data["model_line_id"], str)
    assert isinstance(data["reported_sales_units"], int)
    assert "avg_inventory_units" in data
    assert "days_supply" in data
    assert "earned_credit_units" in data


def assert_vehicle_order(data: dict):
    _assert_common(data)
    assert isinstance(data["dealer_id"], str)
    assert isinstance(data["model_line_id"], str)
    assert isinstance(data["run_id"], str)
    assert data["order_kind"] in ["RETAIL", "STOCK"]
    assert data["state"] in COMMON_STATUSES["order"]
    assert data["build_state"] in COMMON_STATUSES["build"]
    assert data["consumed_units"] in (0, 1)


def assert_dealer_trade(data: dict):
    _assert_common(data)
    assert isinstance(data["from_dealer_id"], str)
    assert isinstance(data["to_dealer_id"], str)
    assert data["from_dealer_id"] != data["to_dealer_id"]
    assert isinstance(data["run_id"], str)
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert data["state"] in COMMON_STATUSES["trade"]


def assert_appeal(data: dict):
    _assert_common(data)
    assert isinstance(data["dealer_id"], str)
    assert isinstance(data["run_id"], str)
    assert data["appeal_type"] in ["NEW_POINT", "MARKET_GAP"]
    assert isinstance(data["requested_units"], int) and data["requested_units"] >= 1
    assert data["state"] in COMMON_STATUSES["appeal"]


def assert_incentive_program(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["model_line_id"], str)
    assert data["kind"] in ["AGED_INVENTORY_CREDIT", "VOLUME_BONUS"]
    assert isinstance(data["params"], dict)
    assert data["status"] in COMMON_STATUSES["program"]


def assert_carrier(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["weekly_capacity"], int) and data["weekly_capacity"] >= 1
    assert data["status"] in COMMON_STATUSES["carrier"]


def assert_shipment(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["carrier_id"], str)
    assert isinstance(data["pickup_week"], str)
    assert data["state"] in COMMON_STATUSES["shipment"]


def assert_allocation_pool_invariants(da: dict):
    """Invariants that hold for a DealerAllocation after any operation (§3.5)."""
    assert da["consumed_units"] <= da["final_units"]
    assert da["retail_consumed_units"] <= da["consumed_units"]
    assert da["final_units"] >= da["base_units"] + da["adjustment_units"]
