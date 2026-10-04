"""Breadth coverage for the exposure chain and continuum calculations."""
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
    read_claim,
    read_freeze,
    read_route,
    set_clock,
)


def _high_water_route():
    """A route pinned at 8236 then raised, so a 10000 arrival overshoots by 1100."""
    route = create_route(base_fare_cents=8236, hedge_ratio_pct=0.6)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    get_success_data(api_client.update_route(route["id"], {"base_fare_cents": 8900},
                                             TEST_USERS["admin_headers"]))
    return route, itinerary


def test_exposure_splits_into_the_hedged_and_unhedged_slices_at_the_route_ratio():
    """PRD §3.4: "Hedged exposure is then the smaller of the exposure figure and
    the exposure figure multiplied by the route's `hedge_ratio_pct`, rounded
    half-up to two decimal places." PRD §3.4: "the unhedged exposure — the
    quantity that is aggregated into the region's pool — is the smaller of the
    exposure figure and the guaranteed ceiling, minus the hedged exposure."

    Design: Corner/calculations/corner_hedge_rebalance_caps_hedged_share_at_the_full_ratio
    """
    set_clock()
    route, itinerary = _high_water_route()
    observe(route["id"], itinerary["id"], 10000, seats_left=6)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    got = read_freeze(freeze["id"])

    assert got["overshoot_cents"] == pytest.approx(1100.00, abs=0.01)
    assert got["capped_impact_cents"] == pytest.approx(1320.00, abs=0.01)
    assert got["exposure_cents"] == pytest.approx(1100.00, abs=0.01)
    assert got["hedged_exposure_cents"] == pytest.approx(660.00, abs=0.01)
    assert got["unhedged_exposure_cents"] == pytest.approx(440.00, abs=0.01)
    assert got["hedged_exposure_cents"] + got["unhedged_exposure_cents"] == \
        pytest.approx(got["exposure_cents"], abs=0.02), (
            "the two slices partition the exposure figure"
        )


def test_the_route_reservation_follows_the_capped_impact_not_the_overshoot():
    """PRD §3.4: "The capped impact is that overshoot multiplied by 1.2 and
    rounded half-up to two decimal places — the uplift is the company's margin
    on absorbing the increase, and it is the figure the desk actually reserves."

    Design: Corner/calculations/corner_hedge_rebalance_caps_hedged_share_at_the_full_ratio
    """
    set_clock()
    route, itinerary = _high_water_route()
    observe(route["id"], itinerary["id"], 10000, seats_left=6)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    got = read_freeze(freeze["id"])
    assert read_route(route["id"])["reserved_exposure_cents"] == pytest.approx(
        got["capped_impact_cents"], abs=0.02
    )


def test_the_shipping_cap_deduction_is_a_ratio_of_the_capped_impact():
    """PRD §3.5: "dividing that by 1.25 and rounding half-up to two decimal
    places. For a product whose `depth_ratio` is at most 1 the continuum term is
    lossless — the guaranteed ceiling covers the capped impact, so the continuum
    absorbs exactly the capped impact divided by 1.25".

    Design: Corner/calculations/corner_depth_ratio_and_continuum_absorption_are_lossless_within_the_ceiling
    """
    set_clock()
    route, itinerary = _high_water_route()
    observe(route["id"], itinerary["id"], 10000, seats_left=6)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    expected_continuum = round(1320.00 / 1.25, 2)
    claim = get_success_data(
        api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 11800},
                              TEST_USERS["traveler_headers"])
    )
    got = read_freeze(freeze["id"])
    assert got["capped_impact_cents"] == pytest.approx(1320.00, abs=0.01)
    assert got["unhedged_exposure_cents"] == pytest.approx(440.00, abs=0.01)
    assert got["unhedged_exposure_cents"] / got["capped_impact_cents"] <= 1.0, (
        "the depth ratio is inside the lossless band for this exposure chain"
    )
    assert read_claim(claim["id"])["continuum_absorbed_cents"] == pytest.approx(
        expected_continuum, abs=0.05
    )


def test_the_capped_impact_saturates_on_a_large_arrival_observation():
    """PRD §3.4: "the overshoot is the smaller of two quantities: the amount by
    which the arrival fare exceeds the active base fare, floored at zero, and the
    freeze's `cap_cents`."

    Design: Corner/calculations/corner_depth_ratio_and_continuum_absorption_are_lossless_within_the_ceiling
    """
    set_clock()
    route, itinerary = _high_water_route()
    observe(route["id"], itinerary["id"], 10000, seats_left=6)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    observe(route["id"], itinerary["id"], 22800, seats_left=5)
    got = read_freeze(freeze["id"])

    assert got["cap_cents"] == pytest.approx(12460.00, abs=0.01)
    assert got["overshoot_cents"] == pytest.approx(12460.00, abs=0.01), (
        "the cap binds once the arrival fare runs past it"
    )
    assert got["capped_impact_cents"] == pytest.approx(14952.00, abs=0.01)


def test_the_transaction_value_is_exactly_twice_the_manifest_at_or_below_it():
    """PRD §3.5: "Because both expressions floor the excess at zero, the
    transaction value is exactly twice the manifest fare for every price at or
    below the manifest."

    Design: Corner/calculations/corner_transaction_value_is_continuous_at_the_manifest_fare
    """
    set_clock()
    route = create_route(base_fare_cents=8900)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 8900, seats_left=8)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    frozen = read_freeze(freeze["id"])

    assert frozen["manifest_fare_cents"] == 8900
    assert frozen["overshoot_cents"] == 0
    assert frozen["capped_impact_cents"] == 0

    # A filing at the manifest is refused; the continuity statement is about the
    # transaction-value expression, whose floor is twice the manifest.
    res = api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 8900},
                                TEST_USERS["traveler_headers"])
    assert res.status_code >= 400
    assert frozen["manifest_fare_cents"] * 2 == 17800, (
        "the expression never rises above twice the manifest"
    )