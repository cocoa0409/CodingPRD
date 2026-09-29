"""Dual-variant calculations: yield-to-worst selection and the gross spread fork.

Two families of two-variant arithmetic live here, both taken from the difficulty
design index:

* ``tranche_yield_to_worst_variant_divergence`` -- the same actuarial discounting
  run to two horizons on one callable maturity, where the *lower* rounded price
  wins, so a premium coupon prices to the call while a discount coupon with an
  identical call feature stays priced to maturity.
* ``gross_spread_negotiated_versus_competitive_divergence`` -- two deals carrying
  byte-identical maturity schedules disclose different underwriter compensation
  purely because ``gross_spread_basis`` was frozen differently at designation.

Every figure asserted below is either a constant transcribed from PRD.md or the
output of an ``expected_*`` helper that restates a PRD formula once.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_money,
    assert_price,
    expected_competitive_gross_spread,
    expected_gross_spread_per_bond,
    expected_issue_price_total,
    expected_negotiated_gross_spread,
    expected_net_proceeds,
    to_decimal,
)
from test_helpers.constants import (
    CANONICAL_EXPECTED_PAR_USD,
    CANONICAL_ISSUE_PRICE_TOTAL_USD,
    CANONICAL_TRANCHE_PRINCIPAL_USD,
    COMPETITIVE_GROSS_SPREAD_PER_BOND_USD,
    COMPETITIVE_GROSS_SPREAD_TOTAL_USD,
    COMPETITIVE_NET_PROCEEDS_USD,
    COMPETITIVE_WINNING_BID_PRICE_PCT,
    DISCOUNT_COUPON_PCT,
    DISCOUNT_PRICE_TO_CALL_PCT,
    DISCOUNT_PRICE_TO_MATURITY_PCT,
    NEGOTIATED_COMPONENT_TOTAL_PER_BOND_USD,
    NEGOTIATED_GROSS_SPREAD_PER_BOND_USD,
    NEGOTIATED_GROSS_SPREAD_TOTAL_USD,
    NEGOTIATED_NET_PROCEEDS_UNINSURED_USD,
    TRANCHE_2_CALL_PERIODS,
    TRANCHE_2_PERIODS,
    TRANCHE_2_PRICE_TO_CALL_PCT,
    TRANCHE_2_PRICE_TO_MATURITY_PCT,
)
from test_helpers.types import DealStatus, GrossSpreadBasis

# The one-cent-free delta the design index pins between the two spread bases:
# 111,700.00 competitive against 87,500.00 negotiated on the same schedule.
SPREAD_BASIS_DELTA_USD = (
    to_decimal(COMPETITIVE_GROSS_SPREAD_TOTAL_USD)
    - to_decimal(NEGOTIATED_GROSS_SPREAD_TOTAL_USD)
)


def _deal_for_one_callable_maturity(client):
    """Participants plus a DRAFT deal authorising a single 5,000,000 maturity.

    PRD section 3.2 prices a maturity the moment it is added, so nothing beyond
    deal creation is needed before the trigger call.
    """
    ctx = fx.participants(client)
    deal = fx.create_deal(
        client,
        ctx.issuer_id,
        ctx.advisor_firm_id,
        ctx.issuer_headers,
        expected_par_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
    )
    ctx.deal = deal
    ctx.deal_id = deal["id"]
    return ctx


def _long_callable_tranche_payload(**overrides):
    """The forty-period maturity callable at par after twenty (PRD section 3.2)."""
    return f.canonical_tranche_2_payload(
        sequence_number=1,
        principal_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
        **overrides,
    )


def test_premium_callable_maturity_is_marketed_at_the_lower_call_price(client):
    """PRD 3.2: "When `is_callable` is true and `price_to_call_pct` is strictly
    less than `price_to_maturity_pct`, `reoffering_price_pct` takes the value of
    `price_to_call_pct` and `is_priced_to_call` becomes true."

    Design: Difficulty/dual_variant_calc/tranche_yield_to_worst_variant_divergence
    """
    ctx = _deal_for_one_callable_maturity(client)

    response = client.create_maturity_tranche(
        ctx.deal_id, _long_callable_tranche_payload(), ctx.advisor_headers
    )
    tranche = validate_success(response, 201)

    # PRD section 3.2 stores both intermediate period counts.
    assert tranche["periods_to_maturity"] == TRANCHE_2_PERIODS
    assert tranche["periods_to_call"] == TRANCHE_2_CALL_PERIODS

    # Each variant is rounded independently, and the rounded figures are compared.
    assert_price(
        tranche["price_to_maturity_pct"],
        TRANCHE_2_PRICE_TO_MATURITY_PCT,
        "price_to_maturity_pct",
    )
    assert_price(
        tranche["price_to_call_pct"], TRANCHE_2_PRICE_TO_CALL_PCT, "price_to_call_pct"
    )
    assert to_decimal(tranche["price_to_call_pct"]) < to_decimal(
        tranche["price_to_maturity_pct"]
    ), "the premium coupon's to-call price must be the strictly lower variant"

    # The strictly-lower test therefore selects the to-call variant.
    assert_price(
        tranche["reoffering_price_pct"],
        TRANCHE_2_PRICE_TO_CALL_PCT,
        "reoffering_price_pct",
    )
    assert tranche["is_priced_to_call"] is True


def test_discount_callable_maturity_stays_priced_to_maturity(client):
    """PRD 3.2: "In every other case — including an exact tie between the two
    rounded prices — `reoffering_price_pct` takes the value of
    `price_to_maturity_pct` and `is_priced_to_call` stays false."

    Design: Difficulty/dual_variant_calc/tranche_yield_to_worst_variant_divergence
    """
    ctx = _deal_for_one_callable_maturity(client)

    response = client.create_maturity_tranche(
        ctx.deal_id,
        _long_callable_tranche_payload(coupon_rate_pct=DISCOUNT_COUPON_PCT),
        ctx.advisor_headers,
    )
    tranche = validate_success(response, 201)

    # The identical call feature, at a discount coupon, reverses which variant is
    # lower: 86.322 to maturity against 91.824 to the call (PRD section 3.2).
    assert_price(
        tranche["price_to_maturity_pct"],
        DISCOUNT_PRICE_TO_MATURITY_PCT,
        "price_to_maturity_pct",
    )
    assert_price(
        tranche["price_to_call_pct"], DISCOUNT_PRICE_TO_CALL_PCT, "price_to_call_pct"
    )
    assert to_decimal(tranche["price_to_call_pct"]) > to_decimal(
        tranche["price_to_maturity_pct"]
    ), "the discount coupon's to-call price must not be the lower variant"

    assert_price(
        tranche["reoffering_price_pct"],
        DISCOUNT_PRICE_TO_MATURITY_PCT,
        "reoffering_price_pct",
    )
    assert tranche["is_priced_to_call"] is False


def test_negotiated_basis_builds_the_spread_from_the_per_bond_components(
    priced_negotiated_deal,
):
    """PRD 3.8: "On the negotiated basis, the per-bond component total is
    `takedown_per_bond_usd` plus `management_fee_per_bond_usd` plus
    `expenses_per_bond_usd`; for each tranche in ascending `sequence_number`, the
    tranche's bond count is its `principal_amount_usd` divided by one thousand and
    its spread is that bond count multiplied by the component total, rounded to two
    decimal places; `Deal.gross_spread_total_usd` is the sum of those rounded
    per-tranche spreads."

    Design: Difficulty/dual_variant_calc/gross_spread_negotiated_versus_competitive_divergence
    """
    ctx = priced_negotiated_deal
    deal = ctx.deal

    assert deal["gross_spread_basis"] == GrossSpreadBasis.NEGOTIATED
    assert deal["status"] == DealStatus.PRICED

    # The reoffering scale is common to both bases (PRD section 3.8, first step).
    assert_money(
        deal["issue_price_total_usd"],
        expected_issue_price_total(ctx.tranches),
        "issue_price_total_usd",
    )
    assert_money(
        deal["issue_price_total_usd"],
        CANONICAL_ISSUE_PRICE_TOTAL_USD,
        "issue_price_total_usd",
    )

    # Built up from 5.000 + 2.500 + 1.250 per bond over two 5,000,000 tranches.
    assert_money(
        deal["gross_spread_total_usd"],
        expected_negotiated_gross_spread(
            ctx.tranches, NEGOTIATED_COMPONENT_TOTAL_PER_BOND_USD
        ),
        "gross_spread_total_usd",
    )
    assert_money(
        deal["gross_spread_total_usd"],
        NEGOTIATED_GROSS_SPREAD_TOTAL_USD,
        "gross_spread_total_usd",
    )
    assert_price(
        deal["gross_spread_per_bond_usd"],
        expected_gross_spread_per_bond(
            NEGOTIATED_GROSS_SPREAD_TOTAL_USD, CANONICAL_EXPECTED_PAR_USD
        ),
        "gross_spread_per_bond_usd",
    )
    assert_price(
        deal["gross_spread_per_bond_usd"],
        NEGOTIATED_GROSS_SPREAD_PER_BOND_USD,
        "gross_spread_per_bond_usd",
    )

    # This deal carries no enhancement, so the money identity leaves the whole
    # remainder with the issuer (PRD section 2.9).
    assert_money(
        deal["net_proceeds_to_issuer_usd"],
        expected_net_proceeds(
            CANONICAL_ISSUE_PRICE_TOTAL_USD, NEGOTIATED_GROSS_SPREAD_TOTAL_USD, 0
        ),
        "net_proceeds_to_issuer_usd",
    )
    assert_money(
        deal["net_proceeds_to_issuer_usd"],
        NEGOTIATED_NET_PROCEEDS_UNINSURED_USD,
        "net_proceeds_to_issuer_usd",
    )


def test_competitive_basis_backs_the_spread_out_of_the_winning_bid(
    priced_competitive_deal,
):
    """PRD 3.8: "On the competitive basis, bid proceeds are `Deal.par_amount_usd`
    multiplied by `winning_bid_price_pct` divided by one hundred, rounded to two
    decimal places, and `Deal.gross_spread_total_usd` is
    `Deal.issue_price_total_usd` less those bid proceeds, rounded to two decimal
    places — the spread is what the underwriter keeps between the reoffering scale
    and the price it paid the issuer."

    Design: Difficulty/dual_variant_calc/gross_spread_negotiated_versus_competitive_divergence
    """
    ctx = priced_competitive_deal
    deal = ctx.deal

    assert deal["gross_spread_basis"] == GrossSpreadBasis.COMPETITIVE
    assert deal["status"] == DealStatus.PRICED

    # The same schedule, so the same reoffering scale as the negotiated deal.
    assert_money(
        deal["issue_price_total_usd"],
        expected_issue_price_total(ctx.tranches),
        "issue_price_total_usd",
    )
    assert_money(
        deal["issue_price_total_usd"],
        CANONICAL_ISSUE_PRICE_TOTAL_USD,
        "issue_price_total_usd",
    )

    assert_money(
        deal["gross_spread_total_usd"],
        expected_competitive_gross_spread(
            CANONICAL_EXPECTED_PAR_USD,
            COMPETITIVE_WINNING_BID_PRICE_PCT,
            CANONICAL_ISSUE_PRICE_TOTAL_USD,
        ),
        "gross_spread_total_usd",
    )
    assert_money(
        deal["gross_spread_total_usd"],
        COMPETITIVE_GROSS_SPREAD_TOTAL_USD,
        "gross_spread_total_usd",
    )
    assert_price(
        deal["gross_spread_per_bond_usd"],
        expected_gross_spread_per_bond(
            COMPETITIVE_GROSS_SPREAD_TOTAL_USD, CANONICAL_EXPECTED_PAR_USD
        ),
        "gross_spread_per_bond_usd",
    )
    assert_price(
        deal["gross_spread_per_bond_usd"],
        COMPETITIVE_GROSS_SPREAD_PER_BOND_USD,
        "gross_spread_per_bond_usd",
    )

    # Net proceeds fall back to the bid proceeds the issuer was actually paid.
    assert_money(
        deal["net_proceeds_to_issuer_usd"],
        COMPETITIVE_NET_PROCEEDS_USD,
        "net_proceeds_to_issuer_usd",
    )


def test_identical_schedules_diverge_only_by_the_frozen_spread_basis(
    priced_negotiated_deal, priced_competitive_deal
):
    """PRD 3.6: "`gross_spread_basis` in particular is frozen at designation time
    and selects which compensation formula applies when the deal is priced."

    Design: Difficulty/dual_variant_calc/gross_spread_negotiated_versus_competitive_divergence
    """
    negotiated = priced_negotiated_deal.deal
    competitive = priced_competitive_deal.deal

    assert negotiated["gross_spread_basis"] == GrossSpreadBasis.NEGOTIATED
    assert competitive["gross_spread_basis"] == GrossSpreadBasis.COMPETITIVE

    # Byte-identical maturity schedules, so the reoffering scale is shared.
    assert_money(
        competitive["issue_price_total_usd"],
        negotiated["issue_price_total_usd"],
        "issue_price_total_usd across the two bases",
    )
    assert_money(
        negotiated["issue_price_total_usd"],
        CANONICAL_ISSUE_PRICE_TOTAL_USD,
        "issue_price_total_usd",
    )

    # The whole difference in disclosed compensation is the basis, not the schedule.
    observed_delta = to_decimal(competitive["gross_spread_total_usd"]) - to_decimal(
        negotiated["gross_spread_total_usd"]
    )
    assert_money(
        observed_delta,
        SPREAD_BASIS_DELTA_USD,
        "competitive less negotiated gross_spread_total_usd",
    )
