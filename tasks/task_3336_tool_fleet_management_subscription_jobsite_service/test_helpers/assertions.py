"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ACCOUNT_STATUSES = ["ACTIVE", "SUSPENDED"]
AGREEMENT_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED", "ENDING", "CLOSED"]
ASSET_STATUSES = ["REGISTERED", "DEPLOYED", "IN_TRANSIT", "IN_REPAIR", "LOST", "RETIRED"]
LOANER_STATUSES = ["AVAILABLE", "DISPATCHED", "RETURNED", "DECOMMISSIONED"]
TICKET_STATUSES = ["OPENED", "PICKUP_SCHEDULED", "IN_SHOP", "LOANER_DISPATCHED",
                   "QUALITY_CHECK", "CLOSED", "REOPENED"]
CLAIM_STATUSES = ["REPORTED", "POLICE_VERIFIED", "APPROVED", "DENIED", "EXPIRED"]
ORDER_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "FULFILLED", "REJECTED"]
CASE_STATUSES = ["OPEN", "DOCUMENTED", "REJECTED"]
TOOL_CATEGORIES = ["DRILL", "SAW", "BREAKER", "MEASURING", "ANCHORING"]
WEIGHT_CLASSES = ["LIGHT", "HEAVY"]
END_OF_TERM_OPTIONS = ["BUYOUT", "RENEWAL", "RETURN"]


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be int"
    else:
        assert "updated_at" not in data, "append-only entity must omit updated_at"
        assert "version" not in data, "append-only entity must omit version"


def assert_contractor_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["tax_id"], str) and len(data["tax_id"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert data["status"] in ACCOUNT_STATUSES
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0, "balance is floored at 0"


def assert_rate_card(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["tool_category"] in TOOL_CATEGORIES
    assert isinstance(data["base_monthly_rate_cents"], int)
    assert isinstance(data["tier2_threshold"], int)
    assert isinstance(data["tier2_monthly_rate_cents"], int)
    assert isinstance(data["tier3_threshold"], int)
    assert isinstance(data["tier3_monthly_rate_cents"], int)
    assert isinstance(data["min_monthly_fee_cents"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] == "ACTIVE"


def assert_tool_model(data: dict):
    _assert_common(data)
    assert isinstance(data["model_code"], str) and len(data["model_code"]) > 0
    assert data["category"] in TOOL_CATEGORIES
    assert isinstance(data["replacement_value_cents"], int)
    assert data["weight_class"] in WEIGHT_CLASSES


def assert_fleet_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["agreement_number"], str) and len(data["agreement_number"]) > 0
    assert isinstance(data["term_months"], int)
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert data["status"] in AGREEMENT_STATUSES
    assert data["end_of_term_option"] in END_OF_TERM_OPTIONS
    assert isinstance(data["fleet_size_target"], int) and data["fleet_size_target"] >= 0
    assert isinstance(data["billed_this_month_cents"], int)
    assert isinstance(data["theft_claim_count"], int) and data["theft_claim_count"] >= 0


def assert_tool_asset(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["tool_model_id"])
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert isinstance(data["tag_code"], str) and len(data["tag_code"]) > 0
    assert data["status"] in ASSET_STATUSES
    assert isinstance(data["utilization_minutes_current_month"], int)


def assert_jobsite(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["address"], str) and len(data["address"]) > 0
    assert isinstance(data["capacity_assets"], int)
    assert isinstance(data["geofence_radius_m"], int)
    assert isinstance(data["deployed_asset_count"], int)
    assert data["deployed_asset_count"] >= 0
    assert data["deployed_asset_count"] <= data["capacity_assets"]


def assert_usage_event(data: dict):
    _assert_common(data, with_version=False)
    assert is_valid_uuid(data["asset_id"])
    assert is_iso8601_timestamp(data["started_at"])
    assert is_iso8601_timestamp(data["ended_at"])
    assert isinstance(data["minutes"], int) and data["minutes"] > 0


def assert_loaner_unit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tool_model_id"])
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert data["status"] in LOANER_STATUSES


def assert_repair_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["asset_id"])
    assert is_iso8601_timestamp(data["opened_at"])
    assert is_iso8601_timestamp(data["promised_return_by"])
    assert isinstance(data["loaner_requested"], bool)
    assert isinstance(data["sla_breach_credit_cents"], int)
    assert data["sla_breach_credit_cents"] >= 0
    assert data["status"] in TICKET_STATUSES
    assert isinstance(data["reopen_count"], int) and 0 <= data["reopen_count"] <= 2


def assert_theft_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["asset_id"])
    assert is_iso8601_timestamp(data["reported_at"])
    assert data["status"] in CLAIM_STATUSES


def assert_consumable_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["pack_size"], int) and data["pack_size"] >= 1
    assert isinstance(data["requires_application_approval"], bool)


def assert_consumable_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["lines"], list)
    assert data["status"] in ORDER_STATUSES
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0


def assert_support_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert data["kind"] in ["ANCHOR_DESIGN", "FIRESTOP"]
    assert is_valid_uuid(data["jobsite_id"])
    assert is_iso8601_timestamp(data["scheduled_for"])
    assert data["status"] in CASE_STATUSES


def assert_end_of_term_settlement(data: dict):
    _assert_common(data, with_version=False)
    assert is_valid_uuid(data["agreement_id"])
    assert data["option"] in END_OF_TERM_OPTIONS
    assert isinstance(data["provisional_amount_cents"], int)
    assert isinstance(data["finalized"], bool)
