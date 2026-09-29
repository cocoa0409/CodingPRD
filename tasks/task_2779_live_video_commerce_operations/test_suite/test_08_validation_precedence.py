"""When one request breaks two rules, the ladder decides which error comes back."""

from test_helpers import (
    ApiErrorId,
    add_cart_item_payload,
    api_client,
    assert_instant,
    base_scenario,
    build_scenario,
    cart_version,
    checkout_payload,
    make_merchandising_manager_headers,
    make_show_producer_headers,
    make_viewer_headers,
    read_cart,
    read_offer,
    read_product,
    read_show,
    ready_show,
    substantiate_claim,
    validate_error,
    validate_paginated,
)

PRODUCER_HEADERS = make_show_producer_headers()
MERCHANDISER_HEADERS = make_merchandising_manager_headers()


def test_go_live_on_a_draft_show_reports_the_state_error_not_the_closed_window():
    """A DRAFT show nine days before airtime breaks both rules and reports the state one.

    The PRD puts own-state legality at rung 8 and the go-live window at rung 17, and
    "the first check that fails decides the response entirely"; "Going live from any
    status other than READY is ERR_INVALID_SHOW_STATE."

    Design: Difficulty/priority_pair_validation_conflict/go_live_state_beats_temporal_window
    """
    scenario = build_scenario()

    response = api_client.go_live_show(scenario.show_id, PRODUCER_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_SHOW_STATE.value)

    show = read_show(scenario.show_id)
    assert show["status"] == "DRAFT"
    assert show["went_live_at"] is None


def test_the_readiness_gate_passes_without_moving_the_clock():
    """Readiness has no temporal condition, so it clears at the epoch instant.

    The PRD: "A show that clears all six recomputes simulcast_readiness_index from
    the current destination health, stamps readiness_checked_at with the logical
    instant, and increments its version." A single destination reporting exactly the
    reference latency with no frame loss grades 100.

    Design: Difficulty/priority_pair_validation_conflict/go_live_state_beats_temporal_window
    """
    scenario = build_scenario()

    ready_show(scenario.show_id)

    show = read_show(scenario.show_id)
    assert show["status"] == "READY"
    assert_instant(show["readiness_checked_at"], "2026-08-01T00:00:00Z", "readiness_checked_at")
    assert show["simulcast_readiness_index"] == 100


def test_once_the_state_is_legal_the_closed_go_live_window_surfaces():
    """The temporal violation was live all along and appears as soon as the show is READY.

    The PRD: "the logical instant must be at or after scheduled_start_at minus 30
    minutes, and strictly before scheduled_end_at. A producer trying to open the
    stream 31 minutes early, or one second after the planned end, is refused with
    ERR_GO_LIVE_WINDOW_CLOSED."

    Design: Difficulty/priority_pair_validation_conflict/go_live_state_beats_temporal_window
    """
    scenario = build_scenario()

    ready_show(scenario.show_id)
    response = api_client.go_live_show(scenario.show_id, PRODUCER_HEADERS)
    validate_error(response, ApiErrorId.ERR_GO_LIVE_WINDOW_CLOSED.value)

    show = read_show(scenario.show_id)
    assert show["status"] == "READY"
    assert show["went_live_at"] is None


def _live_show_with_a_rejected_claim():
    """A live show whose single-unit offer is active but whose product's claim was rejected."""
    scenario = build_scenario(
        offers=[{"offer_price_cents": 3500, "max_qty": 1}],
        take_live=True,
        activate=True,
        num_carts=1,
    )
    substantiate_claim(scenario.product_id, decision="REJECTED", evidence_ref="COMPLAINT-12")
    return scenario


def test_a_rejected_claim_beats_the_allotment_ceiling_on_the_same_add():
    """Asking for five units of a one-unit offer whose claim was pulled reports the claim error.

    The PRD puts claim substantiation at rung 10 and offer allotment at rung 30, and
    the add-item gauntlet requires "the slot's product must be SUBSTANTIATED
    (ERR_CLAIM_NOT_SUBSTANTIATED)" before "the offer's remaining_qty must be at least
    the requested qty (ERR_OFFER_QTY_EXCEEDED)".

    Design: Difficulty/priority_pair_validation_conflict/add_item_claim_safety_beats_fiscal_qty
    """
    scenario = _live_show_with_a_rejected_claim()

    response = api_client.add_cart_item(
        scenario.cart_id,
        add_cart_item_payload(scenario.offer_id, 5),
        make_viewer_headers(scenario.viewer_id),
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_NOT_SUBSTANTIATED.value)


def test_restoring_the_claim_surfaces_the_allotment_error_on_an_identical_request():
    """With the claim substantiated again the same five-unit request fails on allotment.

    The PRD: "The decision is written straight to claim_substantiation_status", and
    an add whose quantity exceeds the offer's remaining allotment is
    ERR_OFFER_QTY_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/add_item_claim_safety_beats_fiscal_qty
    """
    scenario = _live_show_with_a_rejected_claim()

    api_client.add_cart_item(
        scenario.cart_id,
        add_cart_item_payload(scenario.offer_id, 5),
        make_viewer_headers(scenario.viewer_id),
    )
    substantiate_claim(scenario.product_id, decision="SUBSTANTIATED", evidence_ref="LAB-90")

    response = api_client.add_cart_item(
        scenario.cart_id,
        add_cart_item_payload(scenario.offer_id, 5),
        make_viewer_headers(scenario.viewer_id),
    )
    validate_error(response, ApiErrorId.ERR_OFFER_QTY_EXCEEDED.value)


