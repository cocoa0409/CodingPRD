"""Entity assertions and domain invariant checkers.

Money is compared as whole integer cents; labor minutes and ratios are compared
with an explicit tolerance because the PRD carries them to two and four decimal
places respectively.  Instants are compared through the canonicalising helper in
``api_client`` so a server that emits three fractional digits and one that emits
none both satisfy the same assertion.
"""

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant, instants_equal

MINUTE_TOLERANCE = 0.005
RATIO_TOLERANCE = 0.00005


# --- generic building blocks ------------------------------------------------

def assert_common_fields(data: dict, entity_label: str = "resource") -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a server-minted UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 UTC instant, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 UTC instant, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity_label}.version must be an integer, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, (
        f"{entity_label}.version starts at 1, got {data['version']}"
    )


def assert_cents(value, expected: int, label: str) -> None:
    """Assert a money field is exactly this whole number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )
    assert value == expected, f"Expected {label} == {expected} cents, got {value}"


def assert_minutes(value, expected: float, label: str) -> None:
    """Assert a labor-minute field matches to two decimal places."""
    assert value is not None, f"{label} must be present"
    assert float(value) == pytest.approx(expected, abs=MINUTE_TOLERANCE), (
        f"Expected {label} == {expected:.2f} minutes, got {value}"
    )


def assert_ratio(value, expected: float, label: str) -> None:
    """Assert a ratio field matches to four decimal places."""
    assert value is not None, f"{label} must be present"
    assert float(value) == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"Expected {label} == {expected:.4f}, got {value}"
    )


def assert_instant(value, expected: str, label: str) -> None:
    """Assert an instant equals the expected instant at millisecond width."""
    assert value is not None, f"{label} must be present, got null"
    assert is_iso8601_timestamp(value), (
        f"{label} must be an ISO 8601 UTC instant, got {value!r}"
    )
    assert instants_equal(value, expected), (
        f"Expected {label} == {canonical_instant(expected)}, "
        f"got {canonical_instant(value)}"
    )


def assert_null(value, label: str) -> None:
    assert value is None, f"Expected {label} to be null, got {value!r}"


# --- per-resource assertions ------------------------------------------------

def assert_department(data: dict) -> None:
    assert_common_fields(data, "BakeryDepartment")
    assert isinstance(data["name"], str) and data["name"].strip()
    assert isinstance(data["store_number"], str) and data["store_number"].strip()
    assert 0 < float(data["shrink_budget_pct"]) <= 0.5
    assert float(data["labor_rate_cents_per_minute"]) > 0
    assert 0 <= float(data["freight_surcharge_pct"]) <= 0.5
    assert isinstance(data["donation_partner_enabled"], bool)
    assert isinstance(data["open_purchase_commitment_cents"], int)
    assert data["open_purchase_commitment_cents"] >= 0


def assert_product(data: dict) -> None:
    assert_common_fields(data, "Product")
    assert is_valid_uuid(data["department_id"])
    assert isinstance(data["sku"], str) and 1 <= len(data["sku"]) <= 20
    assert data["production_method"] in ("SCRATCH", "PAR_BAKED", "THAW_AND_SERVE")
    assert 1 <= data["units_per_rack"] <= 500
    assert data["unit_retail_cents"] >= 1
    assert 1 <= data["shelf_life_hours"] <= 720
    assert 0 < float(data["markdown_pct"]) < 1
    assert isinstance(data["allergen_tags"], list)
    assert isinstance(data["allergen_free_claim"], bool)
    assert isinstance(data["is_custom_cake_base"], bool)
    assert isinstance(data["recipe_lines"], list)


def assert_ingredient(data: dict) -> None:
    assert_common_fields(data, "Ingredient")
    assert is_valid_uuid(data["department_id"])
    assert 1 <= data["case_pack_units"] <= 1000
    assert float(data["unit_cost_cents"]) > 0
    assert 1 <= data["shelf_life_days"] <= 3650
    assert data["daily_usage_units"] >= 1
    assert data["reorder_point_units"] >= 0
    assert data["on_hand_units"] >= 0
    assert data["replenishment_state"] in ("OK", "REORDER_DUE", "ON_ORDER")


def assert_oven(data: dict) -> None:
    assert_common_fields(data, "Oven")
    assert is_valid_uuid(data["department_id"])
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 60
    assert 1 <= data["deck_count"] <= 8
    assert 1 <= data["rack_capacity_per_deck"] <= 20
    assert 0 <= data["changeover_buffer_minutes"] <= 120
    assert data["allergen_mode"] in ("SHARED", "NUT_FREE_DEDICATED")
    assert data["oven_status"] in ("AVAILABLE", "MAINTENANCE")


def assert_bake_day(data: dict) -> None:
    assert_common_fields(data, "BakeDay")
    assert is_valid_uuid(data["department_id"])
    assert data["plan_posture"] in ("DRAFT", "PLANNED", "LOCKED", "CLOSED")
    assert data["markdown_authorization"] in ("AUTO", "MANAGER_ONLY")
    assert data["day_of_week"] in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert isinstance(data["forecast_lines"], list)
    assert data["labor_budget_minutes"] >= 0
    for money_field in ("production_cost_cents", "shrink_cost_cents"):
        assert isinstance(data[money_field], int), (
            f"BakeDay.{money_field} must be an integer number of cents"
        )
    for unit_field in (
        "planned_units_total",
        "produced_units_total",
        "waste_units_total",
        "plan_unmet_unit_count",
    ):
        assert isinstance(data[unit_field], int) and data[unit_field] >= 0


def assert_production_run(data: dict) -> None:
    assert_common_fields(data, "ProductionRun")
    assert is_valid_uuid(data["bake_day_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["origin"] in ("PLAN_GENERATED", "MANUAL")
    assert data["execution_status"] in (
        "SCHEDULED",
        "PROOFING",
        "BAKING",
        "COMPLETED",
        "CANCELLED",
    )
    assert data["disposition_status"] in (
        "PENDING",
        "ON_SHELF",
        "MARKED_DOWN",
        "CLEARED",
    )
    assert data["rack_count"] >= 1
    assert isinstance(data["planned_units"], int)
    assert isinstance(data["ingredient_cost_cents"], int)
    if data["execution_status"] != "CANCELLED":
        assert data["cancelled_reason"] is None
    else:
        assert data["cancelled_reason"] in ("PLAN_SUPERSEDED", "DAY_CLOSED")


def assert_waste_record(data: dict) -> None:
    assert_common_fields(data, "WasteRecord")
    assert is_valid_uuid(data["bake_day_id"])
    assert is_valid_uuid(data["production_run_id"])
    assert data["disposition_reason"] in (
        "DAY_OLD_UNSOLD",
        "DONATED",
        "DAMAGED",
        "BURNT",
        "OVERPRODUCTION",
    )
    assert data["units"] >= 1
    assert isinstance(data["unit_cost_basis_cents"], int)
    assert isinstance(data["waste_cost_cents"], int)
    assert data["record_status"] in ("ACTIVE", "VOIDED")
    assert isinstance(data["attested_by_user_id"], str)


def assert_pickup_slot(data: dict) -> None:
    assert_common_fields(data, "PickupSlot")
    assert is_valid_uuid(data["bake_day_id"])
    assert is_iso8601_timestamp(data["slot_start_utc"])
    assert is_iso8601_timestamp(data["slot_end_utc"])
    assert 1 <= data["decorator_capacity_units"] <= 500
    assert 0 <= data["reserved_decoration_units"] <= data["decorator_capacity_units"]
    assert data["slot_status"] in ("OPEN", "CLOSED")


def assert_cake_order(data: dict) -> None:
    assert_common_fields(data, "CustomCakeOrder")
    assert is_valid_uuid(data["bake_day_id"])
    assert is_valid_uuid(data["pickup_slot_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["decoration_complexity"] in ("SIMPLE", "STANDARD", "PREMIUM")
    assert 1 <= data["tier_count"] <= 4
    assert data["order_status"] in (
        "INTAKE",
        "CONFIRMED",
        "IN_DECORATION",
        "READY",
        "PICKED_UP",
        "EXPIRED",
    )
    assert 0 <= data["revision_count"] <= 2
    for money_field in (
        "quote_subtotal_cents",
        "rush_fee_cents",
        "volume_discount_cents",
        "quote_total_cents",
    ):
        assert isinstance(data[money_field], int), (
            f"CustomCakeOrder.{money_field} must be an integer number of cents"
        )
    assert is_iso8601_timestamp(data["decoration_deadline_utc"])


def assert_ingredient_order(data: dict) -> None:
    assert_common_fields(data, "IngredientOrder")
    assert is_valid_uuid(data["department_id"])
    assert data["origin"] in ("MANUAL", "AUTO_REORDER")
    assert data["order_status"] in (
        "DRAFT",
        "SUBMITTED",
        "RECEIVED_FULL",
        "RECEIVED_SHORT",
        "CANCELLED",
    )
    assert isinstance(data["lines"], list)
    assert isinstance(data["order_total_cents"], int)
    for line in data["lines"]:
        assert isinstance(line["cases"], int) and line["cases"] >= 1
        assert isinstance(line["ordered_units"], int)
        assert isinstance(line["line_cost_cents"], int)


# --- domain invariants ------------------------------------------------------

def assert_run_unit_conservation(run: dict) -> None:
    """on_shelf_units is always actual_units less wasted_units_total (PRD §3.6)."""
    if run.get("actual_units") is None:
        return
    assert run["on_shelf_units"] == run["actual_units"] - run["wasted_units_total"], (
        f"Expected on_shelf_units == actual_units - wasted_units_total "
        f"({run['actual_units']} - {run['wasted_units_total']}), "
        f"got {run['on_shelf_units']}"
    )
    assert run["on_shelf_units"] >= 0, "on_shelf_units may never be negative"


def assert_order_total_is_sum_of_lines(order: dict) -> None:
    """order_total_cents is the sum of the already-rounded lines (PRD §3.8)."""
    total = sum(line["line_cost_cents"] for line in order["lines"])
    assert order["order_total_cents"] == total, (
        f"Expected order_total_cents == sum of line_cost_cents ({total}), "
        f"got {order['order_total_cents']}"
    )


def assert_quote_total_consistent(order: dict) -> None:
    """quote_total_cents is subtotal + rush fee - volume discount (PRD §3.7)."""
    expected = (
        order["quote_subtotal_cents"]
        + order["rush_fee_cents"]
        - order["volume_discount_cents"]
    )
    assert order["quote_total_cents"] == expected, (
        f"Expected quote_total_cents == {expected}, got {order['quote_total_cents']}"
    )


def find_line(order: dict, ingredient_id: str) -> dict:
    for line in order["lines"]:
        if line["ingredient_id"] == ingredient_id:
            return line
    raise AssertionError(
        f"No line for ingredient {ingredient_id} in order {order.get('id')}"
    )


def find_forecast_line(bake_day: dict, product_id: str, daypart: str) -> dict:
    for line in bake_day["forecast_lines"]:
        if line["product_id"] == product_id and line["daypart"] == daypart:
            return line
    raise AssertionError(
        f"No forecast line for product {product_id} / daypart {daypart}"
    )
