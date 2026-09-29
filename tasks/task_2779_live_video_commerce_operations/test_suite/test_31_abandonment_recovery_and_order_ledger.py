"""Abandonment, the recovery window, empty-basket checkout and order cancellation."""

from test_helpers import (
    MERCHANDISER,
    PRODUCER,
    ApiErrorId,
    abandon_cart,
    add_line,
    api_client,
    assert_cart,
    assert_instant,
    assert_offer_allotment_conserved,
    assert_order,
    cancel_order,
    cart_version,
    checkout_payload,
    end_scenario,
    live_show_scenario,
    live_show_with_active_offer,
    make_viewer_headers,
    order_scenario,
    read_cart,
    read_channel,
    read_line,
    read_offer,
    read_product,
    read_show,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_recovery_attempted_exactly_on_the_deadline_is_already_too_late():
    """A viewer who tries to recover an abandoned basket at the very instant the
    recovery deadline falls is refused, and the basket stays abandoned.

    PRD 3.7: "an attempt landing exactly on the deadline is already too late and is
    refused with `ERR_RECOVERY_WINDOW_CLOSED`". PRD 3.7 also fixes the deadline:
    "The cart stamps `abandoned_at` with the logical instant and sets
    `recovery_deadline_at` to that instant plus a" recovery window of 20 minutes.

    Design: Corner/validations/recover_at_exactly_the_recovery_deadline_rejected
    """
    scenario = live_show_with_active_offer(num_carts=1)
    line = add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 2)
    abandoned = abandon_cart(scenario.cart_id, scenario.viewer_id)
    assert_instant(abandoned["abandoned_at"], "2026-08-10T18:10:00Z", "abandoned_at")
    assert_instant(
        abandoned["recovery_deadline_at"], "2026-08-10T18:30:00Z", "recovery_deadline_at"
    )

    set_clock("2026-08-10T18:30:00Z")
    too_late = api_client.recover_cart(
        scenario.cart_id, make_viewer_headers(scenario.viewer_id)
    )
    validate_error(too_late, ApiErrorId.ERR_RECOVERY_WINDOW_CLOSED)

    cart = read_cart(scenario.cart_id, scenario.viewer_id)
    assert_cart(cart)
    assert cart["status"] == "ABANDONED", "the refused recovery left the cart abandoned"
    assert cart["recovered_count"] == 0, "no recovery loop completed"
    assert cart["held_item_count"] == 0, "the released line was not re-held"
    assert_instant(
        cart["recovery_deadline_at"], "2026-08-10T18:30:00Z", "recovery_deadline_at"
    )

    released = read_line(line["id"])
    assert released["state"] == "RELEASED", "the line is still released"
    assert released["released_reason"] == "CART_ABANDONED"

    offer = read_offer(scenario.offer_id)
    assert offer["held_qty"] == 0, "the refused recovery took no allotment back"
    assert offer["remaining_qty"] == 10
    assert offer["status"] == "ACTIVE", "the offer's window is still open"
    assert read_product(scenario.product_id)["available_qty"] == 50, (
        "the released units are still in circulation"
    )


def test_recovery_after_every_offer_has_expired_finds_nothing_recoverable():
    """Inside the recovery window but after the broadcast has expired its offers,
    recovery is refused because no released line can be re-held.

    PRD 3.7: "A released line is recoverable when the offer it names is currently
    `ACTIVE`, that offer's `remaining_qty` is at least the line's `qty`, and the
    product's `available_qty` is at least the line's `qty`. If no line satisfies
    all three tests, recovery is refused with `ERR_NO_RECOVERABLE_ITEMS`". PRD 3.9
    expires the offers: "every flash offer of this show whose status is
    `SCHEDULED`, `ACTIVE` or `EXHAUSTED` transitions to `EXPIRED`".

    Design: Corner/errors/recover_after_every_offer_expired_returns_no_recoverable_items
    """
    scenario = live_show_with_active_offer(num_carts=1)
    line = add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 2)
    abandon_cart(scenario.cart_id, scenario.viewer_id)

    end_scenario(scenario, "2026-08-10T18:15:00Z")
    expired_offer = read_offer(scenario.offer_id)
    assert expired_offer["status"] == "EXPIRED", "ending the show expired the offer"
    assert expired_offer["remaining_qty"] == 10
    assert_offer_allotment_conserved(expired_offer)

    set_clock("2026-08-10T18:20:00Z")
    refused = api_client.recover_cart(
        scenario.cart_id, make_viewer_headers(scenario.viewer_id)
    )
    validate_error(refused, ApiErrorId.ERR_NO_RECOVERABLE_ITEMS)

    cart = read_cart(scenario.cart_id, scenario.viewer_id)
    assert cart["status"] == "ABANDONED", "the basket stays abandoned"
    assert cart["recovered_count"] == 0
    assert cart["held_item_count"] == 0
    assert_instant(
        cart["recovery_deadline_at"], "2026-08-10T18:30:00Z", "recovery_deadline_at"
    )
    assert read_line(line["id"])["state"] == "RELEASED", "the ineligible line is left behind"
    assert read_product(scenario.product_id)["reserved_qty"] == 0, "nothing was re-reserved"


