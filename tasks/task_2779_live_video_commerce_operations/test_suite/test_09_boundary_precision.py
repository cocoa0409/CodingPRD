"""Three inclusive boundaries, each on a different metric and a different endpoint."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant,
    build_scenario,
    create_host_booking_payload,
    create_show,
    hold_line,
    make_show_producer_headers,
    read_channel,
    read_line,
    read_order,
    read_show,
    report_health,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.fixtures import DEFAULT_PRODUCT, DEFAULT_SLOT, checkout_cart_of, set_clock

PRODUCER_HEADERS = make_show_producer_headers()


def _ready_show_at_call_time():
    """A READY show with one reported FLAGSHIP_APP destination, clock at 17:50Z."""
    scenario = build_scenario(run_ready=True)
    set_clock(TEST_DEFAULTS["CLOCK_PRELIVE"])
    return scenario


def test_a_readiness_index_of_69_refuses_go_live():
    """3050 ms costs 31 points, and 69 is one point short of the go-live floor.

    The PRD: "take the destination's reported latency_ms, subtract 1,500
    milliseconds, divide by 50 milliseconds", and the show's index "must be at
    least 70; an index of exactly 70 passes, an index of 69 is refused with
    ERR_SIMULCAST_NOT_READY".

    Design: Difficulty/boundary_precision_check/go_live_readiness_index_70_passes_69_fails
    """
    scenario = _ready_show_at_call_time()

    report_health(scenario.channel_id, 3050, 0.0)
    assert read_channel(scenario.channel_id)["readiness_index"] == 69
    assert read_show(scenario.show_id)["simulcast_readiness_index"] == 69

    response = api_client.go_live_show(scenario.show_id, PRODUCER_HEADERS)
    validate_error(response, ApiErrorId.ERR_SIMULCAST_NOT_READY.value)


def test_an_index_of_69_is_still_above_the_channel_failure_floor():
    """The go-live gate and the destination-failure gate are different thresholds.

    The PRD: "A destination whose recomputed readiness_index falls below 40 is
    unfit to carry the broadcast and transitions to FAILED".

    Design: Difficulty/boundary_precision_check/go_live_readiness_index_70_passes_69_fails
    """
    scenario = _ready_show_at_call_time()

    report_health(scenario.channel_id, 3050, 0.0)
    api_client.go_live_show(scenario.show_id, PRODUCER_HEADERS)

    assert read_channel(scenario.channel_id)["status"] == "PROVISIONED"
    assert read_show(scenario.show_id)["status"] == "READY"


def test_a_readiness_index_of_exactly_70_passes_go_live():
    """3000 ms costs exactly 30 points and the gate lets the show through.

    The PRD: "an index of exactly 70 passes"; "Upon a successful go-live the show
    stamps went_live_at with the logical instant, increments its version, and every
    destination of the show currently in PROVISIONED transitions PROVISIONED ->
    LIVE, each with its own version incremented."

    Design: Difficulty/boundary_precision_check/go_live_readiness_index_70_passes_69_fails
    """
    scenario = _ready_show_at_call_time()

    report_health(scenario.channel_id, 3050, 0.0)
    api_client.go_live_show(scenario.show_id, PRODUCER_HEADERS)
    report_health(scenario.channel_id, 3000, 0.0)

    assert read_channel(scenario.channel_id)["readiness_index"] == 70
    assert read_show(scenario.show_id)["simulcast_readiness_index"] == 70

    validate_success(api_client.go_live_show(scenario.show_id, PRODUCER_HEADERS))

    show = read_show(scenario.show_id)
    assert show["status"] == "LIVE"
    assert_instant(show["went_live_at"], "2026-08-10T17:50:00Z", "went_live_at")
    assert read_channel(scenario.channel_id)["status"] == "LIVE"


def _host_booked_until_2030_plus_a_late_show():
    """A PENDING 17:00-20:30Z booking for the host, and a second show at 21:30Z."""
    scenario = build_scenario(
        confirm=False,
        with_disclosure=False,
        slots=[],
        offers=[],
        channels=[],
    )
    late_show = create_show(
        title="Late Silk",
        scheduled_start_at="2026-08-10T21:30:00Z",
        scheduled_end_at="2026-08-10T23:00:00Z",
    )
    return scenario, late_show


def test_a_gap_of_44_minutes_is_rejected_as_a_booking_overlap():
    """The existing release advanced by 45 minutes lands at 21:15Z, so a 21:14Z call collides.

    The PRD: "the new booking is rejected when the new call_time_at is earlier
    than the existing release_time_at advanced by 45 minutes and the existing
    call_time_at is earlier than the new release_time_at advanced by 45 minutes";
    "a gap of 44 minutes is rejected with ERR_HOST_BOOKING_OVERLAP".

    Design: Difficulty/boundary_precision_check/host_turnaround_buffer_45_accepted_44_rejected
    """
    scenario, late_show = _host_booked_until_2030_plus_a_late_show()

    response = api_client.create_host_booking(
        create_host_booking_payload(
            late_show["id"],
            scenario.host_id,
            call_time_at="2026-08-10T21:14:00Z",
            release_time_at="2026-08-10T23:30:00Z",
            fee_cents=40000,
        ),
        PRODUCER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_HOST_BOOKING_OVERLAP.value)

    bookings, _meta = validate_paginated(
        api_client.list_host_bookings(PRODUCER_HEADERS, params={"show_id": late_show["id"]})
    )
    assert bookings == []


def test_a_gap_of_exactly_45_minutes_is_accepted():
    """21:15Z is not earlier than 21:15Z, so the collision test fails and the booking stands.

    The PRD: "A gap of exactly 45 minutes between one booking's release and the
    next booking's call time is accepted".

    Design: Difficulty/boundary_precision_check/host_turnaround_buffer_45_accepted_44_rejected
    """
    scenario, late_show = _host_booked_until_2030_plus_a_late_show()

    api_client.create_host_booking(
        create_host_booking_payload(
            late_show["id"],
            scenario.host_id,
            call_time_at="2026-08-10T21:14:00Z",
            release_time_at="2026-08-10T23:30:00Z",
            fee_cents=40000,
        ),
        PRODUCER_HEADERS,
    )
    accepted = validate_success(
        api_client.create_host_booking(
            create_host_booking_payload(
                late_show["id"],
                scenario.host_id,
                call_time_at="2026-08-10T21:15:00Z",
                release_time_at="2026-08-10T23:30:00Z",
                fee_cents=40000,
            ),
            PRODUCER_HEADERS,
        ),
        201,
    )

    assert accepted["status"] == "PENDING"
    assert_instant(accepted["call_time_at"], "2026-08-10T21:15:00Z", "call_time_at")
    assert accepted["fee_cents"] == 40000

    bookings, _meta = validate_paginated(
        api_client.list_host_bookings(PRODUCER_HEADERS, params={"show_id": late_show["id"]})
    )
    assert len(bookings) == 1


def test_the_rejected_booking_leaves_the_earlier_one_untouched():
    """A refused overlap does not disturb the booking it collided with.

    The PRD: "over the existing bookings of the same host_id whose status is
    PENDING or CONFIRMED, the new booking is rejected" — the existing row is only
    read.

    Design: Difficulty/boundary_precision_check/host_turnaround_buffer_45_accepted_44_rejected
    """
    scenario, late_show = _host_booked_until_2030_plus_a_late_show()

    api_client.create_host_booking(
        create_host_booking_payload(
            late_show["id"],
            scenario.host_id,
            call_time_at="2026-08-10T21:14:00Z",
            release_time_at="2026-08-10T23:30:00Z",
            fee_cents=40000,
        ),
        PRODUCER_HEADERS,
    )

    first = validate_success(
        api_client.get_host_booking(scenario.booking["id"], PRODUCER_HEADERS)
    )
    assert first["status"] == "PENDING"
    assert_instant(first["release_time_at"], "2026-08-10T20:30:00Z", "release_time_at")


CAPE = {
    "sku": "SKU-CAPE",
    "title": "Silk Opera Cape",
    "base_price_cents": 4000,
    "unit_cost_cents": 1600,
    "on_hand_qty": 40,
    "claim_text": "Lined with recycled satin",
    "evidence_ref": "LAB-91",
}


def _two_baskets_either_side_of_free_shipping():
    """Two units at 3947 in one cart and two units at 3946 in another, both checked out."""
    scenario = build_scenario(
        num_viewers=2,
        products=[dict(DEFAULT_PRODUCT), dict(CAPE)],
        slots=[
            dict(DEFAULT_SLOT),
            {
                "product_index": 1,
                "slot_sequence": 2,
                "planned_start_at": "2026-08-10T18:40:00Z",
                "planned_end_at": "2026-08-10T19:00:00Z",
                "planned_qty": 10,
            },
        ],
        offers=[
            {
                "offer_price_cents": 3947,
                "window_start_at": "2026-08-10T18:00:00Z",
                "window_end_at": "2026-08-10T19:00:00Z",
                "max_qty": 5,
            },
            {
                "slot_index": 1,
                "offer_price_cents": 3946,
                "window_start_at": "2026-08-10T18:00:00Z",
                "window_end_at": "2026-08-10T19:00:00Z",
                "max_qty": 5,
            },
        ],
        take_live=True,
        activate=True,
        num_carts=2,
    )
    line_at_7500 = hold_line(scenario, 2, cart_index=0, offer_index=0)
    line_at_7498 = hold_line(scenario, 2, cart_index=1, offer_index=1)
    order_at_7500 = checkout_cart_of(scenario, 0)
    order_at_7498 = checkout_cart_of(scenario, 1)
    return line_at_7500, line_at_7498, order_at_7500, order_at_7498


def test_the_two_lines_price_one_cent_apart_after_the_bundle_discount():
    """3947 discounts to 3750 and 3946 to 3749, so the grosses straddle 7500.

    The PRD: "The line's effective_unit_price_cents is the line's
    offer_unit_price_cents multiplied by one minus bundle_discount_pct, rounded
    half up to a whole cent", and the gross is "computed from the already-rounded
    per-unit figure".

    Design: Difficulty/boundary_precision_check/free_shipping_at_exactly_7500_merchandise
    """
    line_at_7500, line_at_7498, _o1, _o2 = _two_baskets_either_side_of_free_shipping()

    first = read_line(line_at_7500["id"])
    assert first["effective_unit_price_cents"] == 3750
    assert first["line_gross_cents"] == 7500

    second = read_line(line_at_7498["id"])
    assert second["effective_unit_price_cents"] == 3749
    assert second["line_gross_cents"] == 7498


def test_merchandise_of_exactly_7500_ships_free():
    """The free-shipping comparison is inclusive, so 7500 pays no shipping.

    The PRD: "shipping_cents is a flat 5.99 dollars, except that it is zero when
    merchandise_cents reaches at least 75 dollars; a merchandise total of exactly
    75 dollars ships free."

    Design: Difficulty/boundary_precision_check/free_shipping_at_exactly_7500_merchandise
    """
    _l1, _l2, order_at_7500, _o2 = _two_baskets_either_side_of_free_shipping()

    order = read_order(order_at_7500["id"])
    assert order["merchandise_cents"] == 7500
    assert order["shipping_cents"] == 0
    assert order["tax_cents"] == 656
    assert order["total_cents"] == 8156


def test_merchandise_two_cents_short_pays_the_flat_shipping_fee():
    """7498 misses the threshold and pays 599, on the same 656 cents of tax.

    The PRD: "total_cents is merchandise_cents plus tax_cents plus
    shipping_cents", with the tax being each line's gross "multiplied by the 8.75
    percent tax rate and rounded half up per line".

    Design: Difficulty/boundary_precision_check/free_shipping_at_exactly_7500_merchandise
    """
    _l1, _l2, _o1, order_at_7498 = _two_baskets_either_side_of_free_shipping()

    order = read_order(order_at_7498["id"])
    assert order["merchandise_cents"] == 7498
    assert order["shipping_cents"] == 599
    assert order["tax_cents"] == 656
    assert order["total_cents"] == 8753
