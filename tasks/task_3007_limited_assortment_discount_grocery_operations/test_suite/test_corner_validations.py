"""Validation rules: uniqueness, packaging minimums, dual-source, windows, claim window."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CATEGORY_MANAGER_HEADERS,
    CUSTOMER_SERVICE_HEADERS,
    PROCUREMENT_LEAD_HEADERS,
    QA_LEAD_HEADERS,
    fixtures,
    make_store_manager_headers,
    make_supplier_rep_headers,
)
from test_helpers.factories import bid_payload, claim_payload, product_payload


def test_duplicate_sku_code_rejected_globally(api):
    """A sku_code collision across categories fails ERR_DUPLICATE_SKU.

    PRD §3.2: "A `barcode_count` below those minimums is rejected with `ERR_BARCODE_COUNT_INVALID`, and a `sku_code` that collides with any existing product is rejected with `ERR_DUPLICATE_SKU`."
    PRD §3.2: "A `CategoryManager` creates a product by supplying its `category_id`, a globally unique `sku_code`, a display `name`, its `kind`, whether it ships in `shelf_ready_packaging`, its `barcode_count`, a target `unit_cost_cents`, and a shelf `price_cents`."

    Design: Corner/validations/duplicate_sku_code_rejected
    """
    cat1 = fixtures.create_category(api, code="C1")
    cat2 = fixtures.create_category(api, code="C2")
    fixtures.create_product(api, cat1["id"], sku_code="SKU-1")

    response = api.create_product(
        product_payload(cat2["id"], sku_code="SKU-1", name="Prod Dup"),
        CATEGORY_MANAGER_HEADERS,
    )
    validate_error(response, "ERR_DUPLICATE_SKU", 409)


def test_shelf_ready_requires_two_barcodes(api):
    """Shelf-ready with one barcode violates the multi-barcode rule: 422.

    PRD §3.2: "Barcode design supports the cashier scan-rate standard: every product needs at least 1 barcode, and any product with `shelf_ready_packaging` must carry at least 2 scannable barcodes so a cashier can always find one without re-orienting the case. A `barcode_count` below those minimums is rejected with `ERR_BARCODE_COUNT_INVALID`, and a `sku_code` that collides with any existing product is rejected with `ERR_DUPLICATE_SKU`."

    Design: Corner/validations/shelf_ready_requires_two_barcodes
    """
    category = fixtures.create_category(api)
    response = api.create_product(
        product_payload(category["id"], shelf_ready_packaging=True, barcode_count=1),
        CATEGORY_MANAGER_HEADERS,
    )
    validate_error(response, "ERR_BARCODE_COUNT_INVALID", 422)


def test_finds_product_requires_shelf_ready(api):
    """A FINDS product without shelf_ready_packaging fails ERR_SHELF_READY_REQUIRED.

    PRD §3.2: "`FINDS` products are weekly one-time promotional buys: exempt from the cap, but held to a stricter merchandising standard — a `FINDS` product created without `shelf_ready_packaging` set to true is rejected with `ERR_SHELF_READY_REQUIRED`, because pallet-display merchandising admits no decanting labor."

    Design: Corner/validations/finds_product_requires_shelf_ready
    """
    category = fixtures.create_category(api)
    response = api.create_product(
        product_payload(
            category["id"], kind="FINDS", shelf_ready_packaging=False, barcode_count=3
        ),
        CATEGORY_MANAGER_HEADERS,
    )
    validate_error(response, "ERR_SHELF_READY_REQUIRED", 422)


def test_duplicate_bid_same_supplier_rejected(api):
    """One bid per supplier per tender: the second submission fails ERR_BID_DUPLICATE.

    PRD §3.4: "One bid per supplier per tender — a second submission is rejected with `ERR_BID_DUPLICATE`."

    Design: Corner/validations/duplicate_bid_same_supplier_rejected
    """
    category = fixtures.create_category(api)
    supplier = fixtures.create_supplier(api)
    product = fixtures.create_product(api, category["id"])
    tender = fixtures.create_open_tender(api, product["id"], bid_ceiling_cents=1000)

    fixtures.submit_bid(api, tender["id"], supplier, 700)
    response = api.create_bid(
        tender["id"], bid_payload(supplier["id"], 650),
        make_supplier_rep_headers(supplier["id"]),
    )
    validate_error(response, "ERR_BID_DUPLICATE", 409)


def test_blind_panel_sample_code_leak_rejected(api):
    """A sample_code containing the supplier's name breaks blinding: 422.

    PRD §3.4: "The blindness rule is hard: the `sample_code` must not equal or contain the bidding supplier's `id` or the supplier's `name`, and there is exactly one panel per bid — a second panel for the same bid is likewise refused. Either violation is rejected with `ERR_BLIND_VIOLATION`."

    Design: Corner/validations/blind_panel_sample_code_leak_rejected
    """
    category = fixtures.create_category(api)
    supplier = fixtures.create_supplier(api, name="Sup A")
    product = fixtures.create_product(api, category["id"])
    tender = fixtures.create_open_tender(api, product["id"], bid_ceiling_cents=1000)
    bid = fixtures.submit_bid(api, tender["id"], supplier, 700)

    response = api.create_panel(bid["id"], {"sample_code": "SAMPLE-Sup A-01"}, QA_LEAD_HEADERS)
    validate_error(response, "ERR_BLIND_VIOLATION", 422)


def test_second_panel_for_same_bid_rejected(api):
    """Exactly one panel per bid: a second panel fails ERR_BLIND_VIOLATION.

    PRD §3.4: "The blindness rule is hard: the `sample_code` must not equal or contain the bidding supplier's `id` or the supplier's `name`, and there is exactly one panel per bid — a second panel for the same bid is likewise refused. Either violation is rejected with `ERR_BLIND_VIOLATION`."

    Design: Corner/validations/blind_panel_sample_code_leak_rejected
    """
    category = fixtures.create_category(api)
    supplier = fixtures.create_supplier(api, name="Sup A")
    product = fixtures.create_product(api, category["id"])
    tender = fixtures.create_open_tender(api, product["id"], bid_ceiling_cents=1000)
    bid = fixtures.submit_bid(api, tender["id"], supplier, 700)

    validate_success(
        api.create_panel(bid["id"], {"sample_code": "BLIND-01"}, QA_LEAD_HEADERS), 201
    )
    response = api.create_panel(bid["id"], {"sample_code": "BLIND-02"}, QA_LEAD_HEADERS)
    validate_error(response, "ERR_BLIND_VIOLATION", 422)


def test_award_same_supplier_dual_source_rejected(api):
    """Award naming the same bid as primary and secondary fails ERR_DUAL_SOURCE_REQUIRED.

    PRD §3.4: "Both must reference `ELIGIBLE` bids of this tender, and the two bids must come from two distinct suppliers; an award naming bids from the same supplier, or made when fewer than `min_sources` distinct suppliers hold `ELIGIBLE` bids, is rejected with `ERR_DUAL_SOURCE_REQUIRED`."

    Design: Corner/validations/award_same_supplier_dual_source_rejected
    """
    category = fixtures.create_category(api)
    sup_a = fixtures.create_supplier(api)
    sup_b = fixtures.create_supplier(api)
    product = fixtures.create_product(api, category["id"])
    tender, bids, _ = fixtures.tender_in_evaluating(
        api, product["id"], bids=[(sup_a, 700, 80), (sup_b, 800, 70)],
    )

    response = api.award_tender(
        tender["id"],
        {"primary_bid_id": bids[0]["id"], "secondary_bid_id": bids[0]["id"]},
        PROCUREMENT_LEAD_HEADERS,
    )
    validate_error(response, "ERR_DUAL_SOURCE_REQUIRED", 409)

    read = validate_success(api.get_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))
    assert read["status"] == "EVALUATING", "the rejected award leaves the tender EVALUATING"


def test_no_replenishment_after_activation(api):
    """Re-planning once the buy is ON_SALE fails ERR_FINDS_NO_REPLENISHMENT.

    PRD §3.5: "Once the buy has moved past `ALLOCATED`, planning is closed forever — there is no replenishment — and any further planning attempt is rejected with `ERR_FINDS_NO_REPLENISHMENT`."

    Design: Corner/validations/no_replenishment_after_activation
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category)
    fixtures.create_store(api)
    world = fixtures.finds_buy_on_sale(
        api, product["id"], total_quantity=5,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    buy = world["buy"]

    fresh = validate_success(api.get_finds_buy(buy["id"], CATEGORY_MANAGER_HEADERS))
    response = api.plan_allocations(
        buy["id"], {"expected_finds_buy_version": fresh["version"]}, CATEGORY_MANAGER_HEADERS
    )
    validate_error(response, "ERR_FINDS_NO_REPLENISHMENT", 409)


def test_activate_succeeds_with_full_allocation(api):
    """Activation succeeds when allocated_quantity == total_quantity == 5.

    PRD §3.5: "First, conservation: the buy's `allocated_quantity` must equal its `total_quantity` exactly — an activation with any unit unallocated is rejected with `ERR_ALLOCATION_INCOMPLETE`."

    Design: Corner/validations/activate_incomplete_allocation_rejected
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category)
    fixtures.create_store(api)
    buy = fixtures.create_finds_buy(
        api, product["id"], total_quantity=5,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    buy = fixtures.plan_allocations(api, buy)
    assert buy["allocated_quantity"] == 5, "the waterfall allocates the full one-time buy"

    activated = validate_success(api.activate_finds_buy(buy["id"], CATEGORY_MANAGER_HEADERS))
    assert activated["status"] == "ON_SALE"


def test_sell_outside_window_rejected(api):
    """Selling the day before the sale window opens fails ERR_SALE_WINDOW_INACTIVE.

    PRD §3.5: "The sale must fall within the allocation's current sale window as read from the logical clock — a sell outside `[sale_start_date, sale_end_date]` is rejected with `ERR_SALE_WINDOW_INACTIVE` — and must not exceed the allocation's `remaining_quantity`, else `ERR_ALLOCATION_EXHAUSTED`."

    Design: Corner/validations/sell_outside_window_rejected
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category)
    store = fixtures.create_store(api)
    world = fixtures.finds_buy_on_sale(
        api, product["id"], total_quantity=5,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    alloc = world["allocations"][0]

    fixtures.set_clock(api, "2026-09-06T23:00:00Z")
    response = api.sell_allocation(
        alloc["id"], {"quantity": 1}, make_store_manager_headers(store["id"])
    )
    validate_error(response, "ERR_SALE_WINDOW_INACTIVE", 409)


def test_sell_exceeding_remaining_rejected(api):
    """Selling 4 against 3 remaining fails ERR_ALLOCATION_EXHAUSTED; nothing moves.

    PRD §3.5: "The sale must fall within the allocation's current sale window as read from the logical clock — a sell outside `[sale_start_date, sale_end_date]` is rejected with `ERR_SALE_WINDOW_INACTIVE` — and must not exceed the allocation's `remaining_quantity`, else `ERR_ALLOCATION_EXHAUSTED`."

    Design: Corner/validations/sell_exceeding_remaining_rejected
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category)
    store = fixtures.create_store(api)
    world = fixtures.finds_buy_on_sale(
        api, product["id"], total_quantity=3,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    alloc = world["allocations"][0]
    manager = make_store_manager_headers(store["id"])

    fixtures.set_clock(api, "2026-09-08T10:00:00Z")
    response = api.sell_allocation(alloc["id"], {"quantity": 4}, manager)
    validate_error(response, "ERR_ALLOCATION_EXHAUSTED", 409)

    read = validate_success(api.get_allocation(alloc["id"], manager))
    assert read["sold_quantity"] == 0, "the rejected sell must not change sold_quantity"


def test_claim_window_expired_46_days(api):
    """A purchase 46 days before the clock fails ERR_CLAIM_WINDOW_EXPIRED.

    PRD §3.9: "The purchase must be recent: a `purchase_date` more than 45 days before the logical clock's date at filing is rejected with `ERR_CLAIM_WINDOW_EXPIRED`."

    Design: Corner/validations/claim_window_expired_46_days
    """
    world = fixtures.claims_world(api)
    response = api.create_claim(
        claim_payload(
            world["product"]["id"], world["store"]["id"],
            quantity=1, unit_price_cents=199, purchase_date="2026-07-17", reason="OTHER",
        ),
        CUSTOMER_SERVICE_HEADERS,
    )
    validate_error(response, "ERR_CLAIM_WINDOW_EXPIRED", 422)


def test_claim_window_exactly_45_days_accepted(api):
    """A purchase exactly 45 days before the clock files cleanly as FILED.

    PRD §3.9: "The purchase must be recent: a `purchase_date` more than 45 days before the logical clock's date at filing is rejected with `ERR_CLAIM_WINDOW_EXPIRED`."

    Design: Corner/validations/claim_window_exactly_45_days_accepted
    """
    world = fixtures.claims_world(api)
    claim = validate_success(
        api.create_claim(
            claim_payload(
                world["product"]["id"], world["store"]["id"],
                quantity=1, unit_price_cents=199, purchase_date="2026-07-18", reason="OTHER",
            ),
            CUSTOMER_SERVICE_HEADERS,
        ),
        201,
    )
    assert claim["status"] == "FILED"


def test_reactivation_blocked_while_category_locked_then_succeeds(api):
    """Reactivate at the cap fails ERR_SKU_CAP_EXCEEDED; after a sibling drops, it succeeds.

    PRD §3.2: "Reactivation reverses this for a `DISCONTINUED` product, but only when two conditions hold: the owning category is `OPEN`, and — for `CORE` products — the category's `active_sku_count` is below its `sku_cap`. A reactivation that would fill the last slot is fine; one attempted against a category already at its cap is rejected with `ERR_SKU_CAP_EXCEEDED`."

    Design: Corner/validations/cross_entity_guard_category_locked_blocks_reactivation
    """
    category = fixtures.create_category(api, sku_cap=2)
    first = fixtures.award_product_with_two_suppliers(api, category["id"])
    second = fixtures.award_product_with_two_suppliers(api, category["id"])

    locked = validate_success(api.get_category(category["id"], CATEGORY_MANAGER_HEADERS))
    assert locked["status"] == "LOCKED"

    # Discontinue the first product, then bring a third into ACTIVE to refill
    # the cap — leaving the first product DISCONTINUED against a LOCKED category.
    validate_success(api.discontinue_product(first["product"]["id"], CATEGORY_MANAGER_HEADERS))
    fixtures.award_product_with_two_suppliers(api, category["id"])

    response = api.reactivate_product(first["product"]["id"], CATEGORY_MANAGER_HEADERS)
    validate_error(response, "ERR_SKU_CAP_EXCEEDED", 409)

    # Drop a sibling; the category auto-opens and reactivation succeeds.
    validate_success(api.discontinue_product(second["product"]["id"], CATEGORY_MANAGER_HEADERS))
    reactivated = validate_success(
        api.reactivate_product(first["product"]["id"], CATEGORY_MANAGER_HEADERS)
    )
    assert reactivated["status"] == "ACTIVE"
