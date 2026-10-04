"""Fuel delivery pricing: the composite blend and its two bases."""
from test_helpers import validate_success
from test_helpers.fixtures import (
    FUEL_COORDINATOR,
    create_site,
    get_site,
    schedule_indexed_delivery,
    set_clock,
)


def test_scheduled_indexed_blend_prices_hedged_and_index_legs_separately():
    """PRD §2.6: "`hedged_fraction` of the volume
    is priced at `fixed_price_cents_per_therm` and the remainder at `index_rate_cents_per_therm`,
    the two products are computed first and summed, and the sum is rounded once to four decimal
    places using round half up."
    PRD §3.3: "While the
    delivery is still `DELIVERY_SCHEDULED` or `DELIVERY_IN_TRANSIT`, and whenever a projection
    evaluates it as a what-if, the blend instead uses the site's current
    `gas_commodity_rate_cents_per_therm` as its index leg".

    Design: Difficulty/dual_variant_calc/composite_hedged_index_price_replayed_vs_delivered
    """
    set_clock()
    site = create_site()
    delivery = schedule_indexed_delivery(site["id"])

    assert delivery["lifecycle_state"] == "DELIVERY_SCHEDULED"
    # The hedged leg keeps the declared fixed price; the index leg of a still
    # scheduled load is the site's current gas commodity rate, not the captured
    # index the load will carry once it is receipted (PRD §3.3).
    index_leg = site["gas_commodity_rate_cents_per_therm"]
    expected = round(0.5 * 4.20 + 0.5 * index_leg, 4)
    assert delivery["effective_commodity_rate_cents_per_therm"] == expected, (
        "the blend is hedged_fraction * fixed_price + (1 - hedged_fraction) * "
        f"the site's current gas index, got {delivery['effective_commodity_rate_cents_per_therm']}"
    )


def test_dispatching_an_indexed_load_freezes_it_onto_the_delivered_basis():
    """PRD §3.3: "Once the delivery is in `DELIVERY_CONFIRMED` or `DELIVERY_SETTLED`, the blend is
    priced against the `index_rate_cents_per_therm` that was captured when it was confirmed, and
    later movement in the gas market does not re-price it — a receipted load is a fact."

    Design: Difficulty/dual_variant_calc/composite_hedged_index_price_replayed_vs_delivered
    """
    set_clock()
    site = create_site()
    delivery = schedule_indexed_delivery(site["id"])
    frozen_at_schedule = delivery["effective_commodity_rate_cents_per_therm"]

    dispatched = validate_success(
        _dispatch(site["id"], delivery["id"]),
    )
    assert dispatched["lifecycle_state"] == "DELIVERY_IN_TRANSIT"
    assert (
        dispatched["effective_commodity_rate_cents_per_therm"] == frozen_at_schedule
    ), "a dispatched load keeps the exact blend it was created with"


def test_scheduling_a_delivery_draws_its_volume_off_the_site_pool():
    """PRD §2.6: "because a delivery is a reservation before it is a physical event, the
    system treats scheduling a delivery as an immediate draw against the pool".

    Design: Difficulty/dual_variant_calc/composite_hedged_index_price_replayed_vs_delivered
    """
    set_clock()
    site = create_site()
    opening = site["draw_position_therms"]
    delivery = schedule_indexed_delivery(site["id"], volume_therms=200000)

    after = get_site(site["id"])
    assert after["draw_position_therms"] == opening - delivery["volume_therms"], (
        "scheduling draws the volume immediately; expected "
        f"{opening - delivery['volume_therms']}, got {after['draw_position_therms']}"
    )


def test_confirming_an_indexed_load_rebases_the_site_fuel_index():
    """PRD §3.3: "the site's
    `current_avoided_fuel_cost_cents_per_therm` is set to that delivery's
    `effective_commodity_rate_cents_per_therm`".

    Design: Difficulty/dual_variant_calc/composite_hedged_index_price_replayed_vs_delivered
    """
    set_clock()
    site = create_site()
    delivery = schedule_indexed_delivery(site["id"])
    _dispatch(site["id"], delivery["id"])
    confirmed = validate_success(
        _confirm(site["id"], delivery["id"]),
    )

    after = get_site(site["id"])
    assert confirmed["lifecycle_state"] == "DELIVERY_CONFIRMED"
    assert after["current_avoided_fuel_cost_cents_per_therm"] == confirmed[
        "effective_commodity_rate_cents_per_therm"
    ], "the site's fuel index must now read the receipted load's blend"


# --- local plumbing (kept out of test_helpers: these are thin pass-throughs) ---
def _dispatch(site_id, delivery_id):
    from test_helpers import api_client

    return api_client.dispatch_fuel_delivery(site_id, delivery_id, FUEL_COORDINATOR)


def _confirm(site_id, delivery_id):
    from test_helpers import api_client

    return api_client.confirm_fuel_delivery(site_id, delivery_id, FUEL_COORDINATOR)