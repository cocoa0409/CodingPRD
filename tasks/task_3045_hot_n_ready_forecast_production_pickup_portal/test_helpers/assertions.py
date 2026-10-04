"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import JsonObject


def assert_common_fields(data: JsonObject):
    """Standard system-managed fields every primary resource carries."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_store_day(data: JsonObject):
    assert_common_fields(data)
    assert isinstance(data.get("business_date"), str)
    assert data.get("status") in ("PLANNING", "OPEN", "CLOSED", "RECONCILED")
    for field in ("produced_units", "sold_units", "discarded_units", "donated_units"):
        assert isinstance(data.get(field), int) and data[field] >= 0
    for field in ("waste_pct_standard", "waste_pct_net"):
        assert isinstance(data.get(field), (int, float))


def assert_daypart(data: JsonObject):
    assert_common_fields(data)
    assert data.get("label") in ("LUNCH", "DINNER", "LATE_NIGHT")
    assert data.get("status") in ("PLANNED", "ACTIVE", "CLOSED")
    assert data.get("posture") in ("NORMAL", "RESTRICTED")
    assert isinstance(data.get("window_start_minute"), int)
    assert isinstance(data.get("window_end_minute"), int)
    assert isinstance(data.get("rack_capacity"), int)
    assert isinstance(data.get("base_demand_units"), int)
    assert isinstance(data.get("preorder_reserved_units"), int)
    assert isinstance(data.get("forecast_units_provisional"), int)
    assert isinstance(data.get("made_ahead_target"), int)


def assert_product(data: JsonObject):
    assert_common_fields(data)
    assert isinstance(data.get("sku"), str)
    assert isinstance(data.get("list_price_cents"), int)
    assert isinstance(data.get("customization_allowed"), bool)
    assert isinstance(data.get("promo_locked"), bool)


def assert_production_run(data: JsonObject):
    assert_common_fields(data)
    assert data.get("status") in ("PLANNED", "BAKING", "HOLDING", "CLOSED")
    assert isinstance(data.get("quantity"), int) and data["quantity"] >= 1


def assert_hold_unit(data: JsonObject):
    assert_common_fields(data)
    assert data.get("status") in ("HOLDING", "ALLOCATED", "SOLD", "DISCARDED")


def assert_order(data: JsonObject):
    assert_common_fields(data)
    assert data.get("kind") in ("PORTAL_STANDARD", "PORTAL_PREORDER", "COUNTER")
    assert data.get("payment_status") in ("UNPAID", "PAID", "REFUNDED")
    assert data.get("fulfillment_status") in (
        "PLACED",
        "IN_PREPARATION",
        "READY",
        "PICKED_UP",
        "CANCELLED",
        "EXPIRED_NO_SHOW",
    )
    for field in ("subtotal_cents", "portal_fee_cents", "total_cents"):
        assert isinstance(data.get(field), int) and data[field] >= 0
    assert isinstance(data.get("made_ahead_units"), int)
    assert isinstance(data.get("made_to_order_units"), int)


def assert_locker_slot(data: JsonObject):
    assert_common_fields(data)
    assert data.get("status") in ("IDLE", "OCCUPIED", "CLEANING")
    assert isinstance(data.get("slot_number"), int) and data["slot_number"] >= 1


def assert_waste_log(data: JsonObject):
    """WasteLog rows are immutable audit appends: id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "a waste log row carries no updated_at"
    assert "version" not in data, "a waste log row carries no version"
    assert data.get("quantity") == 1
    assert data.get("reason") in ("HOLD_EXPIRED", "DAMAGED", "QUALITY", "NO_SHOW")
    assert isinstance(data.get("donated"), bool)


def assert_dough_batch(data: JsonObject):
    assert_common_fields(data)
    assert data.get("status") in ("MIXING", "PROOFING", "PROOFED", "DEPLETED", "EXPIRED")
    assert isinstance(data.get("size_units"), int) and data["size_units"] >= 1
    assert isinstance(data.get("remaining_units"), int)


def assert_cheese_batch(data: JsonObject):
    assert_common_fields(data)
    assert data.get("status") in ("PREPPING", "RESTING", "READY", "DEPLETED")
    assert isinstance(data.get("size_units"), int) and data["size_units"] >= 1
    assert isinstance(data.get("remaining_units"), int)


def assert_crew_shift(data: JsonObject):
    assert_common_fields(data)
    assert data.get("station") in ("OVEN", "CUT_TABLE", "LOCKER_BAY", "DOUGH_PREP")
    assert data.get("status") in ("SCHEDULED", "ENDED")


def assert_demand_event(data: JsonObject):
    assert_common_fields(data)
    assert data.get("status") in ("SCHEDULED", "ACTIVE", "ENDED", "CANCELLED")
    assert isinstance(data.get("demand_multiplier"), (int, float))


__all__ = [
    "assert_common_fields",
    "assert_store_day",
    "assert_daypart",
    "assert_product",
    "assert_production_run",
    "assert_hold_unit",
    "assert_order",
    "assert_locker_slot",
    "assert_waste_log",
    "assert_dough_batch",
    "assert_cheese_batch",
    "assert_crew_shift",
    "assert_demand_event",
]
