"""The guarded restock loop: an offer exhausts, reopens, exhausts and then stays shut."""

from test_helpers import (
    abandon_cart,
    add_line,
    assert_instant,
    assert_offer_allotment_conserved,
    build_scenario,
    read_cart,
    read_line,
    read_offer,
    read_product,
    read_show,
    set_clock,
)


def _two_shopper_show():
    """A live show whose only offer allots two units, with two viewers holding carts."""
    return build_scenario(
        offers=[{"offer_price_cents": 3500, "max_qty": 2}],
        num_viewers=2,
        num_carts=2,
        take_live=True,
        activate=True,
    )


def test_a_hold_that_drains_the_allotment_exhausts_the_offer():
    """Holding both allotted units drives remaining to zero and closes the offer.

    The PRD: "Whenever a hold or a checkout commitment drives the recomputed
    remaining_qty to exactly 0, an ACTIVE offer transitions ACTIVE -> EXHAUSTED in
    that same request", while the product's "reserved_qty is increased by the line's
    qty and available_qty is recomputed".

    Design: Difficulty/non_linear_state_machine/flash_offer_exhausted_returns_to_active_cycle
    """
    scenario = _two_shopper_show()

    add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 2)

    offer = read_offer(scenario.offer_id)
    assert offer["status"] == "EXHAUSTED"
    assert offer["held_qty"] == 2
    assert offer["remaining_qty"] == 0
    assert_offer_allotment_conserved(offer)

    product = read_product(scenario.product_id)
    assert product["reserved_qty"] == 2
    assert product["available_qty"] == 48


def test_abandonment_releases_the_line_and_reopens_the_exhausted_offer():
    """One shopper walking away genuinely reopens the offer for the next one.

    The PRD: on abandonment "Any offer that had been sitting in EXHAUSTED and now
    shows remaining_qty of at least 1 transitions EXHAUSTED -> ACTIVE, provided its
    window is still open and the show is still LIVE", with each held line becoming
    "RELEASED with released_reason set to CART_ABANDONED".

    Design: Difficulty/non_linear_state_machine/flash_offer_exhausted_returns_to_active_cycle
    """
    scenario = _two_shopper_show()

    line = add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 2)
    abandon_cart(scenario.cart_id, scenario.viewer_id)

    offer = read_offer(scenario.offer_id)
    assert offer["status"] == "ACTIVE"
    assert offer["remaining_qty"] == 2

    released = read_line(line["id"])
    assert released["state"] == "RELEASED"
    assert released["released_reason"] == "CART_ABANDONED"


def test_abandonment_opens_a_twenty_minute_recovery_window():
    """The abandoned basket is stamped with the instant and a deadline 20 minutes later.

    The PRD: "The cart stamps abandoned_at with the logical instant and sets
    recovery_deadline_at to that instant plus a recovery window of a third of an
    hour, meaning 20 minutes."

    Design: Difficulty/non_linear_state_machine/flash_offer_exhausted_returns_to_active_cycle
    """
    scenario = _two_shopper_show()

    add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 2)
    abandon_cart(scenario.cart_id, scenario.viewer_id)

    cart = read_cart(scenario.cart_id, scenario.viewer_id)
    assert cart["status"] == "ABANDONED"
    assert_instant(cart["abandoned_at"], "2026-08-10T18:10:00Z", "abandoned_at")
    assert_instant(cart["recovery_deadline_at"], "2026-08-10T18:30:00Z", "recovery_deadline_at")


def test_the_exhaustion_edge_fires_a_second_time_in_the_same_broadcast():
    """The reopened offer exhausts again when the next shopper takes the same two units.

    The PRD calls this "the ACTIVE -> EXHAUSTED -> ACTIVE restock cycle, and it is
    bounded only by the window", the forward edge firing "Whenever a hold or a
    checkout commitment drives the recomputed remaining_qty to exactly 0".

    Design: Difficulty/non_linear_state_machine/flash_offer_exhausted_returns_to_active_cycle
    """
    scenario = _two_shopper_show()

    add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 2)
    abandon_cart(scenario.cart_id, scenario.viewer_id)
    add_line(scenario.carts[1]["id"], scenario.offer_id, scenario.viewers[1]["id"], 2)

    offer = read_offer(scenario.offer_id)
    assert offer["status"] == "EXHAUSTED"
    assert offer["remaining_qty"] == 0
    assert read_product(scenario.product_id)["available_qty"] == 48


def test_a_release_after_the_window_closes_leaves_the_offer_exhausted():
    """Allotment comes back but the offer stays shut, because the window has passed.

    The PRD: "If the window has already closed, or the show is no longer LIVE, the
    offer stays EXHAUSTED even though allotment is available."

    Design: Difficulty/non_linear_state_machine/flash_offer_exhausted_returns_to_active_cycle
    """
    scenario = _two_shopper_show()

    add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 2)
    abandon_cart(scenario.cart_id, scenario.viewer_id)
    second_line = add_line(
        scenario.carts[1]["id"], scenario.offer_id, scenario.viewers[1]["id"], 2
    )

    set_clock("2026-08-10T19:05:00Z")
    abandon_cart(scenario.carts[1]["id"], scenario.viewers[1]["id"])

    offer = read_offer(scenario.offer_id)
    assert offer["remaining_qty"] == 2
    assert offer["status"] == "EXHAUSTED"

    assert read_line(second_line["id"])["state"] == "RELEASED"
    product = read_product(scenario.product_id)
    assert product["reserved_qty"] == 0
    assert product["available_qty"] == 50


def test_both_lost_baskets_are_counted_in_the_shows_abandonment_rate():
    """Two abandoned carts out of two carts ever opened is a rate of 10,000 basis points.

    The PRD: the rate "is 10,000 multiplied by abandoned_cart_count, divided by the
    total number of carts ever opened on the show, rounded half up to a whole basis
    point".

    Design: Difficulty/non_linear_state_machine/flash_offer_exhausted_returns_to_active_cycle
    """
    scenario = _two_shopper_show()

    add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 2)
    abandon_cart(scenario.cart_id, scenario.viewer_id)
    add_line(scenario.carts[1]["id"], scenario.offer_id, scenario.viewers[1]["id"], 2)
    set_clock("2026-08-10T19:05:00Z")
    abandon_cart(scenario.carts[1]["id"], scenario.viewers[1]["id"])

    show = read_show(scenario.show_id)
    assert show["abandoned_cart_count"] == 2
    assert show["abandonment_rate_bp"] == 10000
