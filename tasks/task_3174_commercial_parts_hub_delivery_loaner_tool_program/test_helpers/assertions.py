"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

# Field-level value sets used by the assertions below.
ACCOUNT_POSTURES = ["OPEN", "ON_HOLD", "CREDIT_SUSPENDED", "CLOSED"]
TIERS = ["BRONZE", "SILVER", "GOLD", "PLATINUM"]
FULFILLMENT_ROUTES = ["STORE", "HUB", "MEGA_HUB", "DC", "UNROUTABLE"]
ORDER_STATUSES = ["DRAFT", "CONFIRMED", "ALLOCATED", "PICKING",
                  "DISPATCHED", "DELIVERED", "RETURNED", "VOID"]
LOAN_STATUSES = ["REQUESTED", "CHECKED_OUT", "IN_USE", "DUE", "OVERDUE",
                 "RETURNED", "INSPECTED", "CLOSED", "FORFEITED"]
DEPOSIT_STATES = ["UNCHARGED", "HELD", "APPLIED_TO_BALANCE", "REFUNDED", "FORFEITED"]
CORE_RETURN_STATUSES = ["INITIATED", "IN_TRANSIT", "INSPECTED", "CREDITED", "REJECTED"]
ROUTE_STATUSES = ["DRAFT", "PLANNED", "DISPATCHED", "COMPLETED", "CANCELLED"]
STOP_STATUSES = ["PLANNED", "SEQUENCED", "EN_ROUTE", "DELIVERED", "MISSED", "REJECTED"]
COVERAGE_POSTURES = ["ACTIVE", "SCHEDULED", "EXPIRED"]
WEAR_BANDS = ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4", "LEVEL_5"]


# ── The shared audit spine ────────────────────────────────────────────────
def assert_audit_spine(data: dict):
    """id + created_at + updated_at + version, on every full-size resource."""
    assert is_valid_uuid(data["id"]), f"id must be a UUID, got {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"]), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data["updated_at"]), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_slim_record(data: dict):
    """Child records carry only id and created_at -- no updated_at, no version."""
    assert is_valid_uuid(data["id"]), f"id must be a UUID, got {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"]), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a slim child record has no updated_at"
    assert "version" not in data, "a slim child record has no version"


# ── Entity assertions ─────────────────────────────────────────────────────
def assert_commercial_account(data: dict):
    assert_audit_spine(data)
    for field in ("shop_name", "tax_id", "billing_address", "home_store_id"):
        assert isinstance(data[field], str) and data[field], f"{field} must be a non-empty string"
    assert data["account_posture"] in ACCOUNT_POSTURES
    assert data["tier"] in TIERS
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["credit_terms_days"], int)
    assert isinstance(data["petty_cash_cents"], int)
    assert isinstance(data["credit_exposure_cents"], int)
    assert isinstance(data["deposit_liability_cents"], int)
    assert isinstance(data["receivable_balance_cents"], int)
    assert isinstance(data["order_sequence"], int)
    assert isinstance(data["is_archived"], bool)


def assert_vehicle(data: dict):
    assert_audit_spine(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17, "vin must be 17 characters"
    assert isinstance(data["year"], int)
    assert data["drive_type"] in ["FWD", "RWD", "AWD", "FOUR_WD"]


def assert_part(data: dict):
    assert_audit_spine(data)
    for field in ("sku", "description", "line_code"):
        assert isinstance(data[field], str) and data[field], f"{field} must be a non-empty string"
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["core_charge_cents"], int)
    assert isinstance(data["is_hazardous"], bool)
    assert isinstance(data["is_returnable"], bool)
    assert isinstance(data["is_archived"], bool)
    assert data["catalog_state"] in ["ACTIVE", "SUPERSEDED"]
    assert isinstance(data["supersession_depth"], int)


def assert_tool_fitment(data: dict):
    assert_slim_record(data)
    assert data["placement"] in ["FRONT", "REAR_LEFT", "REAR_RIGHT", "OTHER"]
    assert isinstance(data["depth_index"], int)


def assert_part_interchange(data: dict):
    assert_slim_record(data)
    assert isinstance(data["interchange_sku"], str) and data["interchange_sku"]
    assert isinstance(data["interchange_brand"], str) and data["interchange_brand"]


def assert_part_fitment(data: dict):
    assert_slim_record(data)
    assert isinstance(data["year_from"], int)
    assert isinstance(data["year_to"], int)
    assert data["engine_code"] == "ANY" or isinstance(data["engine_code"], str)
    assert data["drive_type"] in ["FWD", "RWD", "AWD", "FOUR_WD", "ANY"]


def assert_store(data: dict):
    assert_audit_spine(data)
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert data["store_type"] in ["SATELLITE", "HUB", "MEGA_HUB", "DC"]
    assert isinstance(data["delivery_radius_miles"], (int, float))
    assert isinstance(data["cutoff_hour_local"], int)
    assert isinstance(data["cutoff_buffer_minutes"], int)
    assert isinstance(data["promise_time_minutes"], int)
    assert isinstance(data["daily_capacity_units"], int)
    assert isinstance(data["committed_units_today"], int)
    assert is_iso8601_timestamp(data["capacity_epoch_at"])
    assert isinstance(data["is_archived"], bool)


def assert_inventory_item(data: dict):
    assert_audit_spine(data)
    assert isinstance(data["on_hand_units"], int)
    assert isinstance(data["reserved_units"], int)
    assert isinstance(data["available_units"], int)
    assert data["available_units"] == max(0, data["on_hand_units"] - data["reserved_units"]), (
        "available_units must equal max(0, on_hand_units - reserved_units)"
    )


