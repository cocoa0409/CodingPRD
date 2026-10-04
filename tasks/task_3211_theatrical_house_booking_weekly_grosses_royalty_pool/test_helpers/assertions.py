"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_production_company(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0


def assert_theatre(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert data["size_class"] in ["SMALL", "MEDIUM", "LARGE"]
    assert isinstance(data["is_landmark"], bool)
    assert isinstance(data["base_weekly_rent_cents"], int) \
        and data["base_weekly_rent_cents"] >= 0


def assert_production(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["company_id"])
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["required_size_class"] in ["SMALL", "MEDIUM", "LARGE"]
    assert isinstance(data["required_loadin_hours"], int) \
        and data["required_loadin_hours"] > 0
    assert isinstance(data["required_loadout_hours"], int) \
        and data["required_loadout_hours"] > 0


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["theatre_id"])
    assert is_iso8601_timestamp(data["loadin_start"])
    assert is_iso8601_timestamp(data["run_end"])
    assert data["status"] in ["REQUESTED", "APPROVED", "DECLINED", "WITHDRAWN",
                              "ACTIVE", "CLOSED", "EVICTED", "MAINTENANCE_HOLD",
                              "DONE"]


def assert_license_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["weekly_rent_cents"], int) \
        and data["weekly_rent_cents"] >= 0
    assert isinstance(data["stop_clause_weekly_floor_cents"], int) \
        and data["stop_clause_weekly_floor_cents"] >= 0
    assert isinstance(data["stop_clause_consecutive_weeks"], int) \
        and data["stop_clause_consecutive_weeks"] >= 1
    assert data["status"] in ["DRAFT", "SIGNED", "SUPERSEDED", "VOIDED"]


def assert_royalty_participant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["production_id"])
    assert isinstance(data["participant_name"], str) \
        and len(data["participant_name"]) > 0
    assert isinstance(data["royalty_points"], int) and data["royalty_points"] >= 1
    assert isinstance(data["pool_eligible"], bool)
    assert isinstance(data["fixed_royalty_cents"], int) \
        and data["fixed_royalty_cents"] >= 0


def assert_discount_code(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["production_id"])
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert 0 < data["percent_off"] < 100
    assert isinstance(data["active"], bool)


def assert_ticket_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_iso8601_timestamp(data["performance_date"])
    assert isinstance(data["ticket_count"], int) and data["ticket_count"] >= 1
    assert isinstance(data["is_group_sale"], bool)
    assert isinstance(data["face_value_cents"], int) and data["face_value_cents"] > 0
    assert 0.5 <= data["dynamic_pricing_factor"] <= 2.0
    assert data["status"] in ["SOLD", "REFUNDED"]
    assert isinstance(data["computed_gross_cents"], int) \
        and data["computed_gross_cents"] >= 0
    assert isinstance(data["refunded"], bool)


def assert_weekly_gross_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_iso8601_timestamp(data["week_start"])
    assert is_iso8601_timestamp(data["week_end"])
    assert data["status"] in ["DRAFT", "SUBMITTED", "VERIFIED", "REJECTED"]
    assert isinstance(data["gross_cents"], int) and data["gross_cents"] >= 0


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["report_id"])
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["house_expenses_cents"], int) \
        and data["house_expenses_cents"] >= 0
    assert isinstance(data["crew_cost_cents"], int) and data["crew_cost_cents"] >= 0
    assert isinstance(data["theatre_share_cents"], int) \
        and data["theatre_share_cents"] >= 0
    assert isinstance(data["weekly_operating_profit_cents"], int)
    assert isinstance(data["royalty_pool_cents"], int) \
        and data["royalty_pool_cents"] >= 0
    assert data["status"] in ["DRAFT", "FINALIZED"]


def assert_stop_notice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["consecutive_under_floor_weeks"], int) \
        and data["consecutive_under_floor_weeks"] >= 0
    assert data["status"] in ["OPEN", "DISCHARGED", "EXECUTED"]


def assert_capital_project(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["theatre_id"])
    assert isinstance(data["description"], str) and len(data["description"]) > 0
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_crew_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1
    assert is_iso8601_timestamp(data["engaged_at"])


def assert_settlement_invariants(data: dict):
    """Fiscal invariants that must hold for any settlement."""
    assert data["royalty_pool_cents"] <= max(0, data["weekly_operating_profit_cents"]), \
        "royalty pool can never exceed weekly operating profit"
    assert data["theatre_share_cents"] >= 0
    assert data["crew_cost_cents"] >= 0
