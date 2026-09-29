"""Ending the broadcast: four caused links plus the sibling closures."""

from test_helpers import (
    add_line,
    api_client,
    assert_instant,
    base_scenario,
    end_scenario,
    make_show_producer_headers,
    read_cart,
    read_line,
    read_offer,
    read_product,
    read_show,
    validate_success,
)

PRODUCER_HEADERS = make_show_producer_headers()


def _show_ended_with_one_held_basket():
    """One viewer holds three units, another holds nothing, and the broadcast closes."""
    scenario = base_scenario()
    line = add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 3)
    end_scenario(scenario, "2026-08-10T19:30:00Z")
    return scenario, line


def test_ending_the_broadcast_expires_the_live_offer():
    """The show closes at the logical instant and its active offer expires with it.

    The PRD: ending "moves LIVE -> ENDED, stamps ended_at with the logical instant"
    and then "Link one: every flash offer of this show whose status is SCHEDULED,
    ACTIVE or EXHAUSTED transitions to EXPIRED."

    Design: Difficulty/transitive_cascade/show_end_cascade_depth_four
    """
    scenario, line = _show_ended_with_one_held_basket()

    show = read_show(scenario.show_id)
    assert show["status"] == "ENDED"
    assert_instant(show["ended_at"], "2026-08-10T19:30:00Z", "ended_at")

    assert read_offer(scenario.offer_id)["status"] == "EXPIRED"


def test_offer_expiry_releases_the_held_line_and_unwinds_both_ledgers():
    """The expiring offer gives back three units of stock and three units of allotment.

    The PRD: "Link two: each expiring offer releases every cart line of that offer
    still in state HELD, setting state to RELEASED and released_reason to
    OFFER_EXPIRED; and per released line the product's reserved_qty is decremented,
    available_qty recomputed, and the offer's held_qty decremented."

    Design: Difficulty/transitive_cascade/show_end_cascade_depth_four
    """
    scenario, line = _show_ended_with_one_held_basket()

    released = read_line(line["id"])
    assert released["state"] == "RELEASED"
    assert released["released_reason"] == "OFFER_EXPIRED"
    assert_instant(released["released_at"], "2026-08-10T19:30:00Z", "released_at")

    product = read_product(scenario.product_id)
    assert product["reserved_qty"] == 0
    assert product["available_qty"] == 50

    offer = read_offer(scenario.offer_id)
    assert offer["held_qty"] == 0
    assert offer["remaining_qty"] == 10


def test_a_basket_whose_every_line_was_released_is_abandoned_with_a_deadline():
    """The stranded basket becomes recoverable for twenty minutes after the close.

    The PRD: "Link three: any cart still OPEN that held at least one line and whose
    lines are now all in state RELEASED transitions OPEN -> ABANDONED, stamping
    abandoned_at at the logical instant and recovery_deadline_at 20 minutes later."

    Design: Difficulty/transitive_cascade/show_end_cascade_depth_four
    """
    scenario, line = _show_ended_with_one_held_basket()

    cart = read_cart(scenario.cart_id, scenario.viewer_id)
    assert cart["status"] == "ABANDONED"
    assert_instant(cart["abandoned_at"], "2026-08-10T19:30:00Z", "abandoned_at")
    assert_instant(cart["recovery_deadline_at"], "2026-08-10T19:50:00Z", "recovery_deadline_at")


def test_a_cart_that_never_held_a_line_is_left_open():
    """An empty basket was never a lost basket, so the cascade skips it.

    The PRD: "A cart a viewer opened but never added anything to stays OPEN — it was
    never a lost basket."

    Design: Difficulty/transitive_cascade/show_end_cascade_depth_four
    """
    scenario, line = _show_ended_with_one_held_basket()

    untouched = read_cart(scenario.carts[1]["id"], scenario.viewers[1]["id"])
    assert untouched["status"] == "OPEN"
    assert untouched["abandoned_at"] is None


def test_the_cascaded_abandonment_moves_the_shows_abandonment_rate():
    """One abandoned basket out of the two ever opened is 5,000 basis points.

    The PRD: "Link four: each such abandonment increments the show's
    abandoned_cart_count and its abandonment_rate_bp is recomputed."

    Design: Difficulty/transitive_cascade/show_end_cascade_depth_four
    """
    scenario, line = _show_ended_with_one_held_basket()

    show = read_show(scenario.show_id)
    assert show["abandoned_cart_count"] == 1
    assert show["abandonment_rate_bp"] == 5000


def test_ending_completes_the_booking_and_closes_the_destination():
    """The talent's booking completes and the live destination goes off air.

    The PRD: "every simulcast destination of the show still in LIVE transitions LIVE
    -> ENDED, and every booking of the show still in CONFIRMED transitions CONFIRMED
    -> COMPLETED".

    Design: Difficulty/transitive_cascade/show_end_cascade_depth_four
    """
    scenario, line = _show_ended_with_one_held_basket()

    booking = validate_success(
        api_client.get_host_booking(scenario.booking["id"], PRODUCER_HEADERS)
    )
    assert booking["status"] == "COMPLETED"

    channel = validate_success(
        api_client.get_stream_channel(scenario.channel_id, PRODUCER_HEADERS)
    )
    assert channel["status"] == "ENDED"


def test_a_broadcast_that_sold_nothing_settles_at_a_zero_provisional_margin():
    """No order was ever placed, so the recomputed provisional margin is zero.

    The PRD: "Finally the show recomputes margin_provisional_cents and
    pending_question_count", the provisional margin being merchandise revenue less
    cost of goods less commission over the show's orders.

    Design: Difficulty/transitive_cascade/show_end_cascade_depth_four
    """
    scenario, line = _show_ended_with_one_held_basket()

    assert read_show(scenario.show_id)["margin_provisional_cents"] == 0