def test_neither_rejected_add_writes_a_line_or_moves_a_ledger():
    """Two refused adds leave the basket empty and both ledgers untouched.

    The PRD reserves the ledger movement for "A line that survives all of that",
    with the product's reserved_qty and the offer's held_qty moving only "After the
    line is priced". A rejected claim is not a cancellation, so the offer stays
    ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/add_item_claim_safety_beats_fiscal_qty
    """
    scenario = _live_show_with_a_rejected_claim()

    api_client.add_cart_item(
        scenario.cart_id,
        add_cart_item_payload(scenario.offer_id, 5),
        make_viewer_headers(scenario.viewer_id),
    )
    substantiate_claim(scenario.product_id, decision="SUBSTANTIATED", evidence_ref="LAB-90")
    api_client.add_cart_item(
        scenario.cart_id,
        add_cart_item_payload(scenario.offer_id, 5),
        make_viewer_headers(scenario.viewer_id),
    )

    lines, _meta = validate_paginated(
        api_client.list_cart_items(MERCHANDISER_HEADERS, params={"cart_id": scenario.cart_id})
    )
    assert lines == []
    assert read_cart(scenario.cart_id, scenario.viewer_id)["held_item_count"] == 0

    product = read_product(scenario.product_id)
    assert product["reserved_qty"] == 0
    assert product["available_qty"] == 50

    offer = read_offer(scenario.offer_id)
    assert offer["held_qty"] == 0
    assert offer["remaining_qty"] == 1
    assert offer["status"] == "ACTIVE"


def test_a_stale_cart_version_beats_the_empty_basket_check():
    """An empty basket addressed from a stale view reports the conflict, not the emptiness.

    The PRD puts the stale-version rejection at rung 7 and basket non-emptiness at
    rung 28: "In ladder order, the checks are: ownership, then request shape, then
    the stale-version comparison of §2.8 (ERR_STALE_CART_VERSION), then that the
    cart is OPEN (ERR_INVALID_CART_STATE), then that the show is LIVE
    (ERR_INVALID_SHOW_STATE), then that at least one line is in state HELD
    (ERR_EMPTY_CART)."

    Design: Difficulty/priority_pair_validation_conflict/checkout_stale_version_beats_empty_cart
    """
    scenario = base_scenario(num_viewers=1, num_carts=1)
    current = cart_version(scenario.cart_id, scenario.viewer_id)

    response = api_client.checkout_cart(
        scenario.cart_id,
        checkout_payload(current - 1),
        make_viewer_headers(scenario.viewer_id),
    )
    validate_error(response, ApiErrorId.ERR_STALE_CART_VERSION.value)


def test_a_current_version_on_an_empty_basket_reports_the_empty_cart_error():
    """Replaying the checkout with the cart's real version reaches the emptiness rung.

    The PRD: checkout requires "that at least one line is in state HELD
    (ERR_EMPTY_CART)".

    Design: Difficulty/priority_pair_validation_conflict/checkout_stale_version_beats_empty_cart
    """
    scenario = base_scenario(num_viewers=1, num_carts=1)
    current = cart_version(scenario.cart_id, scenario.viewer_id)

    response = api_client.checkout_cart(
        scenario.cart_id, checkout_payload(current), make_viewer_headers(scenario.viewer_id)
    )
    validate_error(response, ApiErrorId.ERR_EMPTY_CART.value)


def test_neither_refused_checkout_creates_an_order_or_advances_the_cart():
    """Both rejections leave the basket open at the version it started from.

    The PRD: on a stale version "the checkout is rejected with
    ERR_STALE_CART_VERSION (HTTP 412) and no order is created", and only a
    successful checkout "increments its version, and moves OPEN -> CHECKED_OUT".

    Design: Difficulty/priority_pair_validation_conflict/checkout_stale_version_beats_empty_cart
    """
    scenario = base_scenario(num_viewers=1, num_carts=1)
    current = cart_version(scenario.cart_id, scenario.viewer_id)

    api_client.checkout_cart(
        scenario.cart_id, checkout_payload(current - 1), make_viewer_headers(scenario.viewer_id)
    )
    api_client.checkout_cart(
        scenario.cart_id, checkout_payload(current), make_viewer_headers(scenario.viewer_id)
    )

    cart = read_cart(scenario.cart_id, scenario.viewer_id)
    assert cart["status"] == "OPEN"
    assert cart["version"] == current

    orders, _meta = validate_paginated(
        api_client.list_orders(MERCHANDISER_HEADERS, params={"cart_id": scenario.cart_id})
    )
    assert orders == []
