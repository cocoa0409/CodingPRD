"""Cart-line admission: the ceilings that guard a hold, and the ledgers a hold moves."""

from test_helpers import (
    MERCHANDISER,
    ApiErrorId,
    DEFAULT_PRODUCT,
    abandon_cart,
    activate_offer,
    add_cart_item_payload,
    add_channel,
    add_line,
    add_offer_target,
    adjust_inventory,
    api_client,
    assert_both_ledgers_conserved,
    assert_cart,
    assert_cart_item,
    assert_flash_offer,
    assert_inventory_pool_conserved,
    book_host,
    build_scenario,
    cancel_order,
    cart_version,
    checkout,
    confirm_booking,
    create_offer,
    create_product,
    create_show,
    create_slot,
    create_substantiated_product,
    go_live,
    inventory_adjustment_payload,
    live_show_with_active_offer,
    make_viewer_headers,
    provision_channel,
    read_cart,
    read_line,
    read_offer,
    read_product,
    read_slot,
    ready_show,
    recover_cart,
    register_certified_host,
    report_health,
    validate_error,
)


def _second_live_broadcast():
    """An independent live broadcast with its own host, product and active offer.

    Built entirely from the public API so the returned offer belongs to a show
    that is not the one the caller's cart was opened on.
    """
    host = register_certified_host()
    product = create_substantiated_product(
        evidence_ref="LAB-90",
        title="Porcelain Vase",
        base_price_cents=6000,
        unit_cost_cents=2000,
        on_hand_qty=30,
    )
    show = create_show(title="Porcelain Monday")
    booking = book_host(show["id"], host["id"])
    confirm_booking(booking["id"], host["id"])
    slot = create_slot(show["id"], product["id"])
    offer = create_offer(slot["id"], offer_price_cents=3000)
    channel = add_channel(show["id"])
    provision_channel(channel["id"])
    report_health(channel["id"], 1500, 0.0)
    ready_show(show["id"])
    go_live(show["id"])
    offer = activate_offer(offer["id"])
    return {"show": show, "product": product, "slot": slot, "offer": offer}


def test_add_line_above_the_offer_remainder_is_refused_then_the_exact_remainder_is_taken():
    """A hold for more units than the flash offer still has left is refused, while a
    hold for exactly the remaining allotment is accepted and exhausts the offer.

    PRD 3.6: "the offer's `remaining_qty` must be at least the requested `qty`
    (`ERR_OFFER_QTY_EXCEEDED`)". PRD 3.6 on the accepted hold: "the offer's
    `held_qty` is increased by the same `qty` and `remaining_qty` is recomputed;
    and if `remaining_qty` has reached 0 the offer moves `ACTIVE → EXHAUSTED`".

    Design: Corner/validations/add_item_above_offer_remaining_rejected_then_exact_remainder_accepted
    """
    scenario = live_show_with_active_offer(num_carts=1)
    viewer_headers = make_viewer_headers(scenario.viewer_id)

    over_the_allotment = api_client.add_cart_item(
        scenario.cart_id,
        add_cart_item_payload(scenario.offer_id, 11),
        viewer_headers,
    )
    validate_error(over_the_allotment, ApiErrorId.ERR_OFFER_QTY_EXCEEDED)

    untouched_offer = read_offer(scenario.offer_id)
    assert untouched_offer["held_qty"] == 0, "a refused hold must not take allotment"
    assert untouched_offer["remaining_qty"] == 10, "the whole allotment is still on offer"
    assert untouched_offer["status"] == "ACTIVE", "a refused hold leaves the offer purchasable"
    untouched_product = read_product(scenario.product_id)
    assert untouched_product["reserved_qty"] == 0, "a refused hold reserves no stock"
    assert read_cart(scenario.cart_id, scenario.viewer_id)["held_item_count"] == 0

    line = add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 10)
    assert_cart_item(line)
    assert line["state"] == "HELD", "the whole remaining allotment is holdable"
    assert line["qty"] == 10
    assert line["offer_unit_price_cents"] == 3500, "the line freezes the offer price"
    assert line["effective_unit_price_cents"] == 3150, (
        "a 35000 cent subtotal takes the upper bundle tier of 0.10, so 3500 becomes 3150"
    )
    assert line["line_gross_cents"] == 31500, "3150 cents times ten units"
    assert line["line_tax_cents"] == 2756, "31500 cents at 8.75 percent, rounded half up"

    offer = read_offer(scenario.offer_id)
    assert_flash_offer(offer)
    assert offer["held_qty"] == 10, "every unit of the allotment is now held"
    assert offer["remaining_qty"] == 0, "the allotment is spent"
    assert offer["status"] == "EXHAUSTED", "an allotment driven to zero exhausts the offer"
    product = read_product(scenario.product_id)
    assert product["reserved_qty"] == 10, "the hold reserved ten physical units"
    assert product["available_qty"] == 40, "fifty on hand less ten reserved"
    assert_both_ledgers_conserved(product, offer)


