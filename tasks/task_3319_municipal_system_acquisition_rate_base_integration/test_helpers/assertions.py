"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

TARGET_STATUSES = ["SCREENING", "VALUATION", "MUNICIPAL_REVIEW", "REGULATORY_REVIEW",
                   "CLOSING", "INTEGRATED", "REJECTED"]
ASSESSMENT_STATUSES = ["DRAFT", "SUBMITTED", "ACCEPTED", "SUPERSEDED"]
CAPITAL_ITEM_STATUSES = ["PLANNED", "SCHEDULED", "EXECUTED", "SPLIT", "CANCELLED"]
CASE_STATUSES = ["OPEN", "FINALIZED", "SUPERSEDED"]
ENTRY_STATUSES = ["SUBMITTED", "SELECTED", "NOT_SELECTED"]
EVENT_KINDS = ["PUBLIC_HEARING", "COUNCIL_VOTE", "REFERENDUM"]
EVENT_STATUSES = ["SCHEDULED", "HELD", "PASSED", "FAILED"]
APPLICATION_STATUSES = ["PREPARED", "FILED", "APPROVED", "DENIED", "REMANDED"]
ACCOUNT_STATUSES = ["LEGACY", "MIGRATED", "CONSOLIDATED", "ORPHANED"]
TRANSITION_CATEGORIES = ["BILLING_RECORDS", "DEPOSITS", "SERVICE_AGREEMENTS", "METER_READS"]
TRANSITION_STATUSES = ["PENDING", "DONE", "BLOCKED"]
EMPLOYEE_STATUSES = ["PENDING", "ACCEPTED", "DECLINED", "ASSUMED", "WITHDRAWN"]
TARIFF_STATUSES = ["DRAFT", "ADOPTED"]
VALUATION_METHODS = ["FMV_INDEPENDENT", "REPLACEMENT_COST", "ORIGINAL_COST_LESS_DEPRECIATION"]


def _assert_common(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_target(data: dict):
    _assert_common(data)
    assert isinstance(data["system_name"], str) and data["system_name"]
    assert isinstance(data["municipality_name"], str) and data["municipality_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["system_type"] in ["WATER", "WASTEWATER", "COMBINED"]
    assert isinstance(data["customer_count"], int) and data["customer_count"] > 0
    assert isinstance(data["permitted_valuation_methods"], list)
    assert len(data["permitted_valuation_methods"]) >= 1
    for m in data["permitted_valuation_methods"]:
        assert m in VALUATION_METHODS
    assert data["status"] in TARGET_STATUSES
    assert isinstance(data["council_approved"], bool)
    assert isinstance(data["filing_estimate_cents"], int)


def assert_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("target_id", ""))
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in ASSESSMENT_STATUSES
    assert isinstance(data["planning_estimate_cents"], int)
    assert isinstance(data["filing_estimate_cents"], int)


def assert_capital_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assessment_id", ""))
    assert data["category"] in ["DISTRIBUTION", "COLLECTION", "TREATMENT", "SOURCE", "STORAGE", "GENERAL"]
    assert data["horizon"] in ["IMMEDIATE", "SHORT_TERM", "LONG_TERM"]
    assert isinstance(data["cost_low_cents"], int) and data["cost_low_cents"] >= 0
    assert isinstance(data["cost_high_cents"], int) and data["cost_high_cents"] >= data["cost_low_cents"]
    assert isinstance(data["midpoint_estimate_cents"], int)
    assert isinstance(data["crews_required"], int) and data["crews_required"] >= 1
    assert data["status"] in CAPITAL_ITEM_STATUSES


def assert_valuation_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("target_id", ""))
    assert data["status"] in CASE_STATUSES


def assert_valuation_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["method"] in VALUATION_METHODS
    assert isinstance(data["value_cents"], int) and data["value_cents"] > 0
    assert isinstance(data["law_citation"], str)
    assert isinstance(data["appraiser_user_id"], str) and data["appraiser_user_id"]
    assert data["status"] in ENTRY_STATUSES


def assert_council_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("target_id", ""))
    assert data["kind"] in EVENT_KINDS
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data["status"] in EVENT_STATUSES


def assert_regulatory_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("target_id", ""))
    assert isinstance(data["purchase_price_cents"], int) and data["purchase_price_cents"] > 0
    assert data["rate_base_method"] in ["AS_PAID", "DEPRECIATED_ORIGINAL_COST"]
    assert isinstance(data["filing_round"], int) and data["filing_round"] >= 1
    assert data["status"] in APPLICATION_STATUSES


def assert_customer_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("target_id", ""))
    assert isinstance(data["account_ref"], str) and data["account_ref"]
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert isinstance(data["ar_balance_cents"], int) and data["ar_balance_cents"] >= 0
    assert data["status"] in ACCOUNT_STATUSES


def assert_transition_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("target_id", ""))
    assert data["category"] in TRANSITION_CATEGORIES
    assert data["status"] in TRANSITION_STATUSES


def assert_employee_transition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("target_id", ""))
    assert isinstance(data["employee_ref"], str) and data["employee_ref"]
    assert isinstance(data["years_of_service"], int) and data["years_of_service"] >= 0
    assert isinstance(data["weekly_salary_cents"], int) and data["weekly_salary_cents"] > 0
    assert isinstance(data["union_covered"], bool)
    assert data["status"] in EMPLOYEE_STATUSES


def assert_tariff_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("target_id", ""))
    assert data["mode"] in ["SINGLE_TARIFF", "STAND_ALONE"]
    assert isinstance(data["representative_old_bill_cents"], int) and data["representative_old_bill_cents"] > 0
    assert isinstance(data["consolidated_monthly_bill_cents"], int) and data["consolidated_monthly_bill_cents"] > 0
    assert data["status"] in TARIFF_STATUSES


def assert_deposit_settlement_invariants(account: dict):
    """Conservation invariants of the deposit settlement waterfall."""
    assert account["deposit_offset_cents"] + account["refund_cents"] == account["deposit_cents"]
    assert account["new_ar_balance_cents"] + account["deposit_offset_cents"] == account["ar_balance_cents"]
    assert account["deposit_offset_cents"] >= 0
    assert account["refund_cents"] >= 0
    assert account["new_ar_balance_cents"] >= 0