def test_checkout_of_an_empty_basket_at_the_current_version_reports_an_empty_cart():
    """A viewer who checks out a cart holding no lines is refused for emptiness even
    though the version supplied is the cart's current one.

    PRD 3.7: "In ladder order, the checks are: ownership, then request shape, then
    the stale-version comparison of §2.8 (`ERR_STALE_CART_VERSION`), then that the
    cart is `OPEN` (`ERR_INVALID_CART_STATE`), then that the show is `LIVE`
    (`ERR_INVALID_SHOW_STATE`), then that at least one line is in state `HELD`
    (`ERR_EMPTY_CART`)."

    Design: Corner/validations/checkout_of_empty_cart_with_current_version_returns_empty_cart
    """
    scenario = live_show_scenario(num_carts=1)
    current_version = cart_version(scenario.cart_id, scenario.viewer_id)

    empty = api_client.checkout_cart(
        scenario.cart_id,
        checkout_payload(current_version),
        make_viewer_headers(scenario.viewer_id),
    )
    validate_error(empty, ApiErrorId.ERR_EMPTY_CART)

    cart = read_cart(scenario.cart_id, scenario.viewer_id)
    assert cart["status"] == "OPEN", "the refused checkout left the cart open"
    assert cart["checked_out_at"] is None, "nothing was converted"
    assert cart["held_item_count"] == 0
    assert cart["version"] == current_version, "a refused checkout does not advance the cart"

    orders, meta = validate_paginated(
        api_client.list_orders(MERCHANDISER, {"cart_id": scenario.cart_id})
    )
    assert meta["total_count"] == 0, "no order was created"
    assert orders == [], "no order was created"


def test_cancelling_a_never_captured_order_voids_it_and_restocks_the_exhausted_offer():
    """Cancelling an order that was never captured voids the payment, refunds
    nothing, releases the committed line and reopens the offer it had exhausted.

    PRD 3.7: "A never-captured order — `payment_state` of `AUTHORIZED` — moves
    `AUTHORIZED → VOIDED`, its `fulfillment_state` moving `PENDING → CANCELLED`;
    `refunded_cents` stays 0, and the show's `gross_merchandise_cents` is"
    unchanged. PRD 3.7 on the release: cancellation will "release every `COMMITTED`
    line of the order's cart to `RELEASED` with `released_reason` set to
    `ORDER_CANCELLED`, decrement the product's `committed_qty` and the offer's
    `sold_qty` by each released `qty` while recomputing `available_qty` and
    `remaining_qty`, restock any offer that was `EXHAUSTED` and now shows
    `remaining_qty` of at least 1 back to `ACTIVE` when its window is still open
    and the show is still `LIVE`".

    Design: Corner/endpoints/order_cancel_from_authorized_voids_and_restocks_the_exhausted_offer
    """
    scenario, order = order_scenario(qty=10)
    assert_order(order)
    assert order["payment_state"] == "AUTHORIZED", "checkout authorises without capturing"
    assert order["fulfillment_state"] == "PENDING"
    assert order["merchandise_cents"] == 31500, "ten units at 3150 after the 0.10 bundle tier"
    assert order["tax_cents"] == 2756, "31500 cents at 8.75 percent, rounded half up"
    assert order["shipping_cents"] == 0, "merchandise of at least 7500 cents ships free"
    assert order["total_cents"] == 34256, "31500 plus 2756 plus nothing for shipping"
    assert read_offer(scenario.offer_id)["status"] == "EXHAUSTED", (
        "the whole allotment was taken, so the offer is exhausted"
    )

    cancelled = cancel_order(order["id"], cancel_reason="VIEWER_CHANGED_MIND")
    assert cancelled["payment_state"] == "VOIDED", "a never-captured order is voided"
    assert cancelled["fulfillment_state"] == "CANCELLED"
    assert cancelled["refunded_cents"] == 0, "there was never any money to refund"
    assert cancelled["cancel_reason"] == "VIEWER_CHANGED_MIND"
    assert_instant(cancelled["cancelled_at"], "2026-08-10T18:10:00Z", "cancelled_at")
    assert cancelled["captured_at"] is None, "the order was never captured"

    lines, _ = validate_paginated(
        api_client.list_cart_items(MERCHANDISER, {"cart_id": scenario.cart_id})
    )
    assert len(lines) == 1, "the cart carried exactly one line"
    assert lines[0]["state"] == "RELEASED", "the committed line went back to released"
    assert lines[0]["released_reason"] == "ORDER_CANCELLED"

    offer = read_offer(scenario.offer_id)
    assert offer["sold_qty"] == 0, "the sold units left the allotment"
    assert offer["held_qty"] == 0
    assert offer["remaining_qty"] == 10, "the whole allotment is on offer again"
    assert offer["status"] == "ACTIVE", (
        "an exhausted offer with allotment back, an open window and a live show restocks"
    )
    product = read_product(scenario.product_id)
    assert product["committed_qty"] == 0, "the commitment is undone"
    assert product["available_qty"] == 50, "every unit is back in circulation"
    assert read_show(scenario.show["id"])["gross_merchandise_cents"] == 0, (
        "a never-captured order was never inside gross merchandise"
    )