def test_add_line_above_available_inventory_is_refused_then_the_exact_stock_is_taken():
    """A hold for more units than the product physically has free is refused even
    though the offer's allotment would allow it, and a hold for exactly the free
    stock is accepted.

    PRD 3.6: "the product's `available_qty` must be at least the requested `qty`
    (`ERR_INSUFFICIENT_INVENTORY`)". PRD 2.7 pins which of the two ceilings
    speaks: "an add that would clear the offer's allotment but exceed the
    product's free units is rejected with `ERR_INSUFFICIENT_INVENTORY`, not with
    `ERR_OFFER_QTY_EXCEEDED`".

    Design: Corner/validations/add_item_above_available_inventory_rejected_then_exact_stock_accepted
    """
    scenario = build_scenario(
        products=[dict(DEFAULT_PRODUCT, on_hand_qty=2, unit_cost_cents=800)],
        offers=[{"offer_price_cents": 1000, "max_qty": 10}],
        take_live=True,
        activate=True,
        num_carts=1,
    )
    viewer_headers = make_viewer_headers(scenario.viewer_id)

    beyond_stock = api_client.add_cart_item(
        scenario.cart_id,
        add_cart_item_payload(scenario.offer_id, 3),
        viewer_headers,
    )
    validate_error(beyond_stock, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)

    product = read_product(scenario.product_id)
    assert product["available_qty"] == 2, "a refused hold leaves the pool untouched"
    assert product["reserved_qty"] == 0
    offer = read_offer(scenario.offer_id)
    assert offer["held_qty"] == 0, "the allotment is untouched even though it had room"
    assert offer["remaining_qty"] == 10

    line = add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 2)
    assert line["state"] == "HELD", "the last free units are holdable"
    assert line["qty"] == 2
    assert line["effective_unit_price_cents"] == 1000, (
        "a 2000 cent subtotal is below the lower bundle floor, so no discount applies"
    )
    assert line["line_gross_cents"] == 2000
    assert line["line_tax_cents"] == 175, "2000 cents at 8.75 percent"

    product = read_product(scenario.product_id)
    assert product["reserved_qty"] == 2, "both free units are now reserved"
    assert product["available_qty"] == 0, "nothing is left in circulation"
    offer = read_offer(scenario.offer_id)
    assert offer["held_qty"] == 2
    assert offer["remaining_qty"] == 8, "allotment still stands even with no stock behind it"
    assert offer["status"] == "ACTIVE", "an offer with allotment left is not exhausted"
    assert_both_ledgers_conserved(product, offer)


