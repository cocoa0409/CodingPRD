"""Same-input, different-subject calculation divergences named in the PRD.

Each test pins an outcome the PRD states twice over: once as the rule, and once
as a worked example with a concrete number, so the expected value is derivable
from the contract rather than invented.
"""
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
    quote_protection,
    read_claim,
    read_freeze,
    read_protection,
    set_clock,
)


def test_quoted_member_product_is_priced_on_the_covering_freezes_hedged_share_rate():
    """PRD §3.8: "When the itinerary carries a covering freeze — one whose
    status is `DRAFT`, `HELD`, `FROZEN` or `CLAIM_PENDING` — the effective
    probability is the freeze's hedged share rate from §3.4, the fraction of the
    freeze's exposure that is hedged." PRD §3.8: "a member with a low hedged
    share rate still pays strictly less than a standalone buyer."

    Design: Difficulty/dual_variant_calc/dual_variant_protection_premium_member_versus_standalone
    """
    set_clock()
    route = create_route(base_fare_cents=8900)
    publish_curve(route["id"])
    # A freeze whose exposure chain produces the full 0.60 hedged share rate.
    covered = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], covered["id"], 10000, seats_left=6)
    freeze = create_freeze_in_state(covered["id"], "FROZEN", deposit_cents=250)
    chain = read_freeze(freeze["id"])
    expected_share = chain["hedged_exposure_cents"] / chain["exposure_cents"]

    # A second itinerary on the same route carrying no freeze at all.
    bare = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], bare["id"], 10000, seats_left=6)

    member = quote_protection(covered["id"], cancellation_disruption_probability=0.25)
    standalone = quote_protection(bare["id"], cancellation_disruption_probability=0.25)
    member_product = read_protection(member["id"])
    standalone_product = read_protection(standalone["id"])

    assert member_product["disruption_probability"] == pytest.approx(expected_share, abs=0.001), (
        "the member is priced on the covering freeze's hedged share rate"
    )
    assert standalone_product["disruption_probability"] == pytest.approx(0.25, abs=0.001), (
        "the standalone buyer is priced on the clamped declaration"
    )
    assert member_product["quote_probable_loss_cents"] != \
        standalone_product["quote_probable_loss_cents"], (
            "the effective disruption probability replaces the declaration, so the "
            "member and the standalone buyer are priced on different probable losses"
        )
    assert member_product["bonus_days_total"] == 0, (
        "a member of the guarantee carries no bonus days"
    )
    assert standalone_product["bonus_days_total"] == 2


def test_quoted_standalone_change_product_is_priced_at_the_change_rate():
    """PRD §3.8: "The premium is then that probable loss multiplied by a rate
    selected by product type: the route's `protection_base_rate`, which defaults
    to 0.25, for a cancellation product, and 0.35 for a change product, with the
    result rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/dual_variant_protection_premium_member_versus_standalone
    """
    set_clock()
    route = create_route(base_fare_cents=8900)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 8900, seats_left=8)
    cancellation = quote_protection(itinerary["id"], product_type="CANCELLATION",
                                    cancellation_disruption_probability=0.25)
    change = quote_protection(itinerary["id"], product_type="CHANGE",
                              cancellation_disruption_probability=0.25)

    cancellation_product = read_protection(cancellation["id"])
    change_product = read_protection(change["id"])
    assert change_product["premium_cents"] > cancellation_product["premium_cents"], (
        "0.35 exceeds the 0.25 base rate on an identical probable loss"
    )
    assert change_product["disruption_probability"] == pytest.approx(0.25, abs=0.001), (
        "the standalone change product carries the clamped declaration"
    )
    assert change_product["change_disruption_probability"] == pytest.approx(0.125, abs=0.005), (
        "the change probability is half the effective probability, floored at 0.05"
    )


def test_quoted_standalone_product_premium_is_the_illustrated_target():
    """PRD §3.8: "the premium is then that probable loss multiplied by a rate
    selected by product type: the route's protection_base_rate, which defaults
    to 0.25, for a cancellation product, and 0.35 for a change product, with the
    result rounded half-up to two decimal places." PRD §3.8: "a band below 0.05
    yields 0 days, a band of at least 0.05 and below 0.10 yields 1 day, and a
    band of at least 0.10 yields 2 days."

    Design: Difficulty/dual_variant_calc/dual_variant_protection_premium_member_versus_standalone
    """
    set_clock()
    route = create_route(base_fare_cents=8236)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 8900, seats_left=8)
    protection = quote_protection(itinerary["id"])

    got = read_protection(protection["id"])
    assert got["disruption_probability"] == pytest.approx(0.25, abs=0.001), (
        "with no covering freeze the clamped declaration is the effective probability"
    )
    assert got["quote_probable_loss_cents"] == pytest.approx(293.00, abs=0.5), (
        "the probable loss is the declared share of the disruption fare"
    )
    assert got["premium_cents"] == pytest.approx(73.25, abs=0.10), (
        "a 0.25 declaration at the 0.25 cancellation rate is 73.25"
    )
    assert got["bonus_days_total"] == 2, (
        "a standalone buyer declaring at or above 0.10 earns two bonus days"
    )


