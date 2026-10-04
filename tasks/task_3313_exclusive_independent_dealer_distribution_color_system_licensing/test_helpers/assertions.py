"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_region(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["territory_radius_miles"] > 0
    assert 0 <= data["exclusivity_block_threshold_pct"] <= 100
    assert isinstance(data["active_dealer_count"], int)
    assert isinstance(data["pending_application_count"], int)


def assert_dealer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["region_id"])
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["status"] in ["APPLIED", "ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert data["channel_posture"] in ["INDEPENDENT_ONLY", "OVERRIDE_REQUIRED", "BLOCKED"]
    assert isinstance(data["bigbox_share_pct"], (int, float))
    assert isinstance(data["branding_compliant"], bool)
    assert 0 <= data["coop_accrual_rate"] <= 0.10
    assert isinstance(data["coop_balance_cents"], int)
    assert isinstance(data["coop_pending_cents"], int)
    assert isinstance(data["inventory_minimum_met"], bool)


def assert_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["region_id"])
    assert is_valid_uuid(data["dealer_id"])
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "WITHDRAWN"]
    assert isinstance(data["territory_conflict"], bool)


def assert_equipment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["dealer_id"])
    assert isinstance(data["serial_no"], str) and data["serial_no"]
    assert data["status"] in ["INSTALLED", "CALIBRATED", "CALIBRATION_OVERDUE", "DECOMMISSIONED"]
    assert isinstance(data["consecutive_failed_calibrations"], int)


def assert_colorant_system(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["generation"], int)
    assert data["annual_license_fee_cents"] >= 0
    assert data["min_initial_inventory_units"] > 0
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_product_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["colorant_system_id"])
    assert isinstance(data["code"], str) and data["code"]
    assert data["channel_class"] in ["DEALER_EXCLUSIVE", "SPECIALTY"]
    assert data["base_price_cents"] > 0
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]


def assert_formula(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["product_line_id"])
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["formulation_version"], int) and data["formulation_version"] >= 1
    assert isinstance(data["rematch_pending"], bool)
    assert data["status"] in ["ACTIVE", "ARCHIVED"]


def assert_formulation_change(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["product_line_id"])
    assert data["status"] in ["DRAFT", "ANNOUNCED", "EFFECTIVE", "COMPLETED", "CANCELLED"]


def assert_rematch_task(data: dict):
    # Append-only resource: id + created_at only; no updated_at, no version.
    _assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data["formulation_change_id"])
    assert is_valid_uuid(data["dealer_id"])
    assert is_valid_uuid(data["color_formula_id"])
    assert data["status"] in ["PENDING", "DONE"]
    assert data["new_formulation_version"] == data["old_formulation_version"] + 1


def assert_license(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["dealer_id"])
    assert is_valid_uuid(data["colorant_system_id"])
    assert data["status"] in ["PENDING", "ACTIVE", "EXPIRED", "SUSPENDED", "REVOKED"]


def assert_contractor(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["dealer_id"])
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["rolling_net_spend_cents"], int)
    assert data["tier"] in ["STANDARD", "SILVER", "GOLD", "PLATINUM"]
    assert data["status"] in ["ACTIVE", "CLOSED"]


def assert_purchase(data: dict):
    # Append-only resource: id + created_at only; no updated_at, no version.
    _assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data["contractor_account_id"])
    assert is_valid_uuid(data["product_line_id"])
    assert data["units"] > 0
    assert isinstance(data["unit_price_cents"], int)
    assert data["invoice_cents"] == data["units"] * data["unit_price_cents"]
    assert isinstance(data["reward_points_redemption_cents"], int)
    assert data["status"] in ["POSTED", "VOIDED"]


def assert_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["dealer_id"])
    assert is_valid_uuid(data["product_line_id"])
    assert data["units"] > 0
    assert data["purpose"] in ["INITIAL_STOCK", "RESTOCK"]
    assert data["invoice_cents"] == data["units"] * data["unit_price_cents"]
    assert data["status"] in [
        "SUBMITTED", "APPROVED", "REJECTED", "FULFILLED", "INVOICED", "PAID", "CANCELLED",
    ]


def assert_coop_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["dealer_id"])
    assert data["amount_cents"] > 0
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "PAID"]


def assert_channel_event(data: dict):
    # Append-only resource: id + created_at only; no updated_at, no version.
    _assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data["dealer_id"])
    assert data["channel"] in ["INDEPENDENT", "BIGBOX"]
    assert data["sales_cents"] > 0
    assert data["status"] in ["CONFIRMED", "SUPERSEDED"]