def test_a_fourth_distinct_held_line_is_refused_by_the_cart_line_ceiling():
    """A cart may carry three held lines; a fourth distinct line is refused, and the
    three lines that were admitted keep the price each locked at its own add time.

    PRD 3.6 requires the cart to hold fewer than three lines in state HELD, "so a
    fourth distinct line is refused with `ERR_CART_ITEM_LIMIT`". PRD 3.6 on the
    locked price: "a later add that lifts the cart into a higher tier does not
    reprice the earlier lines".

    Design: Corner/validations/fourth_distinct_held_line_rejected_by_cart_item_limit
    """
    # PRD 3.2/3.1: the lineup is assembled while the show is still DRAFT — a show
    # that has left DRAFT and READY behind refuses lineup mutation — so all four
    # products, slots and offers are built before the broadcast goes to air.
    accessories = [
        {
            "title": f"Silk Accessory {index}",
            "base_price_cents": 2500,
            "unit_cost_cents": 800,
            "on_hand_qty": 30,
            "evidence_ref": evidence,
        }
        for index, evidence in enumerate(("LAB-89", "LAB-90", "LAB-91"), start=2)
    ]
    scenario = build_scenario(
        num_carts=1,
        take_live=True,
        activate=True,
        products=[dict(DEFAULT_PRODUCT)] + accessories,
        slots=[
            {
                "slot_sequence": index + 1,
                "product_index": index,
                "planned_start_at": "2026-08-10T18:05:00Z",
                "planned_end_at": "2026-08-10T18:35:00Z",
                "planned_qty": 20,
            }
            for index in range(4)
        ],
        offers=[
            {
                "slot_index": index,
                "offer_price_cents": 3500 if index == 0 else 1000,
                "window_start_at": "2026-08-10T18:00:00Z",
                "window_end_at": "2026-08-10T19:00:00Z",
                "max_qty": 10,
            }
            for index in range(4)
        ],
    )

    first = add_line(scenario.cart_id, scenario.offers[0]["id"], scenario.viewer_id, 1)
    second = add_line(scenario.cart_id, scenario.offers[1]["id"], scenario.viewer_id, 1)
    third = add_line(scenario.cart_id, scenario.offers[2]["id"], scenario.viewer_id, 1)

    assert first["effective_unit_price_cents"] == 3500, (
        "the first line locked at a 3500 cent subtotal, below the lower bundle floor"
    )
    assert second["effective_unit_price_cents"] == 1000, (
        "the second line locked at a 4500 cent subtotal, still below the floor"
    )
    assert third["effective_unit_price_cents"] == 950, (
        "the third line locked at a 5500 cent subtotal, which takes the 0.05 tier"
    )

    fourth = api_client.add_cart_item(
        scenario.cart_id,
        add_cart_item_payload(scenario.offers[3]["id"], 1),
        make_viewer_headers(scenario.viewer_id),
    )
    validate_error(fourth, ApiErrorId.ERR_CART_ITEM_LIMIT)

    cart = read_cart(scenario.cart_id, scenario.viewer_id)
    assert_cart(cart)
    assert cart["held_item_count"] == 3, "the refused line was never admitted"
    assert cart["pre_discount_subtotal_cents"] == 5500, "3500 plus 1000 plus 1000"
    assert cart["bundle_discount_pct"] == 0.05, "the subtotal sits in the lower tier"
    assert read_line(first["id"])["effective_unit_price_cents"] == 3500, (
        "an earlier line is never repriced by a later add"
    )

    fourth_offer = read_offer(scenario.offers[3]["id"])
    assert fourth_offer["held_qty"] == 0, "the refused line took no allotment"
    assert fourth_offer["remaining_qty"] == 10
    assert read_product(scenario.products[3]["id"])["reserved_qty"] == 0, (
        "the refused line reserved no stock"
    )


def test_add_line_naming_an_offer_from_another_live_show_is_refused():
    """A viewer shopping one broadcast cannot hold a unit of an offer that belongs,
    through its lineup slot, to a different broadcast.

    PRD 3.6: "the offer's lineup slot must belong, through its `show_id`, to the
    same show as the cart (`ERR_OFFER_SHOW_MISMATCH`)".

    Design: Corner/validations/add_item_with_an_offer_from_another_live_show_rejected
    """
    scenario = live_show_with_active_offer(num_carts=1)
    other = _second_live_broadcast()

    mismatched = api_client.add_cart_item(
        scenario.cart_id,
        add_cart_item_payload(other["offer"]["id"], 1),
        make_viewer_headers(scenario.viewer_id),
    )
    validate_error(mismatched, ApiErrorId.ERR_OFFER_SHOW_MISMATCH)

    cart = read_cart(scenario.cart_id, scenario.viewer_id)
    assert cart["held_item_count"] == 0, "nothing was held into the mismatched cart"
    assert cart["pre_discount_subtotal_cents"] == 0

    foreign_offer = read_offer(other["offer"]["id"])
    assert foreign_offer["held_qty"] == 0, "the other show's allotment is untouched"
    assert foreign_offer["remaining_qty"] == 10
    assert foreign_offer["status"] == "ACTIVE"
    assert read_product(other["product"]["id"])["reserved_qty"] == 0, (
        "the other show's stock is untouched"
    )
    own_offer = read_offer(scenario.offer_id)
    assert own_offer["held_qty"] == 0, "the cart's own offer is untouched as well"


