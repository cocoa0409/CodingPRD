"""Conserved quantities: money buckets and aggregate exposure."""
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    create_freeze_in_state,
    create_itinerary,
    create_route,
    get_success_data,
    observe,
    publish_curve,
    raise_exposure_ceiling,
    read_freeze,
    read_route,
    round_half_up,
    set_clock,
)


def test_the_deposit_is_conserved_across_its_custody_buckets_mid_flight():
    """PRD §3.6: "Each accrual moves the newly credited delta out of
    `custody_held_cents` and into the attributed bucket, which is what keeps the
    custody bucket equal to the unattributed remainder of the deposit at all
    times." PRD §3.6: "sets `deposit_attributed_cents` to the deposit multiplied
    by that day count and divided by 14, rounded half-up to two decimal places."

    Design: Difficulty/compensating_invariant/invariant_deposit_and_custody_conserved_across_expiry
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=5000)

    advance_clock("2026-09-06T00:00:00Z")
    held = read_freeze(freeze["id"])
    expected_attributed = round_half_up(5000 * 5 / 14)

    assert held["membership_days_elapsed"] == 5, (
        "the whole days between the freeze date and the clock, truncated"
    )
    assert held["deposit_attributed_cents"] == pytest.approx(expected_attributed, abs=0.01)
    assert held["custody_held_cents"] + held["custody_return_pending_cents"] + \
        held["deposit_attributed_cents"] == pytest.approx(5000.00, abs=0.02), (
            "the three buckets reconstitute the deposit exactly"
        )


def test_expiry_moves_custody_without_changing_the_deposit_total():
    """PRD §3.6: "Expiry moves the freeze to `EXPIRED`, adds the held custody to
    `custody_return_pending_cents` and zeroes `custody_held_cents`, clears the
    itinerary's `guarantee_locked` flag, decrements the route's
    `open_freeze_count`, and runs the attribution reconciliation".

    Design: Difficulty/compensating_invariant/invariant_deposit_and_custody_conserved_across_expiry
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=5000)

    advance_clock("2026-09-06T00:00:00Z")
    before = read_freeze(freeze["id"])
    expected_attributed = round_half_up(5000 * 5 / 14)

    expired = get_success_data(
        api_client.expire_freeze(freeze["id"], {}, TEST_USERS["system_operator_headers"])
    )
    assert expired["status"] == "EXPIRED"
    assert expired["custody_held_cents"] == 0
    assert expired["custody_return_pending_cents"] == pytest.approx(
        5000 - expected_attributed, abs=0.02)
    assert expired["deposit_attributed_cents"] == pytest.approx(expected_attributed, abs=0.01), (
        "the attribution already accrued is not rolled back"
    )
    assert expired["custody_held_cents"] + expired["custody_return_pending_cents"] + \
        expired["deposit_attributed_cents"] == pytest.approx(5000.00, abs=0.02), (
            "the invariant holds before and after the expiry"
        )
    assert before["deposit_attributed_cents"] == pytest.approx(
        expired["deposit_attributed_cents"], abs=0.01)


def test_the_route_reservation_equals_the_sum_of_the_freeze_capped_impacts():
    """PRD §2.9: "a `reserved_exposure_cents`, which is the sum, over every
    freeze not in `EXPIRED`, `CANCELLED` or `CONVERTED`, of the larger of that
    freeze's `capped_impact_cents` and the largest `payout_cents` among its
    claims that are not `REJECTED` or `SETTLED_WITH_PURCHASE`".

    Design: Difficulty/compensating_invariant/invariant_reserved_exposure_released_on_conversion
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary_a = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary_a["id"], 10000, seats_left=6)
    freeze_a = create_freeze_in_state(itinerary_a["id"], "FROZEN", deposit_cents=250)

    itinerary_b = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary_b["id"], 10000, seats_left=6)
    freeze_b = create_freeze_in_state(itinerary_b["id"], "FROZEN", deposit_cents=250)

    each = read_freeze(freeze_a["id"])["capped_impact_cents"]
    assert each == pytest.approx(1320.00, abs=0.01)
    route_now = read_route(route["id"])
    assert route_now["reserved_exposure_cents"] == pytest.approx(each * 2, abs=0.01), (
        "the reservation is the sum over the route's in-service freezes"
    )


def test_converting_one_freeze_releases_exactly_its_slice_of_the_reservation():
    """PRD §3.6: "The freeze's reserved exposure is released." PRD §2.9: "a
    `reserved_exposure_cents`, which is the sum, over every freeze not in
    `EXPIRED`, `CANCELLED` or `CONVERTED`, of the larger of that freeze's
    `capped_impact_cents` and the largest `payout_cents` among its claims".

    Design: Difficulty/compensating_invariant/invariant_reserved_exposure_released_on_conversion
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    # The route's war chest starts at 0 (PRD §2.14), so the per-route ceiling on
    # the resulting reservation is raised before the freezes are sized.
    route = raise_exposure_ceiling(route)
    itinerary_a = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary_a["id"], 10000, seats_left=6)
    freeze_a = create_freeze_in_state(itinerary_a["id"], "FROZEN", deposit_cents=250)

    itinerary_b = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary_b["id"], 10000, seats_left=6)
    freeze_b = create_freeze_in_state(itinerary_b["id"], "FROZEN", deposit_cents=250)

    each = read_freeze(freeze_a["id"])["capped_impact_cents"]
    converted = get_success_data(
        api_client.convert_freeze(freeze_a["id"], {"expected_freeze_version": freeze_a["version"]},
                                  TEST_USERS["traveler_headers"])
    )
    assert converted["status"] == "CONVERTED"
    assert read_route(route["id"])["reserved_exposure_cents"] == pytest.approx(each, abs=0.02), (
        "the converted freeze's slice is released rather than reassigned"
    )
    assert read_freeze(freeze_b["id"])["status"] == "FROZEN", (
        "the sibling freeze keeps its own reservation"
    )