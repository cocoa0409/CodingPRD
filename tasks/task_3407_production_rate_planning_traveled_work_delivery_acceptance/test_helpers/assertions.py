"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """PRD §2.5: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["current_rate_per_month"], int) and data["current_rate_per_month"] >= 1
    assert isinstance(data["required_component_codes"], int) and data["required_component_codes"] >= 1
    assert isinstance(data["rework_budget_total_cents"], int) and data["rework_budget_total_cents"] >= 0
    assert isinstance(data["announced_target_rate"], int)
    assert isinstance(data["rework_budget_consumed_cents"], int)
    assert isinstance(data["cancellation_reserve_cents"], int)
    assert isinstance(data["traveled_work_open_hours"], int)
    assert isinstance(data["open_escape_count"], int)
    assert isinstance(data["undelivered_inventory_count"], int)
    assert isinstance(data["storage_fees_accrued_cents"], int)
    assert data["posture"] in ["DISTRESSED", "STABILIZING", "STABLE"]


def assert_rate_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data["proposed_rate"], int) and data["proposed_rate"] >= 1
    assert isinstance(data["effective_month"], str) and len(data["effective_month"]) == 7
    assert isinstance(data["demand_backlog_units"], int) and data["demand_backlog_units"] >= 0
    assert data["status"] in ["DRAFT", "ANNOUNCED", "GATED_REVIEW", "COMMITTED", "SHELVED"]
    # gating_verdict is null until request-gating-review (PRD §3.2)
    assert data.get("gating_verdict") in [None, "PASS", "FAIL"]


def assert_supplier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["supplier_code"], str) and data["supplier_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]


def assert_commitment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("supplier_id", "")), "supplier_id must be a UUID"
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data["component_code"], str) and data["component_code"]
    assert data["committed_rate_per_month"] >= 1
    assert data["lead_time_months"] >= 1
    assert data["unit_price_cents"] >= 1
    assert isinstance(data["ordered_quantity"], int) and data["ordered_quantity"] >= 0
    assert isinstance(data["cancelled_quantity"], int) and data["cancelled_quantity"] >= 0
    assert isinstance(data["active_ordered_quantity"], int)
    assert data.get("assumed_rate_at_order") is None or isinstance(data["assumed_rate_at_order"], int)
    assert isinstance(data["cancellation_penalty_cents"], int)
    assert data["status"] in ["DRAFT", "CONFIRMED", "ORDERED", "AT_RISK", "CANCELLED"]


