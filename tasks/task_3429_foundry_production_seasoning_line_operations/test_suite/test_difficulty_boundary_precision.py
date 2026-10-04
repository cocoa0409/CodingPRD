"""Difficulty queue: boundary precision — the inclusive scrap-index RED bound at
exactly 0.0800, and allocation of exactly the available inventory pool."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_allocation,
    create_retail_allocation_payload,
    get_inventory_record,
    get_order,
    scrap_unit_via_defect,
    setup_inventory_with_stock,
    setup_shaken_units,
    validate_error,
)

_RP = TEST_USERS["retail_planner_headers"]


def _two_plain_scraps_over_25():
    """25 poured, 2 plain defect scraps -> scrap_weighted 2.0, index 0.0800."""
    ctx = setup_shaken_units(num_units=25, order_overrides={"planned_quantity": 30})
    u1, u2 = ctx["unit_ids"][0], ctx["unit_ids"][1]
    scrap_unit_via_defect(u1, defect_type="POROSITY", severity="MINOR")
    scrap_unit_via_defect(u2, defect_type="SAND_INCLUSION", severity="MINOR")
    return ctx


def test_scrap_index_exactly_at_restrict_threshold_is_red(api):
    """PRD §2.8: "Both band lower bounds are inclusive — a `scrap_index` of exactly
    0.0400 is `WATCH`, not `GREEN`, and exactly 0.0800 is `RED`."
    2.0 weighted over 25 poured gives exactly 0.0800 — the inclusive RED lower
    bound.

    Design: Difficulty/boundary_precision_check/scrap_index_exactly_at_restrict_threshold
    """
    ctx = _two_plain_scraps_over_25()
    order = get_order(ctx["order"]["id"])
    assert order["scrap_weighted_units"] == pytest.approx(2.0, abs=1e-9)
    assert order["scrap_index"] == pytest.approx(0.08, abs=1e-9), (
        f"scrap_index {order['scrap_index']} != exactly 0.0800 (2.0 / 25)")
    assert order["scrap_tier"] == "RED"


def test_posture_restricted_at_exact_threshold(api):
    """PRD §2.8: "otherwise it is `RESTRICTED` when the order's `scrap_tier` is
    `RED` (equivalently, when `scrap_index` is at least 0.08); otherwise it is
    `OPEN`."
    At scrap_index == 0.0800 the posture gate closes to RESTRICTED; any value below
    would have stayed OPEN.

    Design: Difficulty/boundary_precision_check/scrap_index_exactly_at_restrict_threshold
    """
    ctx = _two_plain_scraps_over_25()
    order = get_order(ctx["order"]["id"])
    assert order["posture"] == "RESTRICTED"


def test_allocation_of_exactly_available_units_succeeds(api):
    """PRD §3.8: "an `allocated_qty` of at least 1 and at most the record's
    `available_units` — equality allowed, otherwise `ERR_INSUFFICIENT_INVENTORY`
    (HTTP 422)"
    Allocating all 10 on-hand units (qty == available_units) is allowed and drives
    available_units to exactly 0.

    Design: Difficulty/boundary_precision_check/allocation_consumes_exactly_available_units
    """
    ctx = setup_inventory_with_stock(num_units=10)
    record = ctx["inventory_record"]
    assert record["on_hand_units"] == 10
    assert record["available_units"] == 10
    allocation = create_allocation(record["id"], allocated_qty=10)
    assert allocation["status"] == "PROPOSED"
    after = get_inventory_record(record["id"])
    assert after["on_hand_units"] == 10
    assert after["reserved_units"] == 10
    assert after["available_units"] == 0


def test_one_unit_over_exhausted_pool_rejected(api):
    """PRD §3.8: "an `allocated_qty` of at least 1 and at most the record's
    `available_units` — equality allowed, otherwise `ERR_INSUFFICIENT_INVENTORY`
    (HTTP 422)"
    After the pool is fully reserved, the very next 1-unit allocation fails.

    Design: Difficulty/boundary_precision_check/allocation_consumes_exactly_available_units
    """
    ctx = setup_inventory_with_stock(num_units=10)
    record = ctx["inventory_record"]
    create_allocation(record["id"], allocated_qty=10)
    current = get_inventory_record(record["id"])
    payload = create_retail_allocation_payload(
        record["id"], current["version"], allocated_qty=1, channel="ECOMMERCE")
    resp = api.create_retail_allocation(payload, _RP)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)
