"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MENU_TIERS = ["FULL", "TIER1_NO_POWER", "TIER2_NO_WATER", "TIER3_NO_GAS"]
AXES = ["power", "water", "gas", "payment_network"]


def assert_storm_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in [
        "WATCH", "WARNING", "ACTIVE", "RECOVERY", "CLOSED", "CANCELLED"
    ]
    assert is_iso8601_timestamp(data.get("watch_started_at", ""))
    assert isinstance(data["warning_count"], int) and data["warning_count"] >= 0
    assert data.get("activated_at") is None or is_iso8601_timestamp(data["activated_at"])
    assert data.get("closed_at") is None or is_iso8601_timestamp(data["closed_at"])
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_unit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("storm_event_id", "")), "storm_event_id must be UUID"
    assert isinstance(data["unit_code"], str) and len(data["unit_code"]) > 0
    assert data["menu_tier"] in MENU_TIERS
    rs = data["resource_status"]
    for axis in AXES:
        assert rs[axis] in ["UP", "DOWN"], f"resource_status.{axis} must be UP or DOWN"
    assert isinstance(data["cash_only_flag"], bool)
    assert data.get("last_shift_change_at") is None or is_iso8601_timestamp(
        data["last_shift_change_at"]
    )
    assert isinstance(data["hours_since_shift_change"], int)
    assert isinstance(data["lodging_fund_cents"], int)
    assert data["lodging_fund_cents"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_condition_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("unit_id", "")), "unit_id must be UUID"
    for axis in AXES:
        assert data[axis] in ["UP", "DOWN"], f"{axis} must be UP or DOWN"
    assert is_iso8601_timestamp(data.get("reported_at", ""))


def assert_menu_activation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("unit_id", "")), "unit_id must be UUID"
    assert data["tier"] in ["TIER1_NO_POWER", "TIER2_NO_WATER", "TIER3_NO_GAS"]
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "ENDED"]
    assert is_iso8601_timestamp(data.get("activated_at", ""))
    assert data.get("ended_at") is None or is_iso8601_timestamp(data["ended_at"])


def assert_checklist_run(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("unit_id", "")), "unit_id must be UUID"
    assert data["status"] in ["IN_PROGRESS", "SUBMITTED", "APPROVED", "REJECTED"]


def assert_checklist_item(data: dict):
    """Append-only item: carries id and created_at but no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("checklist_run_id", "")), "checklist_run_id UUID"
    assert data["key"] in [
        "POWER_RESTORED", "WATER_POTABLE", "GAS_LEAK_CHECK",
        "FOOD_DISCARD_LOGGED", "CASH_DRAWER_COUNTED",
    ]
    assert data["result"] in ["PASS", "FAIL"]
    assert "version" not in data, "ChecklistItem must not carry version"
    assert "updated_at" not in data, "ChecklistItem must not carry updated_at"


def assert_cash_drop(data: dict):
    """Append-only drop: carries id and created_at but no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("unit_id", "")), "unit_id must be UUID"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert is_iso8601_timestamp(data.get("recorded_at", ""))
    assert "version" not in data, "CashDrop must not carry version"
    assert "updated_at" not in data, "CashDrop must not carry updated_at"


def assert_crew_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["role"] in ["GRILL_OP", "SERVER", "SHIFT_LEAD"]
    assert is_valid_uuid(data.get("home_unit_id", "")), "home_unit_id must be UUID"
    assert isinstance(data["is_jump_team"], bool)
    assert data["status"] in ["AVAILABLE", "ASSIGNED", "INACTIVE"]


def assert_crew_assignment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("crew_member_id", "")), "crew_member_id UUID"
    assert is_valid_uuid(data.get("unit_id", "")), "unit_id must be UUID"
    assert is_iso8601_timestamp(data.get("assigned_from", ""))
    assert is_iso8601_timestamp(data.get("assigned_until", ""))
    assert data["status"] in ["SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED"]


def assert_asset(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["kind"] in ["GENERATOR", "MOBILE_KITCHEN"]
    assert is_valid_uuid(data.get("home_unit_id", "")), "home_unit_id must be UUID"
    assert data["status"] in ["IDLE", "ALLOCATED", "RETURNED", "RETIRED"]
    assert data.get("retired_at") is None or is_iso8601_timestamp(data["retired_at"])


def assert_asset_allocation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("asset_id", "")), "asset_id must be UUID"
    assert is_valid_uuid(data.get("unit_id", "")), "unit_id must be UUID"
    assert data["status"] in ["RESERVED", "DEPLOYED", "RETURNED", "CANCELLED"]
    assert data.get("dispatched_at") is None or is_iso8601_timestamp(
        data["dispatched_at"]
    )
    assert data.get("returned_at") is None or is_iso8601_timestamp(data["returned_at"])


def assert_lodging_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("unit_id", "")), "unit_id must be UUID"
    assert is_valid_uuid(data.get("crew_assignment_id", "")), "crew_assignment_id UUID"
    assert isinstance(data["rooms"], int) and data["rooms"] >= 1
    assert isinstance(data["nightly_rate_cents"], int)
    assert data["nightly_rate_cents"] >= 1
    assert is_iso8601_timestamp(data.get("check_in", ""))
    assert is_iso8601_timestamp(data.get("check_out", ""))
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 1
    assert data["status"] in ["CONFIRMED", "CANCELLED"]


def assert_relief_org(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_relief_pledge(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("unit_id", "")), "unit_id must be UUID"
    assert is_valid_uuid(data.get("relief_org_id", "")), "relief_org_id must be UUID"
    assert isinstance(data["meal_count"], int) and data["meal_count"] >= 1
    assert isinstance(data["service_date"], str)
    assert data["status"] in ["PLEDGED", "CONFIRMED", "CANCELLED"]


def assert_confirmed_pledge_invariants(data: dict):
    """Domain invariants that hold after a pledge confirmation (PRD §3.8)."""
    assert data["shortfall_meals"] == max(0, data["meal_count"] - data["served_count"])
    assert data["overage_meals"] == max(0, data["served_count"] - data["meal_count"])
    assert data["shortfall_penalty_cents"] == data["shortfall_meals"] * 100
    assert isinstance(data["reimbursement_cents"], int)
