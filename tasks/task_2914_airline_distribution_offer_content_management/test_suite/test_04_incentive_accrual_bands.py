"""Marginal incentive bands and the inclusive tier boundaries they sit beside."""

from test_helpers import (
    TIER_1,
    TIER_2,
    fixtures as fx,
)

BIG_BASIS = "YTIER01"
SMALL_BASIS = "YTIER02"


def _plain_channel(api):
    """Markup 0 and multiplier 1.0, so an order's revenue equals the filed fare."""
    return fx.create_full_channel(
        api,
        channel_code="CH_TIER",
        content_markup_pct=0.0,
        incentive_multiplier=1.0,
        monthly_platform_fee_cents=1000000,
        per_message_cost_cents=5,
        per_segment_fee_cents=0,
        required_disclosure_codes=[],
    )


def _sell(api, channel, partner_name, iata_code, fare_basis_code, base_amount_cents):
    partner = fx.create_alpha_agency(api, partner_name=partner_name, iata_code=iata_code)
    agreement = fx.create_signed_agreement(
        api,
        partner["id"],
        channel["id"],
        partner["version"],
        proposed_incentive_pct=0.025,
        incentive_cap_cents=10000000,
    )
    filing = fx.create_active_filing(
        api,
        fare_basis_code=fare_basis_code,
        base_amount_cents=base_amount_cents,
        refundable=True,
    )
    offer = fx.construct_offer(api, channel["id"], partner["id"], filing["id"])
    assert offer["total_cents"] == base_amount_cents
    fx.publish_offer(api, offer["id"])
    order = fx.create_order(api, offer["id"])
    fx.capture_payment(api, order["id"], base_amount_cents)
    return agreement, order


def test_balance_exactly_at_the_first_ceiling_enters_tier_two_with_an_empty_band(api):
    """PRD §3.3: "`incentive_tier` is derived from the same qualifying revenue: `TIER_3`
    when the revenue is at or above 20,000,000 cents, otherwise `TIER_2` when it is at
    or above 5,000,000 cents, otherwise `TIER_1`. Both boundaries are inclusive on
    entry, so a balance of exactly 5,000,000 cents already labels the agreement
    `TIER_2` while placing zero cents in the second band."
    PRD §3.3: "The second band is the qualifying revenue less 5,000,000 cents, floored
    at zero and then capped at 15,000,000 cents — the width between the two ceilings —
    and earns 0.025."

    Design: Difficulty/boundary_precision_check/incentive_tier_two_entry_is_inclusive_at_tier_one_ceiling
    """
    channel = _plain_channel(api)
    agreement, _order = _sell(
        api, channel, "Beta Travel GmbH", "12345671", BIG_BASIS, 5000000
    )

    ledger = fx.read_agreement(api, agreement["id"])
    assert ledger["cumulative_net_revenue_cents"] == 5000000
    assert ledger["incentive_tier"] == TIER_2
    # First band 5,000,000 * 0.010 = 50,000; the second band is empty at the boundary.
    assert ledger["incentive_accrued_cents"] == 50000
    assert ledger["tier_downgrade_count"] == 0


def test_one_cent_below_the_ceiling_keeps_tier_one_at_the_same_rounded_accrual(api):
    """PRD §3.3: "The first band is the lesser of the qualifying revenue and 5,000,000
    cents, and earns 0.010."
    PRD §3.3: "That capped value is then rounded half up to whole cents, and the result
    is stored in `incentive_accrued_cents`."

    Design: Difficulty/boundary_precision_check/incentive_tier_two_entry_is_inclusive_at_tier_one_ceiling
    """
    channel = _plain_channel(api)
    at_ceiling, _order_a = _sell(
        api, channel, "Beta Travel GmbH", "12345671", BIG_BASIS, 5000000
    )
    below_ceiling, _order_b = _sell(
        api, channel, "Gamma Travel GmbH", "12345672", SMALL_BASIS, 4999999
    )

    below = fx.read_agreement(api, below_ceiling["id"])
    assert below["cumulative_net_revenue_cents"] == 4999999
    assert below["incentive_tier"] == TIER_1
    # 4,999,999 * 0.010 = 49,999.99, rounded half up once at the end.
    assert below["incentive_accrued_cents"] == 50000

    at = fx.read_agreement(api, at_ceiling["id"])
    # The same rounded accrual, a different tier label: one cent moves only the label.
    assert at["incentive_accrued_cents"] == below["incentive_accrued_cents"]
    assert at["incentive_tier"] == TIER_2
    assert below["incentive_tier"] == TIER_1

    channel_now = fx.read_channel(api, channel["id"])
    assert channel_now["booking_count"] == 2
    # Two messages at 5 cents plus both signed accruals.
    assert channel_now["activity_cost_cents"] == 100010
    assert channel_now["cost_per_booking_flat_cents"] == 500000
    assert channel_now["cost_per_booking_activity_cents"] == 50005