def test_cart_version_advances_once_per_accepted_write_and_not_at_all_on_a_refusal():
    """Each accepted write against a cart advances its version by exactly one, while
    a refused write leaves the version where it was.

    PRD 2.4: "`version` is an integer that starts at `1` when the row is created
    and increments by exactly `1` on every mutation of that row, including
    mutations the row suffers as a side effect of an operation performed on a
    different resource." A refused request mutates nothing: PRD 3.6 moves the
    ledgers and increments the cart only "After the line is priced", and PRD 2.7
    stops at "the first check that fails decides the response entirely".

    Design: Corner/cross_cutting_complexity_layers/cart_version_increments_on_every_accepted_write_only
    """
    scenario = live_show_with_active_offer(num_carts=1)
    cart_id = scenario.cart_id
    viewer_id = scenario.viewer_id

    opened_version = cart_version(cart_id, viewer_id)

    add_line(cart_id, scenario.offer_id, viewer_id, 2)
    after_hold = cart_version(cart_id, viewer_id)
    assert after_hold == opened_version + 1, "an accepted hold advances the cart once"

    refused = api_client.add_cart_item(
        cart_id,
        add_cart_item_payload(scenario.offer_id, 11),
        make_viewer_headers(viewer_id),
    )
    validate_error(refused, ApiErrorId.ERR_OFFER_QTY_EXCEEDED)
    assert cart_version(cart_id, viewer_id) == after_hold, (
        "a refused hold must not advance the cart's version"
    )

    abandon_cart(cart_id, viewer_id)
    after_abandon = cart_version(cart_id, viewer_id)
    assert after_abandon == after_hold + 1, "abandonment advances the cart once"

    recover_cart(cart_id, viewer_id)
    after_recovery = cart_version(cart_id, viewer_id)
    assert after_recovery == after_abandon + 1, "recovery advances the cart once"

    cart = read_cart(cart_id, viewer_id)
    assert cart["status"] == "OPEN", "the recovered cart is open for business again"
    assert cart["recovered_count"] == 1, "one completed abandonment and recovery loop"
    assert cart["held_item_count"] == 1, "the released line came back as a hold"
    assert cart["pre_discount_subtotal_cents"] == 7000, "two units at the 3500 cent offer price"
    assert cart["abandoned_at"] is None, "recovery clears the abandonment stamp"
    assert cart["recovery_deadline_at"] is None, "recovery clears the deadline"


def test_the_product_pool_reconciles_across_hold_adjustment_commitment_and_release():
    """One product's four inventory numbers stay reconciled while a hold reserves
    units, an adjustment revises stock beneath them, checkout commits them
    sideways and an order cancellation gives them back.

    PRD 2.10 states the physical invariant: "`on_hand_qty` always equals
    `available_qty` plus `reserved_qty` plus `committed_qty`". PRD 2.10 on the
    adjustment: "It moves `available_qty` with it and never touches `reserved_qty`
    or `committed_qty`".
    PRD 3.7 on the commitment: "the product's `reserved_qty` is decreased by that
    line's `qty` and its `committed_qty` increased by the same amount — so
    `available_qty` is unchanged, because the units were already out of
    circulation".

    Design: Corner/cross_cutting_complexity_layers/product_available_qty_reconciles_across_hold_adjustment_commit_and_release
    """
    scenario = live_show_with_active_offer(num_carts=1)
    product_id = scenario.product_id
    offer_id = scenario.offer_id

    line = add_line(scenario.cart_id, offer_id, scenario.viewer_id, 2)
    held = read_product(product_id)
    assert (held["on_hand_qty"], held["reserved_qty"], held["committed_qty"], held["available_qty"]) == (
        50,
        2,
        0,
        48,
    ), "a hold moves units from available to reserved and leaves on_hand alone"
    assert_inventory_pool_conserved(held)

    adjusted = adjust_inventory(product_id, on_hand_delta=-8, reason="DAMAGE_WRITE_OFF")
    assert (adjusted["on_hand_qty"], adjusted["reserved_qty"], adjusted["committed_qty"], adjusted["available_qty"]) == (
        42,
        2,
        0,
        40,
    ), "an adjustment moves on_hand and available together, never the reservation"
    assert_inventory_pool_conserved(adjusted)

    order = checkout(scenario.cart_id, scenario.viewer_id)
    committed = read_product(product_id)
    assert (committed["on_hand_qty"], committed["reserved_qty"], committed["committed_qty"], committed["available_qty"]) == (
        42,
        0,
        2,
        40,
    ), "checkout shifts reserved to committed sideways, leaving available alone"
    assert_inventory_pool_conserved(committed)
    sold_offer = read_offer(offer_id)
    assert sold_offer["held_qty"] == 0 and sold_offer["sold_qty"] == 2, (
        "the allotment moves from held to sold"
    )
    assert sold_offer["remaining_qty"] == 8, "a commitment leaves remaining allotment alone"
    assert order["merchandise_cents"] == 6650, "two units at 3325 after the 0.05 bundle tier"
    assert order["tax_cents"] == 582, "6650 cents at 8.75 percent, rounded half up per line"
    assert order["shipping_cents"] == 599, "merchandise below 7500 cents pays flat shipping"
    assert order["total_cents"] == 7831, "6650 plus 582 plus 599"

    cancel_order(order["id"], cancel_reason="VIEWER_CHANGED_MIND")
    released = read_product(product_id)
    assert (released["on_hand_qty"], released["reserved_qty"], released["committed_qty"], released["available_qty"]) == (
        42,
        0,
        0,
        42,
    ), "cancellation returns the committed units to circulation"
    assert_inventory_pool_conserved(released)
    restocked = read_offer(offer_id)
    assert restocked["sold_qty"] == 0 and restocked["remaining_qty"] == 10, (
        "the cancelled units go back into the allotment"
    )
    assert_both_ledgers_conserved(released, restocked)
    assert read_line(line["id"])["state"] == "RELEASED", "the committed line is released"
    assert read_line(line["id"])["released_reason"] == "ORDER_CANCELLED"


