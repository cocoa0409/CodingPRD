"""Entity assertions and domain invariant checkers for the organized-play program."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Common envelope-level helpers ────────────────────

def assert_common_fields(data: dict, entity_label: str = "resource") -> None:
    """Every top-level resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be int"


# ─── Per-entity assertions ────────────────────────────

def assert_store(data: dict) -> None:
    assert_common_fields(data, "Store")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert data["reporting_tier"] in ["STANDARD", "ENHANCED"]
    assert isinstance(data["daily_event_capacity"], int)
    assert isinstance(data["event_space_capacity"], int)
    assert isinstance(data["tp_balance"], int)
    assert isinstance(data["reporting_violation_points"], int)


def assert_set_release(data: dict) -> None:
    assert_common_fields(data, "SetRelease")
    assert isinstance(data["set_code"], str) and data["set_code"]
    assert data["status"] in ["ANNOUNCED", "PRERELEASE", "RELEASED", "RETIRED"]
    for field in ("prerelease_start_date", "prerelease_end_date", "street_date"):
        assert is_iso8601_timestamp(data[field]), f"{field} must be ISO 8601"


def assert_format(data: dict) -> None:
    assert_common_fields(data, "Format")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["format_code"], str) and data["format_code"]
    assert data["rotation_policy"] in ["FIXED", "ROLLING"]
    assert isinstance(data["current_epoch"], int) and data["current_epoch"] >= 0
    assert isinstance(data["banned_card_refs"], list)
    assert isinstance(data["restricted_card_refs"], list)


def assert_event_application(data: dict) -> None:
    assert_common_fields(data, "EventApplication")
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["set_release_id"])
    assert is_valid_uuid(data["format_id"])
    assert isinstance(data["format_code"], str) and data["format_code"]
    assert data["tier"] in ["LOCAL", "QUALIFIER", "CHAMPIONSHIP"]
    assert data["status"] in [
        "SUBMITTED", "APPROVED", "DENIED", "WITHDRAWN", "COMPLETED", "REPORTED",
    ]
    assert data["prizing_report_status"] in ["NOT_DUE", "DUE", "SUBMITTED"]
    assert data["reporting_due_by"] is None or is_iso8601_timestamp(
        data["reporting_due_by"]
    )
    assert data["prize_allocation_id"] is None or is_valid_uuid(
        data["prize_allocation_id"]
    )


def assert_prize_allocation(data: dict) -> None:
    assert_common_fields(data, "PrizeAllocation")
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["event_application_id"])
    assert data["tier"] in ["LOCAL", "QUALIFIER", "CHAMPIONSHIP"]
    assert data["status"] in ["OPEN", "CLOSED", "RELEASED"]
    for field in ("base_tp", "remaining_tp", "total_drawn_tp", "total_restored_tp"):
        assert isinstance(data[field], int), f"{field} must be int"


def assert_allocation_invariant(data: dict) -> None:
    """ALLOC_INVARIANT = base_tp - total_drawn_tp + total_restored_tp == remaining_tp."""
    expected = data["base_tp"] - data["total_drawn_tp"] + data["total_restored_tp"]
    assert data["remaining_tp"] == expected, (
        f"remaining_tp {data['remaining_tp']} != "
        f"base_tp - total_drawn_tp + total_restored_tp = {expected}"
    )


