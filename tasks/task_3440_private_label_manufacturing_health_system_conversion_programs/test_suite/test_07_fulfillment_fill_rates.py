"""Fulfillment events, dual-variant fill rates, rolling window, breach cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_distribution_order,
    create_inventory_program,
    create_product,
    find_order,
    find_position,
    get_agreement,
    get_inventory_program,
    make_facility_director_headers,
    place_order,
    receive_order,
    set_clock,
    setup_facility_with_agreement,
    ship_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_order_receive_from_placed_409(api):
    """PRD §3.6: "A `RECEIVED` event is valid from `SHIPPED` or
    `PARTIALLY_SHIPPED`; sent against a `PLACED` order it is rejected with
    `ERR_ORDER_NOT_RECEIVABLE` (HTTP 409) because nothing has shipped".
    PRD §3.5: "leaves `provisional_fill_rate_pct`, `final_fill_rate_pct`, and
    `received_at` null until fulfillment events supply them."

    Design: Corner/state_machines/order_receive_from_placed_rejected
    """
    ctx = setup_facility_with_agreement(committed_fill_rate_pct=90.0)
    order = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 10}],
    )
    resp = api.record_fulfillment_event(
        order["id"], {"event": "RECEIVED", "shipped_lines": []}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_RECEIVABLE.value, 409)
    orders, _ = validate_paginated(
        api.list_agreement_orders(ctx["agreement"]["id"], ADMIN)
    )
    current = find_order(orders, order["id"])
    assert current["status"] == "PLACED"
    assert current.get("final_fill_rate_pct") is None


def test_receive_counts_open_shortfall_against_fill(api):
    """PRD §3.6: "Receiving from `PARTIALLY_SHIPPED` is explicitly allowed with
    open lines: units neither shipped nor backorder-cancelled stay in the final
    rate's denominator, so the shortfall counts against the facility-facing
    rate". 40 shipped of 100 ordered, nothing cancelled: final == 40.00.

    Design: Corner/state_machines/order_receive_counts_open_shortfall_against_fill
    """
    ctx = setup_facility_with_agreement(committed_fill_rate_pct=90.0)
    order = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 100}],
    )
    shipped = ship_order(
        order["id"],
        [{"product_id": ctx["product"]["id"], "shipped_qty": 40,
          "backorder_cancelled": False}],
    )
    assert shipped["status"] == "PARTIALLY_SHIPPED"
    assert shipped["provisional_fill_rate_pct"] == 40.00
    received = receive_order(order["id"])
    assert received["status"] == "RECEIVED"
    assert received["final_fill_rate_pct"] == 40.00


def test_over_shipment_422(api):
    """PRD §3.6: "the cumulative `shipped_qty` on a line across all events may
    never exceed that line's `ordered_qty` (otherwise `ERR_OVER_SHIPMENT`,
    HTTP 422)". 60 then 50 against 100 ordered fails on the second event.

    Design: Corner/validations/over_shipment_rejected
    """
    ctx = setup_facility_with_agreement(committed_fill_rate_pct=90.0)
    order = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 100}],
    )
    ship_order(
        order["id"],
        [{"product_id": ctx["product"]["id"], "shipped_qty": 60,
          "backorder_cancelled": False}],
    )
    resp = api.record_fulfillment_event(
        order["id"],
        {"event": "SHIPPED", "shipped_lines": [
            {"product_id": ctx["product"]["id"], "shipped_qty": 50,
             "backorder_cancelled": False}
        ]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_OVER_SHIPMENT.value, 422)
    orders, _ = validate_paginated(
        api.list_agreement_orders(ctx["agreement"]["id"], ADMIN)
    )
    current = find_order(orders, order["id"])
    assert current["status"] == "PARTIALLY_SHIPPED"
    assert current["lines"][0]["shipped_qty"] == 60


def test_rolling_input_set_excludes_unreceived(api):
    """PRD §3.6: "counting only this agreement's orders in `RECEIVED` status
    whose `received_at` falls inside that window; `PLACED`, `PARTIALLY_SHIPPED`,
    and `SHIPPED` orders never contribute." A shipped-but-unreceived order
    leaves `rolling_fill_rate_pct` and `spent_cents` untouched.

    Design: Corner/calculations/rolling_input_set_excludes_unreceived
    """
    ctx = setup_facility_with_agreement(committed_fill_rate_pct=90.0)
    o1 = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 100}],
        requested_delivery_date="2026-09-10",
    )
    ship_order(o1["id"], [{"product_id": ctx["product"]["id"],
                           "shipped_qty": 100, "backorder_cancelled": False}])
    receive_order(o1["id"])
    o2 = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 100}],
        requested_delivery_date="2026-09-12",
    )
    ship_order(o2["id"], [{"product_id": ctx["product"]["id"],
                           "shipped_qty": 50, "backorder_cancelled": False}])
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["rolling_fill_rate_pct"] == 100.00
    assert agreement["spent_cents"] == 10000


def test_rolling_window_excludes_stale_orders(api):
    """PRD §3.6: "`rolling_fill_rate_pct` is recomputed over the trailing
    ninety-day window — from ninety days before the current logical clock
    through the current clock, both ends inclusive". PRD §3.6: "While
    `SUSPENDED`, a recomputed rate greater than or equal to the commitment
    recovers the agreement to `ACTIVE` with the same version arithmetic,
    restoring `auto_replenish_enabled` to true on each of the facility's
    programs."

    Design: Corner/calculations/rolling_window_excludes_stale_orders
    """
    ctx = setup_facility_with_agreement(
        committed_fill_rate_pct=90.0,
        agreement_overrides={"start_date": "2026-01-01", "end_date": "2027-08-31"},
    )
    facility, product, agreement = (
        ctx["facility"], ctx["product"], ctx["agreement"]
    )
    program = create_inventory_program(
        facility["id"],
        [{"product_id": product["id"], "par_level": 50, "reorder_point": 10,
          "on_hand": 5}],
    )
    assert program["auto_replenish_enabled"] is True
    o1 = place_order(agreement["id"], facility["id"],
                     [{"product_id": product["id"], "ordered_qty": 100}],
                     requested_delivery_date="2026-09-10")
    o2 = place_order(agreement["id"], facility["id"],
                     [{"product_id": product["id"], "ordered_qty": 50}],
                     requested_delivery_date="2026-09-11")
    o3 = place_order(agreement["id"], facility["id"],
                     [{"product_id": product["id"], "ordered_qty": 50}],
                     requested_delivery_date="2026-12-10")
    ship_order(o1["id"], [{"product_id": product["id"], "shipped_qty": 60,
                           "backorder_cancelled": False}])
    receive_order(o1["id"])
    mid1 = get_agreement(agreement["id"])
    assert mid1["rolling_fill_rate_pct"] == 60.00
    assert mid1["status"] == "SUSPENDED"
    ship_order(o2["id"], [{"product_id": product["id"], "shipped_qty": 50,
                           "backorder_cancelled": False}])
    receive_order(o2["id"])
    mid2 = get_agreement(agreement["id"])
    assert mid2["rolling_fill_rate_pct"] == 73.33  # (60+50)/150
    assert mid2["status"] == "SUSPENDED"
    assert get_inventory_program(program["id"])["auto_replenish_enabled"] is False
    # Advance 96 days: the 2026-09-01 receipts fall outside the trailing
    # 90-day window [2026-09-07, 2026-12-06].
    set_clock("2026-12-06T00:00:00Z")
    ship_order(o3["id"], [{"product_id": product["id"], "shipped_qty": 50,
                           "backorder_cancelled": False}])
    receive_order(o3["id"])
    final = get_agreement(agreement["id"])
    assert final["rolling_fill_rate_pct"] == 100.00  # NOT 80.00 (stale O1)
    assert final["status"] == "ACTIVE"
    assert get_inventory_program(program["id"])["auto_replenish_enabled"] is True


def test_fill_rate_provisional_after_shipped(api):
    """PRD §3.6: "The **provisional** variant, computed on every `SHIPPED` event
    while the order is `PLACED` or `PARTIALLY_SHIPPED`, divides total shipped
    units across all lines by total ordered units across all lines, multiplies
    by 100, and rounds half up to 2 decimal places; cancelled-but-never-shipped
    units count against the rate". (90+50)/150 -> 93.33.

    Design: Difficulty/dual_variant_calc/fill_rate_provisional_undercuts_final_on_cancelled_units
    """
    ctx = setup_facility_with_agreement(
        committed_fill_rate_pct=95.0, lum_commitment=True
    )
    p1 = ctx["product"]
    p2 = create_product(sku="P-200")
    order = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": p1["id"], "ordered_qty": 100},
         {"product_id": p2["id"], "ordered_qty": 50}],
    )
    shipped = ship_order(
        order["id"],
        [{"product_id": p1["id"], "shipped_qty": 90, "backorder_cancelled": True},
         {"product_id": p2["id"], "shipped_qty": 50, "backorder_cancelled": False}],
    )
    assert_distribution_order(shipped)
    assert shipped["status"] == "SHIPPED"
    assert shipped["provisional_fill_rate_pct"] == 93.33


def test_fill_rate_final_after_received(api):
    """PRD §3.6: "The **final** variant, computed on the `RECEIVED` event,
    divides total shipped units by the units the facility still wanted — total
    ordered minus the units on backorder-cancelled lines". (90+50)/(150-10) ->
    100.00, and the agreement's trailing rate reflects the single RECEIVED
    order (100.00 >= 95.0, no breach).

    Design: Difficulty/dual_variant_calc/fill_rate_provisional_undercuts_final_on_cancelled_units
    """
    ctx = setup_facility_with_agreement(
        committed_fill_rate_pct=95.0, lum_commitment=True
    )
    p1 = ctx["product"]
    p2 = create_product(sku="P-201")
    order = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": p1["id"], "ordered_qty": 100},
         {"product_id": p2["id"], "ordered_qty": 50}],
    )
    shipped = ship_order(
        order["id"],
        [{"product_id": p1["id"], "shipped_qty": 90, "backorder_cancelled": True},
         {"product_id": p2["id"], "shipped_qty": 50, "backorder_cancelled": False}],
    )
    assert shipped["provisional_fill_rate_pct"] == 93.33
    received = receive_order(order["id"])
    assert received["status"] == "RECEIVED"
    assert received["final_fill_rate_pct"] == 100.00
    assert received["final_fill_rate_pct"] != received["provisional_fill_rate_pct"]
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["rolling_fill_rate_pct"] == 100.00
    assert agreement["status"] == "ACTIVE"


def test_fill_rate_equality_is_compliant(api):
    """PRD §3.6: "a recomputed rolling rate strictly below
    `committed_fill_rate_pct` — equality is compliant — suspends the
    agreement". 190/200 -> 95.00, exactly the 95.0 commitment: still ACTIVE.

    Design: Difficulty/boundary_precision_check/fill_rate_exactly_committed_is_compliant
    """
    ctx = setup_facility_with_agreement(committed_fill_rate_pct=95.0)
    order = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 200}],
        requested_delivery_date="2026-09-10",
    )
    ship_order(order["id"], [{"product_id": ctx["product"]["id"],
                              "shipped_qty": 190, "backorder_cancelled": False}])
    received = receive_order(order["id"])
    # Open 10-unit shortfall counts against: 190/200 = 95.00.
    assert received["final_fill_rate_pct"] == 95.00
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["rolling_fill_rate_pct"] == 95.00
    assert agreement["status"] == "ACTIVE"


def test_fill_rate_below_committed_suspends(api):
    """PRD §3.6: "The rolling rate is a unit-weighted aggregate: total shipped
    units across those eligible orders divided by total still-wanted units
    (ordered minus cancelled) across the same orders, times 100, rounded half
    up to 2 decimals". After a second receipt of 949/1000 the aggregate is
    1139/1200 = 94.9166.. -> 94.92 < 95.0, so the agreement suspends.

    Design: Difficulty/boundary_precision_check/fill_rate_exactly_committed_is_compliant
    """
    ctx = setup_facility_with_agreement(committed_fill_rate_pct=95.0)
    order_a = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 200}],
        requested_delivery_date="2026-09-10",
    )
    ship_order(order_a["id"], [{"product_id": ctx["product"]["id"],
                                "shipped_qty": 190, "backorder_cancelled": False}])
    receive_order(order_a["id"])
    assert get_agreement(ctx["agreement"]["id"])["status"] == "ACTIVE"
    order_b = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 1000}],
        requested_delivery_date="2026-09-18",
    )
    ship_order(order_b["id"], [{"product_id": ctx["product"]["id"],
                                "shipped_qty": 949, "backorder_cancelled": False}])
    received_b = receive_order(order_b["id"])
    assert received_b["final_fill_rate_pct"] == 94.90
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["rolling_fill_rate_pct"] == 94.92
    assert agreement["status"] == "SUSPENDED"


def test_receive_breach_suspends_agreement(api):
    """PRD §3.6: "Otherwise the agreement's `spent_cents` grows by the order's
    `total_price_cents` and `rolling_fill_rate_pct` is recomputed over the
    trailing ninety-day window". PRD §3.6: "While the agreement is `ACTIVE`, a
    recomputed rolling rate strictly below `committed_fill_rate_pct` — equality
    is compliant — suspends the agreement". O2 ships 170 of 200 with no
    cancellation, so the open 30-unit shortfall stays in the final denominator:
    final 170/200 = 85.00; rolling (100+170)/(100+200) = 90.00 < 95.0.

    Design: Difficulty/transitive_cascade/receive_breach_cascades_suspend_and_mutes_programs
    """
    ctx = setup_facility_with_agreement(committed_fill_rate_pct=95.0)
    o1 = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 100}],
        requested_delivery_date="2026-09-10",
    )
    ship_order(o1["id"], [{"product_id": ctx["product"]["id"],
                           "shipped_qty": 100, "backorder_cancelled": False}])
    receive_order(o1["id"])
    o2 = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 200}],
        requested_delivery_date="2026-09-16",
    )
    ship_order(o2["id"], [{"product_id": ctx["product"]["id"],
                           "shipped_qty": 170, "backorder_cancelled": False}])
    received = receive_order(o2["id"])
    assert received["final_fill_rate_pct"] == 85.00
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["rolling_fill_rate_pct"] == 90.00
    assert agreement["spent_cents"] == 30000
    assert agreement["status"] == "SUSPENDED"


def test_breach_mutes_inventory_program(api):
    """PRD §3.6: "every `InventoryProgram` whose `facility_id` matches the
    agreement's facility has `auto_replenish_enabled` forced to false, each
    cascaded program's `version` incrementing by 1." PRD §3.9: "when
    `auto_replenish_enabled` is false the `suggested_order_qty` is 0 regardless
    of need".

    Design: Difficulty/transitive_cascade/receive_breach_cascades_suspend_and_mutes_programs
    """
    ctx = setup_facility_with_agreement(committed_fill_rate_pct=95.0)
    program = create_inventory_program(
        ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "par_level": 50,
          "reorder_point": 10, "on_hand": 5}],
    )
    # Before any order exists the pipeline is 0: max(0, 50-5-0) = 45.
    before = get_inventory_program(program["id"])
    assert find_position(before, ctx["product"]["id"])["suggested_order_qty"] == 45
    o1 = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 100}],
        requested_delivery_date="2026-09-10",
    )
    ship_order(o1["id"], [{"product_id": ctx["product"]["id"],
                           "shipped_qty": 100, "backorder_cancelled": False}])
    receive_order(o1["id"])
    o2 = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 200}],
        requested_delivery_date="2026-09-16",
    )
    ship_order(o2["id"], [{"product_id": ctx["product"]["id"],
                           "shipped_qty": 170, "backorder_cancelled": False}])
    receive_order(o2["id"])
    assert get_agreement(ctx["agreement"]["id"])["status"] == "SUSPENDED"
    after = get_inventory_program(program["id"])
    assert after["auto_replenish_enabled"] is False
    assert find_position(after, ctx["product"]["id"])["suggested_order_qty"] == 0
    assert after["version"] == 2  # one cascade flip on top of creation
