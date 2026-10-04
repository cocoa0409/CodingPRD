"""Numeric and temporal thresholds tested at their exact boundary."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_freeze_in_state,
    create_itinerary,
    create_route,
    get_success_data,
    observe,
    publish_curve,
    read_freeze,
    set_clock,
    setup_passive_watch_reading_wait,
    validate_error,
)


def test_claim_at_a_market_price_equal_to_the_base_fare_is_refused():
    """PRD §3.5: "Filing requires the freeze to actually have something to
    claim: if the freeze's `overshoot_cents` is zero the filing is refused with
    `ERR_NO_OVERSHOOT` (HTTP 422), because a frozen fare that did not rise above
    the manifest has nothing to settle."

    Design: Difficulty/boundary_precision_check/boundary_overshoot_zero_hits_the_hedge_cap_exactly
    """
    set_clock()
    route = create_route(base_fare_cents=8900)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 8900, seats_left=9)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)

    res = api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 8900},
                                TEST_USERS["traveler_headers"])
    validate_error(res, "ERR_NO_OVERSHOOT")
    got = read_freeze(freeze["id"])
    assert got["overshoot_cents"] == 0
    assert got["capped_impact_cents"] == 0


def test_overshoot_saturates_exactly_at_the_cap_and_the_uplift_is_applied():
    """PRD §3.4: "With those two prices fixed, the overshoot is the smaller of
    two quantities: the amount by which the arrival fare exceeds the active base
    fare, floored at zero, and the freeze's `cap_cents`. The capped impact is
    that overshoot multiplied by 1.2 and rounded half-up to two decimal places".

    Design: Difficulty/boundary_precision_check/boundary_overshoot_zero_hits_the_hedge_cap_exactly
    """
    set_clock()
    route = create_route(base_fare_cents=8900)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 21360, seats_left=8)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    got = read_freeze(freeze["id"])

    assert got["manifest_fare_cents"] == 8900
    assert got["cap_cents"] == pytest.approx(12460.00, abs=0.01)
    assert got["overshoot_cents"] == pytest.approx(12460.00, abs=0.01), (
        "a 21360 arrival against an 8900 base absorbs exactly the cap"
    )
    assert got["capped_impact_cents"] == pytest.approx(14952.00, abs=0.01), (
        "the capped impact is the saturated overshoot lifted by 1.2"
    )


def test_one_cent_less_of_overshoot_moves_the_capped_impact_by_one_uplift_step():
    """PRD §3.4: "The capped impact is that overshoot multiplied by 1.2 and
    rounded half-up to two decimal places".

    Design: Difficulty/boundary_precision_check/boundary_overshoot_zero_hits_the_hedge_cap_exactly
    """
    set_clock()
    route = create_route(base_fare_cents=8900)
    publish_curve(route["id"])

    saturated = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], saturated["id"], 21360, seats_left=8)
    freeze_a = create_freeze_in_state(saturated["id"], "FROZEN", deposit_cents=250)

    one_less = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], one_less["id"], 21359, seats_left=8)
    freeze_b = create_freeze_in_state(one_less["id"], "FROZEN", deposit_cents=250)

    assert read_freeze(freeze_a["id"])["capped_impact_cents"] == pytest.approx(14952.00, abs=0.01)
    assert read_freeze(freeze_b["id"])["capped_impact_cents"] == pytest.approx(14950.80, abs=0.01)


def test_watch_notification_is_suppressed_exactly_at_the_cooldown_instant():
    """PRD §3.2: "The window is half-open — a clock reading exactly equal to
    `cooldown_until` is suppressed, which is why the field can be read as
    strictly private to the watcher until one instant past itself."

    Design: Difficulty/boundary_precision_check/boundary_watch_cooldown_half_open_at_exactly_six_hours
    """
    set_clock()
    route, itinerary, watch = setup_passive_watch_reading_wait()
    headers = TEST_USERS["traveler_headers"]

    first = get_success_data(api_client.evaluate_watch(watch["id"], {"request_source": "MEMBER"},
                                                       headers))
    assert first["cooldown_until"] == "2026-09-01T06:00:00.000Z", (
        "the cooldown is stamped as the notification instant plus six hours"
    )

    get_success_data(api_client.advance_clock({"to_iso8601": "2026-09-01T06:00:00.000Z"},
                                              TEST_USERS["admin_headers"]))
    at_boundary = get_success_data(api_client.evaluate_watch(watch["id"],
                                                             {"request_source": "MEMBER"},
                                                             headers))
    assert at_boundary["cooldown_suppressed"] is True, (
        "a clock reading exactly equal to cooldown_until is suppressed"
    )
    assert at_boundary["notification_status"] == "NOTIFIED", (
        "a suppressed pass delivers nothing, so it does not advance the machine"
    )

    get_success_data(api_client.advance_clock({"to_iso8601": "2026-09-01T06:00:01Z"},
                                              TEST_USERS["admin_headers"]))
    past_boundary = get_success_data(api_client.evaluate_watch(watch["id"],
                                                               {"request_source": "MEMBER"},
                                                               headers))
    assert past_boundary["cooldown_suppressed"] is False, (
        "one second past the boundary the recommendation is delivered"
    )
    assert past_boundary["notification_status"] == "WAIT", (
        "the delivery applies the computed wait and moves the watch to WAIT"
    )
    assert past_boundary["notification_attempt_count"] == 3, (
        "every evaluation that is not an expiry increments the attempt count"
    )


def test_a_fresh_watch_is_never_suppressed_on_its_first_notification():
    """PRD §3.2: "A watch in any other status has no cooldown at all, so the
    first notification of a fresh watch is never suppressed."

    Design: Difficulty/boundary_precision_check/boundary_watch_cooldown_half_open_at_exactly_six_hours
    """
    set_clock()
    route, itinerary, watch = setup_passive_watch_reading_wait()
    assert watch["cooldown_until"] is None, (
        "a freshly armed watch carries no cooldown instant"
    )
    first = get_success_data(
        api_client.evaluate_watch(watch["id"], {"request_source": "MEMBER"},
                                  TEST_USERS["traveler_headers"])
    )
    assert first["cooldown_suppressed"] is False
    assert first["notification_attempt_count"] == 1