def assert_prize_distribution(data: dict) -> None:
    assert_common_fields(data, "PrizeDistribution")
    assert is_valid_uuid(data["prize_allocation_id"])
    assert isinstance(data["recipient_ref"], str) and data["recipient_ref"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 0
    assert data["status"] in ["PROPOSED", "PASSED", "VOIDED"]


def assert_prize_report(data: dict) -> None:
    assert_common_fields(data, "PrizeReport")
    assert is_valid_uuid(data["event_application_id"])
    assert is_valid_uuid(data["prize_allocation_id"])
    assert isinstance(data["unclaimed_tp"], int)
    assert isinstance(data["reported_headcount"], int)
    assert data["status"] in ["FILED", "OVERDUE"]


def assert_enforcement_case(data: dict) -> None:
    assert_common_fields(data, "RulesEnforcementCase")
    assert is_valid_uuid(data["event_application_id"])
    assert isinstance(data["player_ref"], str) and data["player_ref"]
    assert isinstance(data["judge_ref"], str) and data["judge_ref"]
    assert data["offense_class"] in ["MINOR", "MAJOR", "SEVERE"]
    assert data["rules_enforcement_level"] in [
        "REGULAR", "COMPETITIVE", "PROFESSIONAL",
    ]
    assert isinstance(data["repeated_offense"], bool)
    assert isinstance(data["penalty_points"], int)
    assert isinstance(data["current_points"], int)
    assert data["status"] in ["FILED", "ESCALATED", "CLOSED", "REDUCED"]


def assert_code_redemption(data: dict) -> None:
    assert_common_fields(data, "CodeRedemption")
    assert data["code_kind"] in ["DIGITAL", "PHYSICAL"]
    assert isinstance(data["redemption_code"], str) and data["redemption_code"]
    assert is_valid_uuid(data["event_application_id"])
    assert data["status"] in ["AVAILABLE", "REDEEMED", "DECLINED"]
    assert data["physical_grant_status"] in [
        "NOT_APPLICABLE", "RESERVED", "DISBURSED",
    ]


def assert_product_configuration(data: dict) -> None:
    assert_common_fields(data, "ProductConfiguration")
    assert is_valid_uuid(data["set_release_id"])
    assert data["configuration_kind"] in [
        "DRAFT_BOOSTER", "COLLECTOR_BOOSTER", "BUNDLE",
    ]
    assert isinstance(data["pack_count"], int)
    assert isinstance(data["print_run_units"], int)
    assert isinstance(data["units_allocated"], int)
    assert isinstance(data["units_available"], int)
    assert data["units_available"] == data["print_run_units"] - data["units_allocated"]


def assert_allocation_order(data: dict) -> None:
    assert_common_fields(data, "AllocationOrder")
    assert isinstance(data["distributor_name"], str) and data["distributor_name"]
    assert is_valid_uuid(data["product_configuration_id"])
    assert isinstance(data["quantity"], int)
    assert isinstance(data["submitted_seq"], int)
    assert data["status"] in [
        "PENDING", "APPROVED", "DENIED", "PARTIALLY_FULFILLED",
    ]
    assert isinstance(data["fulfilled_qty"], int)


def assert_judge_certification(data: dict) -> None:
    assert_common_fields(data, "JudgeCertification")
    assert isinstance(data["judge_ref"], str) and data["judge_ref"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["level"] in ["LEVEL_1", "LEVEL_2", "LEVEL_3"]
    assert data["status"] in ["ACTIVE", "DECERTIFIED"]
    assert isinstance(data["practice_events"], int)
    assert isinstance(data["promotion_eligible"], bool)


def assert_reprint_plan(data: dict) -> None:
    assert_common_fields(data, "ReprintPlan")
    assert isinstance(data["card_name"], str) and data["card_name"]
    assert is_valid_uuid(data["set_release_id"])
    assert is_valid_uuid(data["format_id"])
    assert isinstance(data["secondary_market_index"], int)
    assert isinstance(data["first_print_index"], int)
    assert data["verdict"] in ["REPRINT_ALLOWED", "REPRINT_DENIED"]
    assert data["status"] in ["DRAFT", "APPROVED", "REJECTED", "PUBLISHED"]


def assert_prizing_summary(data: dict) -> None:
    assert data["reporting_due_status"] in ["NOT_SCHEDULED", "OPEN", "PAST_DUE"]
    assert data["report_status"] in ["NOT_FILED", "FILED"]
    assert isinstance(data["qualified_headcount"], bool)
    assert isinstance(data["prize_pool_remaining_tp"], int)
    assert data["headcount_gate_error"] in [None, "ERR_HEADCOUNT_BELOW_THRESHOLD"]