"""Transitive cascades: tender award to category lock, and sell-through to store stats."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    CATEGORY_MANAGER_HEADERS,
    PROCUREMENT_LEAD_HEADERS,
    fixtures,
    make_store_manager_headers,
)


def _award_second_core_product(api, category, supplier_pairs):
    """Create a second CORE product and carry its tender through evaluation."""
    sup_c, sup_d = supplier_pairs
    product = fixtures.create_product(api, category["id"], unit_cost_cents=200)
    tender, bids, _ = fixtures.tender_in_evaluating(
        api, product["id"], bids=[(sup_c, 700, 80), (sup_d, 800, 70)],
    )
    return product, tender, bids


def test_award_cascades_product_activation_then_category_lock(api):
    """Award -> product ACTIVE -> count 2 -> category LOCKED, each hop caused by the last.

    PRD §3.4: "The product's `primary_supplier_id` and `secondary_supplier_id` are set from the winning bids, the product transitions `PROPOSED → ACTIVE`, and the resulting recomputation of the category's `active_sku_count` may auto-transition the category `OPEN → LOCKED`."
    PRD §3.1: "The `active_sku_count` is a computed field, not a stored guess: it counts the category's products whose `kind` is `CORE` and whose status is `ACTIVE`."

    Design: Difficulty/transitive_cascade/award_cascades_product_activation_category_lock
    """
    category = fixtures.create_category(api, sku_cap=2)
    first = fixtures.award_product_with_two_suppliers(api, category["id"])
    assert first["product"]["status"] == "ACTIVE"

    sup_c = fixtures.create_supplier(api)
    sup_d = fixtures.create_supplier(api)
    product2, tender2, bids2 = _award_second_core_product(api, category, (sup_c, sup_d))

    validate_success(
        api.award_tender(
            tender2["id"],
            {"primary_bid_id": bids2[0]["id"], "secondary_bid_id": bids2[1]["id"]},
            PROCUREMENT_LEAD_HEADERS,
        )
    )

    read_product = validate_success(api.get_product(product2["id"], CATEGORY_MANAGER_HEADERS))
    read_category = validate_success(api.get_category(category["id"], CATEGORY_MANAGER_HEADERS))

    assert read_product["status"] == "ACTIVE"
    assert read_product["primary_supplier_id"] == sup_c["id"]
    assert read_product["secondary_supplier_id"] == sup_d["id"]
    assert read_category["active_sku_count"] == 2, (
        f"two ACTIVE CORE products must count 2, got {read_category['active_sku_count']}"
    )
    assert read_category["status"] == "LOCKED", "count reaching the cap auto-locks the category"


def test_discontinue_cascades_category_unlock(api):
    """Discontinuing at the cap drops the count and auto-reopens the category.

    PRD §3.1: "When the count later drops below the cap — because a product was discontinued — the category auto-transitions `LOCKED → OPEN` on the same terms."
    PRD §3.2: "Discontinuation is an explicit `CategoryManager` action available only while the product is `ACTIVE`. It moves the product `ACTIVE → DISCONTINUED`, recomputes the owning category's `active_sku_count` (which may auto-`OPEN` a `LOCKED` category), refreshes the product's `updated_at`, and increments its `version`."

    Design: Difficulty/transitive_cascade/award_cascades_product_activation_category_lock
    """
    category = fixtures.create_category(api, sku_cap=2)
    first = fixtures.award_product_with_two_suppliers(api, category["id"])
    sup_c = fixtures.create_supplier(api)
    sup_d = fixtures.create_supplier(api)
    product2, tender2, bids2 = _award_second_core_product(api, category, (sup_c, sup_d))

    validate_success(
        api.award_tender(
            tender2["id"],
            {"primary_bid_id": bids2[0]["id"], "secondary_bid_id": bids2[1]["id"]},
            PROCUREMENT_LEAD_HEADERS,
        )
    )
    locked = validate_success(api.get_category(category["id"], CATEGORY_MANAGER_HEADERS))
    assert locked["status"] == "LOCKED"

    discontinued = validate_success(
        api.discontinue_product(first["product"]["id"], CATEGORY_MANAGER_HEADERS)
    )
    assert discontinued["status"] == "DISCONTINUED"

    reopened = validate_success(api.get_category(category["id"], CATEGORY_MANAGER_HEADERS))
    assert reopened["active_sku_count"] == 1
    assert reopened["status"] == "OPEN", "dropping below the cap auto-opens the category"


def test_sell_cascades_allocation_buy_and_store_sell_through(api):
    """Selling the last unit flips allocation and buy to SOLD_OUT and sets sell-through 100.

    PRD §3.5: "If that leaves the allocation at zero remaining, it auto-transitions to `SOLD_OUT`; the buy's `remaining_quantity` is then recomputed, and if it too reaches zero the buy auto-transitions `ON_SALE → SOLD_OUT`. When a buy reaches `SOLD_OUT`, every store holding an allocation of it has its `finds_sell_through_pct` recomputed — the percentage, from 0 to 100, of allocated Finds quantity sold across that store's allocations that sit in terminal sell states."

    Design: Difficulty/transitive_cascade/sell_cascades_buy_soldout_store_sellthrough
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category, price_cents=199)
    store = fixtures.create_store(api)
    world = fixtures.finds_buy_on_sale(
        api, product["id"], total_quantity=2,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    buy, alloc = world["buy"], world["allocations"][0]
    assert alloc["allocated_quantity"] == 2
    manager = make_store_manager_headers(store["id"])

    fixtures.set_clock(api, "2026-09-08T10:00:00Z")
    validate_success(api.sell_allocation(alloc["id"], {"quantity": 1}, manager))

    sold_out = validate_success(api.sell_allocation(alloc["id"], {"quantity": 1}, manager))
    assert sold_out["status"] == "SOLD_OUT", (
        f"selling the last unit flips the allocation to SOLD_OUT, got {sold_out['status']}"
    )

    read_buy = validate_success(api.get_finds_buy(buy["id"], CATEGORY_MANAGER_HEADERS))
    assert read_buy["remaining_quantity"] == 0
    assert read_buy["status"] == "SOLD_OUT", (
        f"zero remaining flips the buy ON_SALE -> SOLD_OUT, got {read_buy['status']}"
    )

    read_store = validate_success(api.get_store(store["id"], manager))
    assert read_store["finds_sell_through_pct"] == 100.0, (
        f"fully sold buy must read 100.0 sell-through, got {read_store['finds_sell_through_pct']}"
    )


def test_sell_cascade_recomputes_buy_remaining_on_partial_allocation_sell(api):
    """A partial sell decrements the buy's remaining while both stay ON_SALE.

    PRD §3.5: "A recorded sale increases `sold_quantity` by `quantity` and recomputes `remaining_quantity`. If that leaves the allocation at zero remaining, it auto-transitions to `SOLD_OUT`; the buy's `remaining_quantity` is then recomputed, and if it too reaches zero the buy auto-transitions `ON_SALE → SOLD_OUT`."

    Design: Difficulty/transitive_cascade/sell_cascades_buy_soldout_store_sellthrough
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category)
    store = fixtures.create_store(api)
    world = fixtures.finds_buy_on_sale(
        api, product["id"], total_quantity=3,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    buy, alloc = world["buy"], world["allocations"][0]
    manager = make_store_manager_headers(store["id"])

    fixtures.set_clock(api, "2026-09-08T10:00:00Z")
    sold = validate_success(api.sell_allocation(alloc["id"], {"quantity": 2}, manager))
    assert sold["status"] == "ON_SALE"
    assert sold["sold_quantity"] == 2
    assert sold["remaining_quantity"] == 1

    read_buy = validate_success(api.get_finds_buy(buy["id"], CATEGORY_MANAGER_HEADERS))
    assert read_buy["remaining_quantity"] == 1, (
        f"buy remaining recomputes after the sell: 3 - 2 = 1, got {read_buy['remaining_quantity']}"
    )
    assert read_buy["status"] == "ON_SALE", "partial sell leaves the buy ON_SALE"