def test_ending_the_broadcast_returns_fully_reconciled_counters_in_its_own_response():
    """The response to ending a broadcast already carries the recomputed abandonment
    counters, and an immediate read of the show reports exactly the same numbers.

    PRD 1: "every cascade, counter and derived field is reconciled inside the
    request that caused it — there is no background job, no eventual settlement,
    and no window in which the offer ledger and the inventory ledger disagree".
    PRD 2.11: "Every derived counter downstream of a cascade is recomputed inside
    the same request, so a read issued immediately after sees fully reconciled
    values." PRD 3.7 fixes the rate: "It is 10,000 multiplied by
    `abandoned_cart_count`, divided by the total number of carts ever opened on the
    show, rounded half up to a whole basis point".

    Design: Corner/consistency_model/show_end_recomputes_denormalised_counters_in_the_same_response
    """
    scenario = live_show_with_active_offer(num_carts=1)
    line = add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 2)

    ended = end_scenario(scenario, "2026-08-10T18:10:00Z")
    assert ended["status"] == "ENDED", "the broadcast is off air"
    assert_instant(ended["ended_at"], "2026-08-10T18:10:00Z", "ended_at")
    assert ended["abandoned_cart_count"] == 1, "the one basket the ending abandoned"
    assert ended["abandonment_rate_bp"] == 10000, "one abandoned cart out of one cart ever opened"
    assert ended["gross_merchandise_cents"] == 0, "no order was ever captured"
    assert ended["margin_provisional_cents"] == 0, "no order is inside the provisional scope"

    read_back = read_show(scenario.show["id"])
    for field in (
        "status",
        "abandoned_cart_count",
        "abandonment_rate_bp",
        "gross_merchandise_cents",
        "margin_provisional_cents",
    ):
        assert read_back[field] == ended[field], (
            f"an immediate read must agree with the ending response on {field}"
        )
    assert_instant(read_back["ended_at"], ended["ended_at"], "ended_at")

    released = read_line(line["id"])
    assert released["state"] == "RELEASED", "offer expiry released the held line"
    assert released["released_reason"] == "OFFER_EXPIRED"

    cart = read_cart(scenario.cart_id, scenario.viewer_id)
    assert cart["status"] == "ABANDONED", "a basket whose lines were all released is abandoned"
    assert_instant(
        cart["recovery_deadline_at"], "2026-08-10T18:30:00Z", "recovery_deadline_at"
    )

    offer = read_offer(scenario.offer_id)
    assert offer["status"] == "EXPIRED", "the show's offers expire with it"
    assert offer["held_qty"] == 0 and offer["remaining_qty"] == 10, (
        "the released allotment is reconciled in the same request"
    )
    assert read_channel(scenario.channel_id)["status"] == "ENDED", (
        "a live destination ends with the show"
    )
    booking = validate_success(
        api_client.get_host_booking(scenario.booking["id"], PRODUCER)
    )
    assert booking["status"] == "COMPLETED", "a confirmed booking completes with the show"