def assert_sales_rep(data: dict):
    assert_audit_spine(data)
    for field in ("email", "full_name", "district_code", "home_store_id"):
        assert isinstance(data[field], str) and data[field], f"{field} must be a non-empty string"
    assert isinstance(data["active_account_count"], int)
    assert data["active_account_count"] >= 0


def assert_rep_coverage(data: dict):
    assert_audit_spine(data)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["coverage_posture"] in COVERAGE_POSTURES


def assert_part_order(data: dict):
    assert_audit_spine(data)
    assert isinstance(data["member_sequence"], int)
    assert data["fulfillment_route"] in FULFILLMENT_ROUTES
    assert data["pricing_band"] in TIERS
    assert isinstance(data["parts_subtotal_cents"], int)
    assert isinstance(data["core_charge_total_cents"], int)
    assert isinstance(data["tier_discount_cents"], int)
    assert isinstance(data["refundable_deposit_cents"], int)
    assert isinstance(data["delivery_fee_cents"], int)
    assert isinstance(data["refundable_deposit_consumed_cents"], int)
    assert isinstance(data["order_base_cents"], int)
    assert isinstance(data["satisfaction_cents"], int)
    assert data["status"] in ORDER_STATUSES


def assert_tool_loan(data: dict):
    assert_audit_spine(data)
    assert isinstance(data["deposit_amount_cents"], int)
    assert data["deposit_state"] in DEPOSIT_STATES
    assert isinstance(data["deposit_forfeited_cents"], int)
    assert data["status"] in LOAN_STATUSES
    assert isinstance(data["overdue_days"], int)
    if data.get("forfeiture_rate") is not None:
        assert 0.0 <= data["forfeiture_rate"] <= 1.0, "forfeiture_rate must be within [0.00, 1.00]"


def assert_tool_catalog(data: dict):
    assert_audit_spine(data)
    assert isinstance(data["tool_sku"], str) and data["tool_sku"]
    assert isinstance(data["tool_name"], str) and data["tool_name"]
    assert isinstance(data["deposit_amount_cents"], int)
    assert isinstance(data["replacement_unit_cost_cents"], int)
    assert isinstance(data["wear_accumulated"], (int, float))
    assert data["wear_accumulated"] >= 0, "wear_accumulated can never be negative"
    assert data["wear_band"] in WEAR_BANDS
    assert 1.00 <= data["wear_multiplier_rate"] <= 2.00
    assert 0.00 <= data["wear_forfeiture_rate"] <= 1.00
    assert 12 <= data["wear_grace_period_hours"] <= 48


def assert_core_return(data: dict):
    assert_audit_spine(data)
    assert isinstance(data["core_subtotal_cents"], int)
    assert isinstance(data["restocking_fee_cents"], int)
    assert isinstance(data["warranty_covered"], bool)
    assert isinstance(data["credit_amount_cents"], int)
    assert data["status"] in CORE_RETURN_STATUSES


def assert_warranty_registration(data: dict):
    assert_slim_record(data)
    assert is_iso8601_timestamp(data["purchased_at"])
    assert is_iso8601_timestamp(data["warranty_expires_at"])
    assert data["warranty_expires_at"] > data["purchased_at"], (
        "warranty_expires_at must be strictly after purchased_at"
    )


def assert_route_stop(data: dict):
    assert_audit_spine(data)
    assert data["stop_kind"] in ["CUSTOMER", "RETURN_DESK"]
    assert is_iso8601_timestamp(data["delivery_window_start"])
    assert is_iso8601_timestamp(data["delivery_window_end"])
    assert data["status"] in STOP_STATUSES
    assert isinstance(data["lateness_minutes"], int)
    assert data["lateness_minutes"] >= 0, "lateness_minutes is never negative"


def assert_service_route(data: dict):
    assert_audit_spine(data)
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert data["driver_type"] in ["OWNED", "AFFILIATE"]
    assert is_iso8601_timestamp(data["departure_at"])
    assert is_iso8601_timestamp(data["shift_end_at"])
    assert data["status"] in ROUTE_STATUSES
    assert isinstance(data["run_credit_cents"], int)
    assert data["run_credit_cents"] >= 0


# ── Domain invariant checkers ─────────────────────────────────────────────
def assert_account_invariants(data: dict):
    """Invariants that hold after ANY operation on an account."""
    assert data["petty_cash_cents"] >= 0, "petty_cash_cents is never negative"
    assert data["credit_exposure_cents"] >= 0, "credit_exposure_cents is never negative"
    assert data["deposit_liability_cents"] >= 0, "deposit_liability_cents is never negative"
    assert data["receivable_balance_cents"] >= 0, "receivable_balance_cents is never negative"
    assert data["order_sequence"] >= 0
    assert_cost_precision(float(data["credit_exposure_cents"]))


def assert_deposit_position_conserved(account: dict):
    """The store's conserved deposit position is petty cash minus liability."""
    return account["petty_cash_cents"] - account["deposit_liability_cents"]


def assert_order_invariants(data: dict):
    """Invariants that hold after ANY order operation."""
    assert data["parts_subtotal_cents"] >= 0
    assert data["tier_discount_cents"] >= 0
    assert data["core_charge_total_cents"] >= 0
    assert data["refundable_deposit_cents"] >= 0
    assert data["delivery_fee_cents"] in (0, 795), (
        "the delivery fee is a two-outcome schedule: 0 or 795 cents"
    )
    assert data["refundable_deposit_consumed_cents"] >= 0
    assert data["refundable_deposit_consumed_cents"] <= data["refundable_deposit_cents"], (
        "the waterfall never pays out more than the order's refundable ceiling"
    )
    assert data["satisfaction_cents"] <= 1200, "the satisfaction score saturates at 1200 cents"