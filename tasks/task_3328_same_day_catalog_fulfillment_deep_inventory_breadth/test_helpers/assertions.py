"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import WIP_STOCK_FEET, FINISHED_STOCK_FEET


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version on a full common-field resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_fields(data: dict):
    """Append-only resources carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only rows must not expose updated_at"
    assert "version" not in data, "append-only rows must not expose version"


def assert_distribution_center(data: dict):
    assert_common_fields(data)
    assert isinstance(data["code"], str) and 2 <= len(data["code"]) <= 8
    assert data["region"] in ["NORTHEAST", "SOUTHEAST", "MIDWEST", "SOUTHWEST", "WEST"]
    assert data["operations_posture"] in ["OPEN", "RESTRICTED", "LOCKDOWN"]
    assert isinstance(data["cutoff_sequence_index"], int)
    assert isinstance(data["inbound_reserved_units"], int)
    assert isinstance(data["cutoff_passed"], bool)
    assert isinstance(data["inbound_capacity_units"], int) and data["inbound_capacity_units"] >= 0
    assert isinstance(data["transit_seconds"], int) and data["transit_seconds"] >= 0
    assert -480 <= data["utc_offset_minutes"] <= 840


def assert_catalog_item(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["catalog_status"] in ["ACTIVE", "SUSPENDED"]
    assert data["curation_review_state"] in ["UNREVIEWED", "APPROVED"]
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 1
    assert data["unit_weight_kg"] > 0
    assert isinstance(data["curation_bundle_size"], int)
    assert isinstance(data["curated_dimension_json"], dict)
    assert isinstance(data["long_tail"], bool)


def assert_item_attribute(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["item_id"], str)
    assert isinstance(data["attribute_name"], str) and data["attribute_name"]
    assert isinstance(data["attribute_value"], str) and data["attribute_value"]


def assert_item_cross_reference(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["referenced_manufacturer"], str)
    assert isinstance(data["referenced_part_number"], str)


def assert_supplier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["long_tail_authorized"], bool)
    assert data["commitment_breach_count"] >= 0
    assert data["performance_rating_units"] == 100 - 10 * data["commitment_breach_count"], (
        "performance_rating_units must be derived from commitment_breach_count"
    )


def assert_availability_report(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["item_id"], str)
    assert data["reported_available_units"] >= 0


def assert_curation_review(data: dict):
    assert_common_fields(data)
    assert data["review_status"] in ["OPEN", "REVOKED"]
    assert isinstance(data["approved_count"], int)
    assert isinstance(data["bundle_level_revision"], int)
    assert isinstance(data["revision_round_baseline"], int)


def assert_curation_review_item(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["review_id"], str)
    assert isinstance(data["item_id"], str)
    assert isinstance(data["item_attribute_counter"], int)


def assert_stock_row(data: dict):
    assert_common_fields(data)
    assert isinstance(data["item_id"], str)
    assert isinstance(data["dc_id"], str)
    assert isinstance(data["account_id"], str)
    assert data["reserved_units"] >= 0
    assert data["available_units"] == data["on_hand_units"] - data["reserved_units"], (
        "available_units must equal on_hand_units - reserved_units"
    )
    if data.get("positioning_flag") is not None:
        assert data["positioning_flag"] in ["OK", "UNDERSTOCKED", "LONG_TAIL_DEFICIT"]


def assert_customer_account(data: dict):
    assert_common_fields(data)
    assert isinstance(data["account_name"], str)
    assert data["home_region"] in ["NORTHEAST", "SOUTHEAST", "MIDWEST", "SOUTHWEST", "WEST"]
    assert isinstance(data["open_claim_count"], int) and data["open_claim_count"] >= 0


def assert_catalog_order(data: dict):
    assert_common_fields(data)
    assert data["order_status"] in ["DRAFT", "RELEASED", "CANCELLED"]
    assert data["fulfillment_status"] in ["AWAITING_RELEASE", "ALLOCATED", "PICKED",
                                          "SHIPPED", "RETURNED"]
    assert isinstance(data["line_count"], int)
    assert isinstance(data["total_small_line_fee_cents"], int)
    assert isinstance(data["order_total_cents"], int)
    assert isinstance(data["same_day_committed"], bool)
    assert isinstance(data["commit_minutes_before_cutoff"], int)
    assert data["commit_minutes_before_cutoff"] >= 0, "the value is saturated at 0"


def assert_order_line(data: dict):
    assert_common_fields(data)
    assert data["line_status"] in ["PENDING", "ALLOCATED", "PICKED", "SHORT",
                                   "RESTOCKED", "RETURNED"]
    assert data["quantity"] >= 1
    assert isinstance(data["line_subtotal_cents"], int)
    assert isinstance(data["allocated_small_line_fee_cents"], int)
    assert data["allocated_small_line_fee_cents"] >= 0
    assert data["line_total_cents"] == (
        data["line_subtotal_cents"] + data["allocated_small_line_fee_cents"]
    ), "line_total_cents must be the subtotal plus the line's share of the fee"


def assert_pick_task(data: dict):
    assert_common_fields(data)
    assert data["pick_status"] in ["QUEUED", "PICKING", "PICKED", "SHORT_CLOSED"]
    assert data["shortage_disposition"] in ["NONE", "MADE_TO_ORDER"]
    assert data["picked_units"] >= 0
    assert data["requested_units"] >= 1


def assert_shipment(data: dict):
    assert_common_fields(data)
    assert data["shipment_status"] in ["STAGED", "CUTOFF_CONFIRMED", "DISPATCHED", "HELD"]
    assert data["service_level"] in ["GROUND", "TWO_DAY", "OVERNIGHT"]
    assert data["freight_charge_cents"] == (
        data["freight_rate_cents"] + data["freight_surcharge_cents"]
    ), "freight_charge_cents must be rate plus surcharge"


def assert_return_authorization(data: dict):
    assert_common_fields(data)
    assert data["return_status"] in ["DRAFT", "APPROVED", "RECEIVED", "CANCELLED"]
    assert data["restock_units"] >= 0
    assert data["damaged_units"] >= 0


def assert_damage_claim(data: dict):
    assert_common_fields(data)
    assert data["claim_status"] in ["OPEN", "RESUMED", "RESOLVED", "REJECTED", "VOIDED"]
    assert data["disposition"] in ["PENDING", "REPLACE_FROM_STOCK", "ZERO_CHARGE_RESHIP"]
    assert data["claim_units"] >= 0


def assert_square_footage_request(data: dict):
    assert_common_fields(data)
    assert data["request_status"] in ["QUOTED", "CUTTING", "FULFILLED", "RETURNED"]
    assert data["committed_variant"] in ["FORWARD_LOOKING", "ON_HAND_ONLY"]
    assert isinstance(data["committed_length_feet"], int)
    assert isinstance(data["prior_committed_length_feet"], int)


def assert_square_footage_line(data: dict):
    assert_common_fields(data)
    assert data["line_status"] in ["PLANNED", "CUT"]
    assert data["cut_list_ordinal"] >= 1
    assert data["requested_feet"] >= 1


def assert_clock_tick(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["current_utc"], str)
    assert isinstance(data["dc_local_times"], dict)


# --- domain invariant checkers ---------------------------------------------------

def assert_order_invariants(data: dict):
    """Money invariants that must hold on any order, whatever the state."""
    assert_cost_precision(data["order_total_cents"])
    assert_cost_precision(data["total_small_line_fee_cents"])
    assert data["total_small_line_fee_cents"] >= 0
    assert data["order_total_cents"] >= 0
    assert data["line_count"] >= 0
    assert data["freight_charge_cents"] >= 0


def assert_fee_fully_allocated(order: dict, lines: list):
    """The order's handling fee equals the sum of its lines' allocated shares."""
    allocated = sum(line["allocated_small_line_fee_cents"] for line in lines)
    assert allocated == order["total_small_line_fee_cents"], (
        f"allocated line fees {allocated} must equal the order total "
        f"{order['total_small_line_fee_cents']}"
    )


def assert_stock_ledger_conserved(stock_rows: list, expected_total: int):
    """Q_stock = sum of (on_hand_units + reserved_units) over the rows."""
    total = sum(row["on_hand_units"] + row["reserved_units"] for row in stock_rows)
    assert total == expected_total, f"Q_stock drifted: expected {expected_total}, got {total}"


def assert_recoverable_units_conserved(on_hand_units: int, line_damaged_units: int,
                                       expected_total: int):
    """Q_recoverable = the center's on-hand units plus the line's damaged units."""
    total = on_hand_units + line_damaged_units
    assert total == expected_total, (
        f"Q_recoverable drifted: expected {expected_total}, got {total}"
    )


def assert_pipe_variant_allowance(variant: str):
    """The two commitment variants differ only in the trailing stock allowance."""
    if variant == "FORWARD_LOOKING":
        return WIP_STOCK_FEET
    return FINISHED_STOCK_FEET