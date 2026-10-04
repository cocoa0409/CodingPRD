"""Multi-hop chains where each hop is caused only by the previous one."""
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
    read_itinerary,
    read_route,
    set_clock,
    setup_pool_and_route,
)


def test_restricted_posture_freezes_the_deposit_accrual_without_unwinding_it():
    """PRD §2.11: "Every freeze on the route in `DRAFT` or `HELD` is frozen in
    place: its `deposit_attributed_cents` and `custody_held_cents` receive no
    further increments and its `membership_days_elapsed` stops advancing, so
    attribution halts without unwinding what has already accrued."

    Design: Difficulty/transitive_cascade/cascade_posture_to_freeze_hold_to_itinerary_lock_to_watch_buynow
    """
    set_clock()
    pool, route = setup_pool_and_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    freeze = create_freeze_in_state(itinerary["id"], "HELD", deposit_cents=5000)

    route = read_route(route["id"])
    get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "RESTRICTED", "posture_reason_code": "REGIONAL_POOL_BREACH",
             "expected_route_version": route["version"]},
            TEST_USERS["admin_headers"])
    )
    at_restriction = read_freeze(freeze["id"])
    assert at_restriction["status"] == "HELD", (
        "a HELD freeze on a RESTRICTED route is frozen in place rather than advanced"
    )
    assert at_restriction["deposit_attributed_cents"] == 0

    # Seven more days of logical clock: the accrual must not resume.
    get_success_data(api_client.advance_clock({"to_iso8601": "2026-09-08T00:00:00Z"},
                                              TEST_USERS["admin_headers"]))
    after = read_freeze(freeze["id"])
    assert after["deposit_attributed_cents"] == 0, (
        "attribution halts without rolling back, and does not advance while restricted"
    )
    assert after["membership_days_elapsed"] == 0
    assert after["custody_held_cents"] == pytest.approx(5000.00, abs=0.01)


def test_restricted_posture_leaves_the_itinerary_guarantee_locked():
    """PRD §3.3: "The itinerary's `guarantee_locked` flag turns on and the
    itinerary's version increments." PRD §3.6: "Expiry moves the freeze to
    `EXPIRED` ... clears the itinerary's `guarantee_locked` flag".

    Design: Difficulty/transitive_cascade/cascade_posture_to_freeze_hold_to_itinerary_lock_to_watch_buynow
    """
    set_clock()
    pool, route = setup_pool_and_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    freeze = create_freeze_in_state(itinerary["id"], "HELD", deposit_cents=5000)
    assert read_itinerary(itinerary["id"])["guarantee_locked"] is True, (
        "opening a freeze turns the itinerary's guarantee lock on"
    )

    route = read_route(route["id"])
    get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "RESTRICTED", "posture_reason_code": "REGIONAL_POOL_BREACH",
             "expected_route_version": route["version"]},
            TEST_USERS["admin_headers"])
    )
    assert read_itinerary(itinerary["id"])["guarantee_locked"] is True, (
        "the lock is carried from the freeze that could no longer advance"
    )


def test_system_fired_buy_now_opens_a_twenty_four_hour_hold():
    """PRD §3.2: "The system fires its own `BUY_NOW` in one narrow
    circumstance: when the route has moved to `RESTRICTED` or `CLOSED` while the
    itinerary is still `PLANNED` or `WATCHING`, and the watch is still inside
    its window." PRD §3.2: "When `BUY_NOW` fires, the itinerary's
    `booking_hold_expires_at` is set to the current instant plus 24 hours".

    Design: Difficulty/transitive_cascade/cascade_posture_to_freeze_hold_to_itinerary_lock_to_watch_buynow
    """
    set_clock()
    pool, route = setup_pool_and_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 10000, seats_left=6)
    itinerary = read_itinerary(itinerary["id"])
    watch = get_success_data(
        api_client.arm_watch(itinerary["id"],
                             {"expected_itinerary_version": itinerary["version"]},
                             TEST_USERS["traveler_headers"])
    )

    route = read_route(route["id"])
    get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "RESTRICTED", "posture_reason_code": "REGIONAL_POOL_BREACH",
             "expected_route_version": route["version"]},
            TEST_USERS["admin_headers"])
    )
    fired = get_success_data(
        api_client.evaluate_watch(watch["id"], {"request_source": "SYSTEM"},
                                  TEST_USERS["traveler_headers"])
    )
    assert fired["notification_status"] == "BUY_NOW", (
        "the escape clause pushes a watcher on a closing route to buy now"
    )
    assert read_itinerary(itinerary["id"])["booking_hold_expires_at"] == "2026-09-02T00:00:00.000Z", (
        "the hold expires exactly 24 hours after the firing instant"
    )


