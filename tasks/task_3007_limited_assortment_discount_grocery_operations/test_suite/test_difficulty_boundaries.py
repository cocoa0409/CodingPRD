"""Boundary precision: the SKU cap count boundary and the scan-rate threshold."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CATEGORY_MANAGER_HEADERS,
    PROCUREMENT_LEAD_HEADERS,
    fixtures,
    make_store_manager_headers,
)
from test_helpers.factories import scan_payload


def _evaluate_second_tender(api, category):
    """Second CORE product with an EVALUATING tender and two ELIGIBLE bids."""
    sup_c = fixtures.create_supplier(api)
    sup_d = fixtures.create_supplier(api)
    product = fixtures.create_product(api, category["id"], unit_cost_cents=200)
    tender, bids, _ = fixtures.tender_in_evaluating(
        api, product["id"], bids=[(sup_c, 700, 80), (sup_d, 800, 70)],
    )
    return product, tender, bids


def test_sku_cap_allows_filling_to_cap_then_rejects_beyond(api):
    """Count 1 -> 2 at cap 2 succeeds; a third activation fails ERR_SKU_CAP_EXCEEDED.

    PRD §3.4: "The tendered product must still be `PROPOSED`, and — for a `CORE` product — its category must have `active_sku_count` below `sku_cap`, or the award is rejected with `ERR_SKU_CAP_EXCEEDED`."
    PRD §3.1: "When the count reaches the cap, the category auto-transitions `OPEN → LOCKED`, refreshing its `updated_at` and incrementing its `version`; while `LOCKED`, no further activations are permitted."

    Design: Difficulty/boundary_precision_check/sku_cap_exact_boundary
    """
    category = fixtures.create_category(api, sku_cap=2)
    fixtures.award_product_with_two_suppliers(api, category["id"])

    product2, tender2, bids2 = _evaluate_second_tender(api, category)
    validate_success(
        api.award_tender(
            tender2["id"],
            {"primary_bid_id": bids2[0]["id"], "secondary_bid_id": bids2[1]["id"]},
            PROCUREMENT_LEAD_HEADERS,
        )
    )
    at_cap = validate_success(api.get_category(category["id"], CATEGORY_MANAGER_HEADERS))
    assert at_cap["active_sku_count"] == 2
    assert at_cap["status"] == "LOCKED", "count reaching the cap locks the category"

    # Third CORE product: category is at cap, so its award must be rejected.
    sup_e = fixtures.create_supplier(api)
    sup_f = fixtures.create_supplier(api)
    product3 = fixtures.create_product(api, category["id"], unit_cost_cents=200)
    tender3, bids3, _ = fixtures.tender_in_evaluating(
        api, product3["id"], bids=[(sup_e, 700, 80), (sup_f, 800, 70)],
    )
    response = api.award_tender(
        tender3["id"],
        {"primary_bid_id": bids3[0]["id"], "secondary_bid_id": bids3[1]["id"]},
        PROCUREMENT_LEAD_HEADERS,
    )
    validate_error(response, "ERR_SKU_CAP_EXCEEDED", 409)

    after = validate_success(api.get_category(category["id"], CATEGORY_MANAGER_HEADERS))
    assert after["active_sku_count"] == 2
    read_product3 = validate_success(api.get_product(product3["id"], CATEGORY_MANAGER_HEADERS))
    assert read_product3["status"] == "PROPOSED", (
        "the rejected award must not activate the product"
    )


def test_sku_cap_boundary_reactivation_fills_last_slot(api):
    """A reactivation that fills the last slot is fine; the next award fails.

    PRD §3.2: "A reactivation that would fill the last slot is fine; one attempted against a category already at its cap is rejected with `ERR_SKU_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/sku_cap_exact_boundary
    """
    category = fixtures.create_category(api, sku_cap=2)
    first = fixtures.award_product_with_two_suppliers(api, category["id"])
    validate_success(api.discontinue_product(first["product"]["id"], CATEGORY_MANAGER_HEADERS))

    second = fixtures.award_product_with_two_suppliers(api, category["id"])
    assert second["product"]["status"] == "ACTIVE"

    # Count is 1; reactivating the discontinued product fills the last slot.
    reactivated = validate_success(
        api.reactivate_product(first["product"]["id"], CATEGORY_MANAGER_HEADERS)
    )
    assert reactivated["status"] == "ACTIVE"

    locked = validate_success(api.get_category(category["id"], CATEGORY_MANAGER_HEADERS))
    assert locked["active_sku_count"] == 2
    assert locked["status"] == "LOCKED"

    # A third award must now fail at the boundary.
    product3, tender3, bids3 = _evaluate_second_tender(api, category)
    response = api.award_tender(
        tender3["id"],
        {"primary_bid_id": bids3[0]["id"], "secondary_bid_id": bids3[1]["id"]},
        PROCUREMENT_LEAD_HEADERS,
    )
    validate_error(response, "ERR_SKU_CAP_EXCEEDED", 409)


def test_scan_rate_exactly_1000_is_compliant(api):
    """Final rate exactly 1000.0 is COMPLIANT — the threshold is >=, not >.

    PRD §3.7: "The `compliance` flag follows directly: `COMPLIANT` when the final rate is at least 1000, `BELOW_STANDARD` below it — a shift landing exactly on 1000 is compliant."

    Design: Difficulty/boundary_precision_check/scan_rate_exact_threshold_compliant
    """
    world = fixtures.store_with_cashier(api)
    store, cashier = world["store"], world["cashier"]
    shift = fixtures.open_shift(api, store, cashier, opened_at="2026-09-01T08:00:00Z")

    validate_success(
        api.scan_shift(shift["id"], scan_payload(items_count=500), world["cashier_headers"])
    )
    fixtures.set_clock(api, "2026-09-01T08:30:00Z")

    closed = validate_success(
        api.close_shift(shift["id"], make_store_manager_headers(store["id"]))
    )
    assert closed["final_scan_rate"] == 1000.0, (
        f"500*3600/1800 = 1000.0 exactly, got {closed['final_scan_rate']}"
    )
    assert closed["compliance"] == "COMPLIANT", (
        "a shift landing exactly on 1000 is compliant"
    )


def test_scan_rate_one_item_below_threshold_is_below_standard(api):
    """499 items over the same half hour: 998.0 is below the standard.

    PRD §3.7: "The `compliance` flag follows directly: `COMPLIANT` when the final rate is at least 1000, `BELOW_STANDARD` below it — a shift landing exactly on 1000 is compliant."
    PRD §3.7: "Closing a shift — a `StoreManager` action restricted to the manager's own store — moves it `OPEN → CLOSED`, stamps `closed_at` from the logical clock, and computes the final variant exactly once: the count of scanned items minus 2 per void, multiplied by 3600 and divided by the shift's full duration in seconds (again with a denominator of at least 1), rounded half-up to 2 decimal places, stored as `final_scan_rate`."

    Design: Difficulty/boundary_precision_check/scan_rate_exact_threshold_compliant
    """
    world = fixtures.store_with_cashier(api)
    store, cashier = world["store"], world["cashier"]
    shift = fixtures.open_shift(api, store, cashier, opened_at="2026-09-01T08:00:00Z")

    validate_success(
        api.scan_shift(shift["id"], scan_payload(items_count=499), world["cashier_headers"])
    )
    fixtures.set_clock(api, "2026-09-01T08:30:00Z")

    closed = validate_success(
        api.close_shift(shift["id"], make_store_manager_headers(store["id"]))
    )
    assert closed["final_scan_rate"] == 998.0, (
        f"499*3600/1800 = 998.0, got {closed['final_scan_rate']}"
    )
    assert closed["compliance"] == "BELOW_STANDARD"
