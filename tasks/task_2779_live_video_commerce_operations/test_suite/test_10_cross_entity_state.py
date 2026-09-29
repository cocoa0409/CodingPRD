"""Operations whose legality lives on a neighbouring entity, not on the target."""

from test_helpers import (
    ApiErrorId,
    activate_offer,
    add_cart_item_payload,
    api_client,
    assert_instant,
    build_scenario,
    certify_host,
    go_live,
    make_host_headers,
    make_merchandising_manager_headers,
    make_show_producer_headers,
    make_viewer_headers,
    read_line,
    read_offer,
    read_product,
    read_show,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.fixtures import set_clock

PRODUCER_HEADERS = make_show_producer_headers()
MERCHANDISER_HEADERS = make_merchandising_manager_headers()


def _ready_show_inside_the_offer_window():
    """A READY show never taken live, with the clock inside the offer's window."""
    scenario = build_scenario(run_ready=True)
    set_clock(TEST_DEFAULTS["CLOCK_LIVE"])
    return scenario


def test_activating_an_offer_under_a_ready_show_is_refused():
    """Every property of the offer is satisfiable; the show two hops away is not.

    The PRD: activation requires "the show reached through the offer's lineup slot
    must be LIVE (ERR_INVALID_SHOW_STATE)".

    Design: Difficulty/cross_entity_state_dependency/offer_activate_requires_live_show
    """
    scenario = _ready_show_inside_the_offer_window()

    response = api_client.activate_flash_offer(scenario.offer_id, MERCHANDISER_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_SHOW_STATE.value)


def test_the_refused_activation_leaves_the_offer_scheduled():
    """A refusal writes nothing onto the offer it addressed.

    The PRD: "A successful create enters SCHEDULED with held_qty and sold_qty at
    zero and remaining_qty equal to max_qty, and activated_at null", and only
    "Activation stamps activated_at with the logical instant".

    Design: Difficulty/cross_entity_state_dependency/offer_activate_requires_live_show
    """
    scenario = _ready_show_inside_the_offer_window()

    api_client.activate_flash_offer(scenario.offer_id, MERCHANDISER_HEADERS)

    offer = read_offer(scenario.offer_id)
    assert offer["status"] == "SCHEDULED"
    assert offer["activated_at"] is None


def test_the_identical_activation_succeeds_once_the_show_is_live():
    """Taking the show live changes nothing about the offer and yet unblocks it.

    The PRD: "Activation stamps activated_at with the logical instant, recomputes
    remaining_qty as max_qty less held_qty less sold_qty, and increments the
    offer's version."

    Design: Difficulty/cross_entity_state_dependency/offer_activate_requires_live_show
    """
    scenario = _ready_show_inside_the_offer_window()

    api_client.activate_flash_offer(scenario.offer_id, MERCHANDISER_HEADERS)
    go_live(scenario.show_id)

    show = read_show(scenario.show_id)
    assert show["status"] == "LIVE"
    assert_instant(show["went_live_at"], "2026-08-10T18:10:00Z", "went_live_at")

    validate_success(api_client.activate_flash_offer(scenario.offer_id, MERCHANDISER_HEADERS))

    offer = read_offer(scenario.offer_id)
    assert offer["status"] == "ACTIVE"
    assert_instant(offer["activated_at"], "2026-08-10T18:10:00Z", "activated_at")
    assert offer["remaining_qty"] == 10


def _booking_under_a_lapsed_certification():
    """A PENDING booking whose host's certification expired a day before the clock."""
    scenario = build_scenario(
        certified_until="2026-08-05T00:00:00Z",
        confirm=False,
        with_disclosure=False,
        slots=[],
        offers=[],
        channels=[],
    )
    set_clock("2026-08-06T00:00:00Z")
    return scenario


def _read_host(host_id: str) -> dict:
    return validate_success(api_client.get_host(host_id, PRODUCER_HEADERS))


def test_a_host_whose_certification_instant_has_passed_reads_as_expired():
    """certification_status is derived from the clock, never stored.

    The PRD: "certification_status is never stored independently of that instant —
    it is derived on every read: UNCERTIFIED when
    disclosure_certification_expires_at is null, EXPIRED when
    disclosure_certification_expires_at is strictly earlier than the logical
    clock's current instant, and CERTIFIED otherwise."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_certified_host
    """
    scenario = _booking_under_a_lapsed_certification()

    assert _read_host(scenario.host_id)["certification_status"] == "EXPIRED"


def test_confirming_a_booking_for_an_expired_host_is_refused():
    """The booking is PENDING and owned by the actor; the Host row is what fails.

    The PRD: acceptance is refused "unless the host's certification_status is
    CERTIFIED at that moment (ERR_HOST_CERTIFICATION_EXPIRED)".

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_certified_host
    """
    scenario = _booking_under_a_lapsed_certification()
    booking_id = scenario.booking["id"]

    response = api_client.confirm_host_booking(booking_id, make_host_headers(scenario.host_id))
    validate_error(response, ApiErrorId.ERR_HOST_CERTIFICATION_EXPIRED.value)

    booking = validate_success(
        api_client.get_host_booking(booking_id, PRODUCER_HEADERS)
    )
    assert booking["status"] == "PENDING"
    assert booking["confirmed_at"] is None


def test_recertifying_the_host_alone_lets_the_same_confirm_succeed():
    """Nothing about the booking changes; only the neighbouring Host row is renewed.

    The PRD: "acceptance moves the booking PENDING -> CONFIRMED, stamping
    confirmed_at with the logical instant and incrementing version."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_certified_host
    """
    scenario = _booking_under_a_lapsed_certification()
    booking_id = scenario.booking["id"]

    api_client.confirm_host_booking(booking_id, make_host_headers(scenario.host_id))
    certify_host(scenario.host_id, certified_until=TEST_DEFAULTS["CERT_UNTIL"])

    host = _read_host(scenario.host_id)
    assert host["certification_status"] == "CERTIFIED"
    assert_instant(
        host["disclosure_certification_expires_at"],
        "2026-12-31T23:59:59Z",
        "disclosure_certification_expires_at",
    )

    confirmed = validate_success(
        api_client.confirm_host_booking(booking_id, make_host_headers(scenario.host_id))
    )
    assert confirmed["status"] == "CONFIRMED"
    assert_instant(confirmed["confirmed_at"], "2026-08-06T00:00:00Z", "confirmed_at")


def _live_show_with_a_scheduled_offer():
    """A LIVE show at 18:10Z whose offer was never activated, plus an empty cart."""
    return build_scenario(take_live=True, num_carts=1)


def test_adding_a_line_against_a_scheduled_offer_reports_the_offer_status():
    """With the show LIVE, the offer's own status is the only thing left to fail.

    The PRD: adding a line requires that "the show must be LIVE
    (ERR_INVALID_SHOW_STATE) and the named offer must be ACTIVE
    (ERR_OFFER_NOT_ACTIVE)".

    Design: Difficulty/cross_entity_state_dependency/cart_item_requires_active_offer
    """
    scenario = _live_show_with_a_scheduled_offer()

    response = api_client.add_cart_item(
        scenario.cart_id,
        add_cart_item_payload(scenario.offer_id, 1),
        make_viewer_headers(scenario.viewer_id),
    )
    validate_error(response, ApiErrorId.ERR_OFFER_NOT_ACTIVE.value)

    lines, _meta = validate_paginated(
        api_client.list_cart_items(MERCHANDISER_HEADERS, params={"cart_id": scenario.cart_id})
    )
    assert lines == []

    product = read_product(scenario.product_id)
    assert product["reserved_qty"] == 0
    assert product["available_qty"] == 50


def test_the_same_payload_holds_a_line_once_the_offer_is_active():
    """Activation alone turns the refused request into a priced hold.

    The PRD: "A line that survives all of that is created in state HELD",
    priced by the four-step order with "The line's line_tax_cents is
    line_gross_cents multiplied by a tax rate of 8.75 percent, rounded half up".

    Design: Difficulty/cross_entity_state_dependency/cart_item_requires_active_offer
    """
    scenario = _live_show_with_a_scheduled_offer()

    api_client.add_cart_item(
        scenario.cart_id,
        add_cart_item_payload(scenario.offer_id, 1),
        make_viewer_headers(scenario.viewer_id),
    )
    activate_offer(scenario.offer_id)
    created = validate_success(
        api_client.add_cart_item(
            scenario.cart_id,
            add_cart_item_payload(scenario.offer_id, 1),
            make_viewer_headers(scenario.viewer_id),
        ),
        201,
    )

    line = read_line(created["id"])
    assert line["state"] == "HELD"
    assert line["effective_unit_price_cents"] == 3500
    assert line["line_gross_cents"] == 3500
    assert line["line_tax_cents"] == 306


def test_the_successful_hold_moves_both_ledgers_by_one_unit():
    """The unit leaves availability on the product and allotment on the offer.

    The PRD: "the product's reserved_qty is increased by the line's qty and
    available_qty is recomputed; the offer's held_qty is increased by the same qty
    and remaining_qty is recomputed".

    Design: Difficulty/cross_entity_state_dependency/cart_item_requires_active_offer
    """
    scenario = _live_show_with_a_scheduled_offer()

    activate_offer(scenario.offer_id)
    api_client.add_cart_item(
        scenario.cart_id,
        add_cart_item_payload(scenario.offer_id, 1),
        make_viewer_headers(scenario.viewer_id),
    )

    product = read_product(scenario.product_id)
    assert product["reserved_qty"] == 1
    assert product["available_qty"] == 49

    offer = read_offer(scenario.offer_id)
    assert offer["held_qty"] == 1
    assert offer["remaining_qty"] == 9
