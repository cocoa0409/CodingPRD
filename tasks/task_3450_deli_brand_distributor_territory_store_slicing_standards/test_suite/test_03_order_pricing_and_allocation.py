"""Weekly ordering: allocation waterfall, tiered pricing, lot-unit conservation (PRD §3.3)."""
from test_helpers import (
    TEST_USERS,
    allocate_week,
    assert_lot_conservation,
    assert_order_line,
    assert_order_money_consistency,
    create_order,
    create_plant,
    create_production_run,
    create_product,
    complete_run,
    get_lot_for_run,
    get_order,
    make_distributor_rep_headers,
    make_plant_scheduler_headers,
    setup_active_distributor,
    setup_allocated_order,
    setup_lot,
    set_clock,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["brand_admin_headers"]


def _setup_two_tier_orders():
    """Distributor with products A (5000c) and B (3000c), 100 units of stock each,
    and two PENDING orders for week 2026-09-07: O1 = A x60 + B x40 (merch 420000),
    O2 = A x20 (merch exactly 100000). Returns (o1, o2) re-read after allocation."""
    net = setup_active_distributor()
    distributor = net["distributor"]
    product_a = create_product(code="A", name="Item A", base_price_cents=5000)
    product_b = create_product(code="B", name="Item B", base_price_cents=3000)
    plant = create_plant()
    run_a = create_production_run(
        plant, product_a, line_code="L1", capacity_units=200, planned_units=100)
    complete_run(run_a, plant, 100, 0)
    run_b = create_production_run(
        plant, product_b, line_code="L2", capacity_units=200, planned_units=100)
    complete_run(run_b, plant, 100, 0)
    order_1 = create_order(distributor, [(product_a["id"], 60), (product_b["id"], 40)])
    order_2 = create_order(distributor, [(product_a["id"], 20)])
    allocate_week(plant)
    return get_order(order_1["id"]), get_order(order_2["id"])


def test_pricing_tier_reads_pre_discount_total_at_boundary(api):
    """PRD §3.3: "Third, the discount tier is keyed on that pre-discount merchandise
    total: 8 percent when the merchandise total is at least 500,000 cents ($5,000.00),
    else 5 percent when it is at least 200,000 cents ($2,000.00), else 2 percent when
    it is at least 100,000 cents ($1,000.00), else no discount."

    O2 lands on exactly 100000 cents of merchandise, so the 2 percent tier applies
    (2000) even though the post-discount total then falls below the free-delivery bar.

    Design: Difficulty/combinatorial_formula/order_pricing_tier_fee_evaluation_order
    """
    _o1, o2 = _setup_two_tier_orders()
    assert o2["allocation_status"] == "ALLOCATED"
    assert o2["merchandise_total_cents"] == 100000
    assert o2["discount_cents"] == 2000, (
        f"2% tier at the exact 100000 pre-discount boundary: "
        f"expected 2000, got {o2['discount_cents']}"
    )
    assert_order_money_consistency(o2)


def test_delivery_fee_reads_post_discount_total(api):
    """PRD §3.3: "Fifth, `delivery_fee_cents` is zero when the merchandise total
    minus the discount is at least 100,000 cents ($1,000.00), and otherwise a flat
    1,500 cents ($15.00) — note the fee is keyed on the post-discount total and never
    feeds back into the tier."

    Pinned order proven twice over: O2's 100000 pre-discount earns the tier yet its
    98000 post-discount still pays the 1500 fee (total 99500), while O1's 420000
    pre-discount earns 5 percent (21000) and its 399000 post-discount ships free
    (total 399000).

    Design: Difficulty/combinatorial_formula/order_pricing_tier_fee_evaluation_order
    """
    o1, o2 = _setup_two_tier_orders()
    assert o2["delivery_fee_cents"] == 1500, (
        f"98000 post-discount < 100000 -> fee applies: got {o2['delivery_fee_cents']}"
    )
    assert o2["total_cents"] == 99500
    assert o1["merchandise_total_cents"] == 420000
    assert o1["discount_cents"] == 21000
    assert o1["delivery_fee_cents"] == 0, (
        f"399000 post-discount >= 100000 -> free: got {o1['delivery_fee_cents']}"
    )
    assert o1["total_cents"] == 399000
    assert o1["allocation_status"] == "ALLOCATED"
    assert_order_money_consistency(o1)


def test_allocation_moves_units_available_to_allocated(api):
    """PRD §3.4: "A conservation invariant holds from that moment forward: a lot's
    available, allocated, and delivered units plus the run's wasted units always
    equal the run's actual units." and PRD §3.3: "granted units move from each
    consumed lot's `available_units` into its `allocated_units`".

    Run completed 50 actual / 5 waste -> lot 45 available; a 20-unit allocation moves
    the lot to 25 available / 20 allocated, and 25 + 20 + 0 + 5 == 50 still holds.

    Design: Difficulty/compensating_invariant/lot_units_conserved_across_allocate_and_cancel
    """
    net = setup_active_distributor()
    product = create_product(code="P1", name="Item")
    supply = setup_lot(product, actual_units=50, waste_units=5)
    order = create_order(net["distributor"], [(product["id"], 20)])
    allocate_week(supply["plant"])
    lot = get_lot_for_run(supply["run"]["id"])
    run = validate_success(api.get_production_run(
        supply["run"]["id"], make_plant_scheduler_headers(supply["plant"]["id"])))
    assert lot["available_units"] == 25 and lot["allocated_units"] == 20, (
        f"after allocation expected 25/20, got "
        f"{lot['available_units']}/{lot['allocated_units']}"
    )
    assert_lot_conservation(lot, run)


def test_cancel_releases_allocated_units_back(api):
    """PRD §3.3: "Cancelling releases the order's allocated lot units back to
    availability, moving units from each lot's `allocated_units` to its
    `available_units` in reverse first-expiry order: latest `expires_at` first, ties
    by latest `created_at` first."

    The compensating cancel of the 20-unit allocation restores the lot to
    45 available / 0 allocated; 45 + 0 + 0 + 5 == 50 — no unit drift across the
    forward+compensating pair.

    Design: Difficulty/compensating_invariant/lot_units_conserved_across_allocate_and_cancel
    """
    net = setup_active_distributor()
    product = create_product(code="P1", name="Item")
    supply = setup_lot(product, actual_units=50, waste_units=5)
    order = create_order(net["distributor"], [(product["id"], 20)])
    allocate_week(supply["plant"])
    resp = api.cancel_order(
        order["id"], make_distributor_rep_headers(net["distributor"]["id"]))
    cancelled = validate_success(resp)
    assert cancelled["allocation_status"] == "CANCELLED"
    lot = get_lot_for_run(supply["run"]["id"])
    run = validate_success(api.get_production_run(
        supply["run"]["id"], make_plant_scheduler_headers(supply["plant"]["id"])))
    assert lot["available_units"] == 45 and lot["allocated_units"] == 0, (
        f"after cancel expected 45/0, got "
        f"{lot['available_units']}/{lot['allocated_units']}"
    )
    assert_lot_conservation(lot, run)


def test_elite_tier_outranks_earlier_standard_order(api):
    """PRD §3.3: "The system gathers every order of that week still in `PENDING` and
    processes them in a strict priority order: distributors of tier `ELITE` first,
    then `PREFERRED`, then `STANDARD`, with ties inside a tier broken by the order's
    `created_at`, earliest first." and "A `SHORTED` order has every money field
    written as zero."

    The later-created ELITE order takes the whole 10-unit pool; the earlier STANDARD
    order is SHORTED with qty_allocated 0 and all money fields 0.

    Design: Corner/calculations/allocation_prefers_elite_tier_over_earlier_standard
    """
    standard = setup_active_distributor(tier="STANDARD")
    elite = setup_active_distributor(tier="ELITE")
    product = create_product(code="P1", name="Item")
    supply = setup_lot(product, actual_units=10)
    order_std = create_order(standard["distributor"], [(product["id"], 10)])
    order_elite = create_order(elite["distributor"], [(product["id"], 10)])
    allocate_week(supply["plant"])

    elite_order = get_order(order_elite["id"])
    std_order = get_order(order_std["id"])
    assert elite_order["allocation_status"] == "ALLOCATED", (
        "ELITE tier rank wins despite the later created_at"
    )
    lines, _m = validate_paginated(api.list_order_lines(
        ADMIN, params={"order_id": order_elite["id"]}))
    assert sum(ln["qty_allocated"] for ln in lines) == 10
    assert std_order["allocation_status"] == "SHORTED"
    assert std_order["merchandise_total_cents"] == 0
    assert std_order["total_cents"] == 0


def test_partial_and_shorted_orders_priced_on_allocated_units(api):
    """PRD §3.3: "`PARTIAL` when at least one unit was granted but the order was not
    filled in full; `SHORTED` when not a single unit was granted." and "First, each
    line's `line_total_cents` is its `qty_allocated` multiplied by its snapshotted
    `unit_price_cents` — integer cents, no rounding, and a line allocated zero units
    contributes zero."

    O1 gets 10 of 15 requested units (the second product has no stock): PARTIAL with
    merchandise 5000, no tier, 1500 fee, total 6500. O2 gets nothing: SHORTED with
    every money field 0.

    Design: Corner/calculations/allocation_partial_and_zero_money_fields
    """
    net = setup_active_distributor()
    product_1 = create_product(code="P1", name="Item 1", base_price_cents=500)
    product_2 = create_product(code="P2", name="Item 2", base_price_cents=700)
    supply = setup_lot(product_1, actual_units=10)
    order_1 = create_order(
        net["distributor"], [(product_1["id"], 10), (product_2["id"], 5)])
    order_2 = create_order(net["distributor"], [(product_2["id"], 3)])
    allocate_week(supply["plant"])

    o1 = get_order(order_1["id"])
    assert o1["allocation_status"] == "PARTIAL"
    assert o1["merchandise_total_cents"] == 5000
    assert o1["discount_cents"] == 0
    assert o1["delivery_fee_cents"] == 1500
    assert o1["total_cents"] == 6500
    assert_order_money_consistency(o1)

    o2 = get_order(order_2["id"])
    assert o2["allocation_status"] == "SHORTED"
    assert o2["merchandise_total_cents"] == 0
    assert o2["discount_cents"] == 0
    assert o2["delivery_fee_cents"] == 0
    assert o2["total_cents"] == 0


def test_expired_lot_excluded_from_allocation_pool(api):
    """PRD §3.3: "The eligible supply pool for a line is the lots of that product
    whose `status` is `AVAILABLE`, whose `expires_at` is later than the current
    logical time, and whose `available_units` exceed zero."

    The lot expired at 2026-09-02T00:00:00Z (one-day unopened shelf life); with the
    clock at 2026-09-03 the physical units exist but the pool is empty, so the order
    is SHORTED with qty_allocated 0.

    Design: Corner/calculations/expired_lot_excluded_from_allocation_pool
    """
    net = setup_active_distributor()
    product = create_product(code="P1", name="Item", shelf_life_unopened_days=1)
    supply = setup_lot(product, actual_units=10)
    order = create_order(net["distributor"], [(product["id"], 10)])
    set_clock("2026-09-03T00:00:00Z")
    allocate_week(supply["plant"])
    order = get_order(order["id"])
    assert order["allocation_status"] == "SHORTED", (
        "expired lots are excluded from the pool even though units physically exist"
    )
    lines, _m = validate_paginated(api.list_order_lines(
        ADMIN, params={"order_id": order["id"]}))
    assert sum(ln["qty_allocated"] for ln in lines) == 0


def test_allocate_week_response_carries_processed_orders(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field." and
    PRD §3.3: "Each processed order's `version` increments."

    The bulk allocation response itself carries the processed order with its final
    status and pricing written — 10 units at 500 cents -> merchandise 5000, fee 1500,
    total 6500 — no re-read needed (immediate consistency).

    Design: Corner/endpoints/allocate_week_returns_processed_orders
    """
    net = setup_active_distributor()
    product = create_product(code="P1", name="Item", base_price_cents=500)
    supply = setup_lot(product, actual_units=10)
    order = create_order(net["distributor"], [(product["id"], 10)])
    resp = api.allocate_week(
        "2026-09-07", make_plant_scheduler_headers(supply["plant"]["id"]))
    processed = validate_success(resp)
    assert isinstance(processed, list) and len(processed) == 1
    first = processed[0]
    assert first["id"] == order["id"]
    assert first["allocation_status"] == "ALLOCATED", (
        "the response body itself reflects the mutation"
    )
    assert first["merchandise_total_cents"] == 5000
    assert first["total_cents"] == 6500


def test_orders_list_filters_by_distributor(api):
    """PRD §4: the orders list supports filters `distributor_id`, `delivery_week`,
    `allocation_status`, `fulfillment_status` ("List orders; filters
    `distributor_id`, `delivery_week`, `allocation_status`, `fulfillment_status`").

    The `distributor_id` filter isolates one distributor's orders from another's:
    exactly the five-unit order of the first distributor is returned.

    Design: Corner/endpoints/orders_filtered_by_distributor
    """
    net_1 = setup_active_distributor()
    net_2 = setup_active_distributor()
    product = create_product(code="P1", name="Item")
    order_1 = create_order(net_1["distributor"], [(product["id"], 5)])
    order_2 = create_order(net_2["distributor"], [(product["id"], 7)])
    data, meta = validate_paginated(api.list_orders(
        ADMIN, params={"distributor_id": net_1["distributor"]["id"]}))
    ids = {o["id"] for o in data}
    assert order_1["id"] in ids and order_2["id"] not in ids
    assert meta["total_count"] == 1


def test_order_line_shape_has_no_version_and_price_snapshot(api):
    """PRD §2.4: "Three resource types are deliberately lighter: an order line, a
    lot, and a training certification each carry only `id` and `created_at`." and
    "For those three, both `updated_at` and `version` are absent, and no client may
    rely on them." PRD §3.3: "At creation, each line snapshots `unit_price_cents`
    from its product's current `base_price_cents`, so later catalog price changes
    never rewrite an in-flight order; the line's `qty_allocated` starts at zero."

    Design: Corner/entities/orderline_immutable_shape_no_version
    """
    net = setup_active_distributor()
    product = create_product(code="P1", name="Item", base_price_cents=500)
    order = create_order(net["distributor"], [(product["id"], 5)])
    data, _meta = validate_paginated(api.list_order_lines(
        ADMIN, params={"order_id": order["id"]}))
    assert len(data) == 1
    line = data[0]
    assert_order_line(line)  # asserts id + created_at present, updated_at/version absent
    assert line["unit_price_cents"] == 500, "price snapshot taken at order creation"
    assert line["qty_allocated"] == 0
    assert line["qty_requested"] == 5
    order = get_order(order["id"])
    assert order["allocation_status"] == "PENDING"
    assert order["fulfillment_status"] == "UNSHIPPED"