def assert_workforce_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data["skill_code"], str) and data["skill_code"]
    assert data["required_headcount"] >= 1
    assert isinstance(data["hired_headcount"], int) and data["hired_headcount"] >= 0


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["airline_code"], str) and data["airline_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["credit_standing"] in ["GOOD", "WATCH", "POOR"]


def assert_aircraft(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert isinstance(data["line_number"], int) and data["line_number"] >= 1
    assert isinstance(data["configuration_code"], str) and data["configuration_code"]
    assert isinstance(data["ordered_configuration_code"], str)
    assert data["contract_price_cents"] >= 1
    assert isinstance(data["contracted_delivery_date"], str)
    assert data["production_status"] in ["IN_PRODUCTION", "ASSEMBLY_COMPLETE", "IN_STORAGE", "DELIVERED"]
    assert data["quality_status"] in ["CLEAR", "HOLD"]
    assert data["delivery_status"] in [
        "NOT_STARTED", "FLIGHT_TESTING", "CONFIG_VERIFIED",
        "WALKTHROUGH_PASSED", "REJECTED", "ACCEPTED",
    ]
    assert isinstance(data["rework_cost_total_cents"], int)
    assert data.get("scheduled_delivery_date") is None or isinstance(data["scheduled_delivery_date"], str)


def assert_work_package(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("aircraft_id", "")), "aircraft_id must be a UUID"
    assert isinstance(data["station_sequence"], int) and data["station_sequence"] >= 1
    assert isinstance(data["description"], str)
    assert data["planned_hours"] >= 1
    # traveled_hours is set by the travel action (PRD §3.4); null beforehand
    assert data.get("traveled_hours") is None or data["traveled_hours"] >= 1
    assert data["status"] in ["OPEN", "COMPLETE", "TRAVELED"]


def assert_rework_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("aircraft_id", "")), "aircraft_id must be a UUID"
    assert data.get("work_package_id") is None or is_valid_uuid(data["work_package_id"])
    assert data.get("escape_id") is None or is_valid_uuid(data["escape_id"])
    assert data["source"] in ["TRAVELED_WORK", "QUALITY_ESCAPE", "FLIGHT_TEST_FAILURE", "WALKTHROUGH_SNAG"]
    assert isinstance(data["estimated_cost_cents"], int) and data["estimated_cost_cents"] >= 0
    # actual_cost_cents is null until the order is CLOSED (PRD §3.5)
    assert data.get("actual_cost_cents") is None or isinstance(data["actual_cost_cents"], int)
    assert data["status"] in ["OPEN", "CLOSED", "CREDITED"]


def assert_quality_escape(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("aircraft_id", "")), "aircraft_id must be a UUID"
    assert data["severity"] in ["MAJOR", "CRITICAL"]
    assert isinstance(data["description"], str)
    assert isinstance(data["reported_by_id"], str) and data["reported_by_id"]
    assert isinstance(data["conformance_documented"], bool)
    assert isinstance(data["conformance_refs"], list)
    assert data.get("regulator_notified_at") is None or isinstance(data["regulator_notified_at"], str)
    assert isinstance(data["is_late_notification"], bool)
    assert data.get("dispositioned_by_id") is None or isinstance(data["dispositioned_by_id"], str)
    assert data.get("disposition_code") in [None, "USE_AS_IS", "REWORK", "SCRAP"]
    assert data["status"] in ["OPEN", "ROOT_CAUSE", "DISPOSITIONED", "CLOSED"]


def assert_flight_test(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("aircraft_id", "")), "aircraft_id must be a UUID"
    assert data["range_code"] in ["RANGE_ALPHA", "RANGE_BRAVO"]
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data.get("outcome") in [None, "PASS", "FAIL"]
    assert data["status"] in ["SCHEDULED", "COMPLETED"]


def assert_storage_preservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("aircraft_id", "")), "aircraft_id must be a UUID"
    assert isinstance(data["bay_code"], str) and data["bay_code"]
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data["daily_rate_cents"] >= 1
    assert data["preservation_cycle_days"] >= 1
    assert isinstance(data["last_preserved_at"], str)
    assert isinstance(data["next_preservation_due"], str)
    assert isinstance(data["is_overdue"], bool)
    assert data["status"] in ["ACTIVE", "RELEASED"]


def assert_delivery_negotiation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("aircraft_id", "")), "aircraft_id must be a UUID"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert isinstance(data["proposed_delivery_date"], str)
    assert data["compensation_variant"] in ["CONTRACTUAL_LIQUIDATED", "GOODWILL"]
    assert isinstance(data["days_late"], int) and data["days_late"] >= 0
    assert isinstance(data["compensation_cents"], int) and data["compensation_cents"] >= 0
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["status"] in ["PROPOSED", "COUNTERED", "AGREED", "EXPIRED"]


# --- Domain invariants (PRD §2.9, §3.3, §3.5, §3.9) ---

def assert_program_invariants(data: dict):
    """Ledger and health invariants that hold on every program read."""
    assert 0 <= data["rework_budget_consumed_cents"] <= data["rework_budget_total_cents"], (
        f"consumed {data['rework_budget_consumed_cents']} outside budget "
        f"{data['rework_budget_total_cents']}"
    )
    assert data["cancellation_reserve_cents"] >= 0
    assert data["traveled_work_open_hours"] >= 0
    assert data["open_escape_count"] >= 0
    assert data["undelivered_inventory_count"] >= 0
    assert data["storage_fees_accrued_cents"] >= 0
    assert 0.0 <= data["supply_chain_readiness_pct"] <= 100.0
    assert 0.0 <= data["workforce_readiness_pct"] <= 100.0


def assert_commitment_quantity_invariant(data: dict):
    """PRD §3.3: ordered == active + cancelled at every step."""
    assert data["ordered_quantity"] == data["active_ordered_quantity"] + data["cancelled_quantity"], (
        f"ordered {data['ordered_quantity']} != active {data['active_ordered_quantity']} "
        f"+ cancelled {data['cancelled_quantity']}"
    )
    assert data["active_ordered_quantity"] >= 0