def test_cancelling_an_itinerary_forfeits_its_frozen_deposit():
    """PRD §3.6: "When a freeze in `HELD` or `FROZEN` is cancelled, the
    forfeiture rule looks for a payment on the same itinerary whose kind is
    `MEMBERSHIP_2` and whose status is `CAPTURED` or `PARTIALLY_REFUNDED`. If one
    exists, `deposit_forfeited_cents` is set to twice the freeze's deposit".

    Design: Difficulty/transitive_cascade/cascade_cancel_to_forfeit_to_payment_sink_to_posture_release
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    allow_freezes(route)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    get_success_data(
        api_client.create_payment(
            {"itinerary_id": itinerary["id"], "payment_kind": "MEMBERSHIP_2",
             "amount_cents": 2500, "capture": True},
            TEST_USERS["ops_headers"])
    )
    get_success_data(
        api_client.cancel_itinerary(itinerary["id"], {"cancel_reason": "TRAVELER_PLAN_CHANGE"},
                                    TEST_USERS["traveler_headers"])
    )
    cancelled = read_freeze(freeze["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["deposit_forfeited_cents"] == pytest.approx(500.00, abs=0.01), (
        "the multiplier is applied to the whole deposit"
    )


def test_itinerary_cancellation_sinks_the_membership_payment():
    """PRD §3.6: "If one exists, `deposit_forfeited_cents` is set to twice the
    freeze's deposit and that membership payment is driven to `FORFEITED` with
    its `refundable_remaining_cents` written to zero".

    Design: Difficulty/transitive_cascade/cascade_cancel_to_forfeit_to_payment_sink_to_posture_release
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    allow_freezes(route)
    create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    membership = get_success_data(
        api_client.create_payment(
            {"itinerary_id": itinerary["id"], "payment_kind": "MEMBERSHIP_2",
             "amount_cents": 2500, "capture": True},
            TEST_USERS["ops_headers"])
    )
    get_success_data(
        api_client.cancel_itinerary(itinerary["id"], {"cancel_reason": "TRAVELER_PLAN_CHANGE"},
                                    TEST_USERS["traveler_headers"])
    )
    sunk = get_success_data(api_client.get_payment(membership["id"], TEST_USERS["ops_headers"]))
    assert sunk["status"] == "FORFEITED"
    assert sunk["refundable_remaining_cents"] == 0


def test_itinerary_cancellation_is_terminal_and_expires_the_watch():
    """PRD §3.10: "The itinerary becomes `CANCELLED`, which is terminal. Any
    watch on it is expired with `watch_armed` cleared, and every freeze on it in
    `DRAFT`, `HELD` or `FROZEN` is cancelled under the forfeiture rule".

    Design: Difficulty/transitive_cascade/cascade_cancel_to_forfeit_to_payment_sink_to_posture_release
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 10000, seats_left=6)
    itinerary = read_itinerary(itinerary["id"])
    watch = get_success_data(
        api_client.arm_watch(itinerary["id"],
                             {"expected_itinerary_version": itinerary["version"]},
                             TEST_USERS["traveler_headers"])
    )
    allow_freezes(route)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)

    get_success_data(
        api_client.cancel_itinerary(itinerary["id"], {"cancel_reason": "TRAVELER_PLAN_CHANGE"},
                                    TEST_USERS["traveler_headers"])
    )
    cancelled = read_itinerary(itinerary["id"])
    expired_watch = get_success_data(
        api_client.get_watch(watch["id"], TEST_USERS["traveler_headers"])
    )

    assert cancelled["travel_status"] == "CANCELLED"
    assert cancelled["watch_armed"] is False
    assert expired_watch["notification_status"] == "EXPIRED"
    assert read_freeze(freeze["id"])["status"] == "CANCELLED"


def allow_freezes(route: dict) -> None:
    """Raise the route's exposure ceiling so a freeze activation is not capped.

    Several cascades place a second freeze on a route that already carries one;
    the per-route cap binds on activation, so the ceiling is widened first.
    """
    get_success_data(
        api_client.update_route(route["id"], {"max_guarantee_exposure_cents": 500000},
                                TEST_USERS["admin_headers"])
    )