def test_an_inventory_adjustment_revises_landed_cost_and_refuses_to_drive_stock_negative():
    """An adjustment carrying a new landed cost rewrites the product's cost without
    disturbing the cost already frozen on a lineup slot, and an adjustment that
    would drive free stock below zero is refused outright.

    PRD 3.2: "Supplying `unit_cost_cents` replaces the product's current landed
    cost — this is the post-show cost revision that the final margin variant reads
    —" and it deliberately does not touch "the `unit_cost_snapshot_cents` already
    recorded on any lineup slot". PRD 3.2 also fixes the floor: "An adjustment that
    would push `available_qty` below zero is refused with
    `ERR_INSUFFICIENT_INVENTORY`; an adjustment never moves `reserved_qty` or
    `committed_qty`."

    Design: Corner/endpoints/inventory_adjustment_revises_cost_and_rejects_negative_available
    """
    product = create_product(
        sku="SKU-ROBE",
        title="Silk Wrap Robe",
        base_price_cents=4000,
        unit_cost_cents=1500,
        on_hand_qty=50,
    )
    show = create_show()
    slot = create_slot(show["id"], product["id"])
    assert slot["unit_cost_snapshot_cents"] == 1500, "the slot froze the cost at creation"

    revised = adjust_inventory(
        product["id"], on_hand_delta=5, unit_cost_cents=1700, reason="RESTOCK_AND_COST_REVISION"
    )
    assert revised["on_hand_qty"] == 55, "fifty units plus five"
    assert revised["available_qty"] == 55, "nothing is reserved or committed, so all are free"
    assert revised["reserved_qty"] == 0 and revised["committed_qty"] == 0
    assert revised["unit_cost_cents"] == 1700, "the adjustment replaced the landed cost"
    assert revised["version"] == product["version"] + 1, "the adjustment advanced the product once"
    assert read_slot(slot["id"])["unit_cost_snapshot_cents"] == 1500, (
        "the frozen slot cost is deliberately left behind"
    )

    below_zero = api_client.adjust_inventory(
        product["id"],
        inventory_adjustment_payload(on_hand_delta=-60, reason="CYCLE_COUNT"),
        MERCHANDISER,
    )
    validate_error(below_zero, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)

    unchanged = read_product(product["id"])
    assert unchanged["on_hand_qty"] == 55, "the refused adjustment wrote nothing"
    assert unchanged["available_qty"] == 55
    assert unchanged["unit_cost_cents"] == 1700
    assert_inventory_pool_conserved(unchanged)