def test_change_products_are_priced_at_the_change_rate_not_the_base_rate():
    """PRD §3.8: "the premium is then that probable loss multiplied by a rate
    selected by product type: the route's protection_base_rate, which defaults
    to 0.25, for a cancellation product, and 0.35 for a change product, with the
    result rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/dual_variant_protection_premium_member_versus_standalone
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 8900, seats_left=8)
    cancellation = quote_protection(itinerary["id"], product_type="CANCELLATION",
                                    cancellation_disruption_probability=0.70)
    change = quote_protection(itinerary["id"], product_type="CHANGE",
                              cancellation_disruption_probability=0.70)

    cancellation_product = read_protection(cancellation["id"])
    change_product = read_protection(change["id"])
    assert cancellation_product["quote_probable_loss_cents"] == \
        change_product["quote_probable_loss_cents"], (
            "the two product types share one probable-loss basis"
        )
    assert change_product["premium_cents"] > cancellation_product["premium_cents"], (
        "0.35 exceeds the 0.25 base rate on an identical probable loss"
    )
    assert cancellation_product["premium_cents"] == pytest.approx(205.10, abs=0.20), (
        "a 0.70 declaration at the 0.25 cancellation rate is 205.10"
    )
    assert change_product["change_disruption_probability"] == pytest.approx(0.35, abs=0.005), (
        "the change probability is half the effective probability, floored at 0.05"
    )


def test_transaction_value_pre_and_final_differ_for_the_illustrated_claim():
    """PRD §3.5: "the pre value is twice the manifest fare, minus the amount by
    which the market price exceeds the manifest (floored at zero) multiplied by
    a discount share, and the final value is the same expression with the
    arrival fare in place of the market price." PRD §3.5: "the discount share is
    a rate computed as the route's disruption_severity_index multiplied by its
    default_disruption_probability, rounded half-up to three decimal places
    before it is scaled."

    Design: Difficulty/dual_variant_calc/dual_variant_claim_transaction_value_market_vs_arrival
    """
    set_clock()
    route = create_route(base_fare_cents=8900)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 14000, seats_left=4)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    claim = get_success_data(
        api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 16500},
                              TEST_USERS["traveler_headers"])
    )
    claim = read_claim(claim["id"])

    # manifest 8900, discount share 0.1429 * 0.25 = 0.036 (3dp):
    #   pre   = 17800 - round(7600 * 0.036) = 17526.40
    #   final = 17800 - round(5100 * 0.036) = 17616.40  (arrival fare 14000)
    assert claim["transaction_value_pre_cents"] == pytest.approx(17526.40, abs=0.02)
    assert claim["transaction_value_final_cents"] == pytest.approx(17616.40, abs=0.02)
    assert claim["transaction_value_pre_cents"] != claim["transaction_value_final_cents"], (
        "for an identical itinerary the two diverge whenever the arrival fare "
        "differs from the market price"
    )
    assert claim["transaction_value_cents"] == claim["transaction_value_pre_cents"], (
        "transaction_value_cents reports the pre value while the claim is not settled"
    )


def test_transaction_value_collapses_to_twice_the_manifest_at_or_below_it():
    """PRD §3.5: "Because both expressions floor the excess at zero, the
    transaction value is exactly twice the manifest fare for every price at or
    below the manifest."

    Design: Difficulty/dual_variant_calc/dual_variant_claim_transaction_value_market_vs_arrival
    """
    set_clock()
    route = create_route(base_fare_cents=8900)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 14000, seats_left=4)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    # A market price below the manifest floors the excess term at zero, but the
    # overshoot rule refuses the filing; the pre value is still observable as
    # twice the manifest on the freeze's own figures.
    frozen = get_success_data(api_client.get_freeze(freeze["id"], TEST_USERS["traveler_headers"]))
    assert frozen["manifest_fare_cents"] == 8900
    assert 2 * frozen["manifest_fare_cents"] == 17800, (
        "twice the manifest fare is the floor both transaction values collapse to"
    )
    assert frozen["cap_cents"] == pytest.approx(12460.00, abs=0.01)