"""Money compositions whose rounding points and evaluation order are pinned.

Wage harmonisation rounds each component before it sums them, the consideration
chain picks its synergy tier from the gross and never from the net, and the
retention bonus multiplies an already-rounded award before a two-sided clamp.
"""

from test_helpers import assertions as a
from test_helpers.api_client import ApiClient
from test_helpers.constants import (
    DEAL_STATUS_BOARD_REVIEW,
    OFFER_STATUS_DRAFT,
    RETENTION_BONUS_CAP_CENTS,
    RETENTION_BONUS_FLOOR_CENTS,
    ROLE_CODE_BILLER,
    ROLE_CODE_FRONT_DESK,
    ROLE_CODE_PRACTICE_MANAGER,
    ROLE_CODE_RN,
)
from test_helpers.fixtures import (
    board_review_deal,
    create_acquisition,
    create_offer,
    read_acquisition,
    reset_clock,
)

# A BILLER on 5,282,350 cents with 104 PTO hours: raw components 158470.5 and
# 132058.75, each rounded half up on its own before the sum.
BILLER_WAGE_CENTS = 5_282_350
BILLER_UPLIFT_CENTS = 158_471
BILLER_PTO_CENTS = 132_059
BILLER_OFFERED_CENTS = 5_572_880
BILLER_SUM_THEN_ROUND_CENTS = 5_572_879
BILLER_BONUS_CENTS = 557_288

# The pinned consideration chain on a purchase price of 1,450,000,000 cents.
PURCHASE_PRICE_CENTS = 1_450_000_000
INTEGRATION_RESERVE_CENTS = 50_750_000
GROSS_CENTS = 1_500_750_000
SYNERGY_BPS = 275
SYNERGY_CENTS = 41_270_625
NET_CENTS = 1_459_479_375
RETIERED_FROM_NET_CENTS = 1_478_858_184
TIER_TWO_CEILING_CENTS = 1_500_000_000


def test_wage_components_are_rounded_before_they_are_summed(api: ApiClient):
    """Each wage component is rounded on its own, then added.

    PRD: "Four steps run at creation time, and the rounding points are pinned
    because rounding the sum instead of the components can differ by a cent."

    Design: Difficulty/combinatorial_formula/staff_wage_rounding_per_component_then_sum
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    offer = create_offer(
        api,
        acquisition["id"],
        staff_member_name="Rosa Delgado",
        role_code=ROLE_CODE_BILLER,
        legacy_annual_wage_cents=BILLER_WAGE_CENTS,
        legacy_pto_hours=104,
        credited_service_months=84,
        offer_expires_on="2026-10-31",
    )

    a.assert_money_equals(
        offer["uplift_component_cents"], BILLER_UPLIFT_CENTS, "uplift_component_cents"
    )
    a.assert_money_equals(offer["pto_component_cents"], BILLER_PTO_CENTS, "pto_component_cents")
    a.assert_money_equals(
        offer["offered_annual_wage_cents"], BILLER_OFFERED_CENTS, "offered_annual_wage_cents"
    )
    assert offer["offered_annual_wage_cents"] != BILLER_SUM_THEN_ROUND_CENTS
    assert (
        offer["offered_annual_wage_cents"]
        == BILLER_WAGE_CENTS
        + offer["uplift_component_cents"]
        + offer["pto_component_cents"]
    )


def test_drafting_an_offer_reserves_nothing_from_the_retention_pool(api: ApiClient):
    """A drafted offer computes its money but commits none of it.

    PRD: "A drafted offer lands in `DRAFT`, with `extended_on` and `accepted_on`
    both null, and the retention pool is untouched — a draft reserves nothing."

    Design: Difficulty/combinatorial_formula/staff_wage_rounding_per_component_then_sum
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    offer = create_offer(
        api,
        acquisition["id"],
        staff_member_name="Rosa Delgado",
        role_code=ROLE_CODE_BILLER,
        legacy_annual_wage_cents=BILLER_WAGE_CENTS,
        legacy_pto_hours=104,
        credited_service_months=84,
        offer_expires_on="2026-10-31",
    )

    a.assert_status(offer, OFFER_STATUS_DRAFT)
    assert offer["wage_floor_applied"] is False
    a.assert_money_equals(
        offer["retention_bonus_cents"], BILLER_BONUS_CENTS, "retention_bonus_cents"
    )
    a.assert_fields_null(offer, "extended_on", "accepted_on")

    refreshed = read_acquisition(api, acquisition["id"])
    a.assert_retention_pool(refreshed, 3_000_000, 0, 3_000_000)


def test_synergy_tier_is_keyed_on_the_gross_never_on_the_net(api: ApiClient):
    """The tier comes from the gross figure and is not re-derived from the net.

    PRD: "The tier is selected once, from the gross, and is never re-derived
    from the net."

    Design: Difficulty/combinatorial_formula/net_consideration_tier_pinned_to_gross_not_net
    """
    deal = board_review_deal(api)
    acquisition = read_acquisition(api, deal["acquisition"]["id"])

    a.assert_status(acquisition, DEAL_STATUS_BOARD_REVIEW, "deal_status")
    a.assert_consideration_chain(
        acquisition,
        PURCHASE_PRICE_CENTS,
        INTEGRATION_RESERVE_CENTS,
        GROSS_CENTS,
        SYNERGY_BPS,
        SYNERGY_CENTS,
        NET_CENTS,
    )
    assert acquisition["net_consideration_cents"] != RETIERED_FROM_NET_CENTS
    assert acquisition["gross_consideration_cents"] >= TIER_TWO_CEILING_CENTS
    assert acquisition["net_consideration_cents"] < TIER_TWO_CEILING_CENTS


def test_board_review_pins_the_opinion_and_copies_its_concluded_value(api: ApiClient):
    """Pinning and the purchase price are the first two side effects of board review.

    PRD: "`purchase_price_cents` is copied from that pinned opinion's
    `concluded_value_cents`."

    Design: Difficulty/combinatorial_formula/net_consideration_tier_pinned_to_gross_not_net
    """
    deal = board_review_deal(api)
    acquisition = read_acquisition(api, deal["acquisition"]["id"])

    a.assert_money_equals(
        deal["fmv"]["concluded_value_cents"], PURCHASE_PRICE_CENTS, "concluded_value_cents"
    )
    a.assert_money_equals(
        acquisition["purchase_price_cents"], PURCHASE_PRICE_CENTS, "purchase_price_cents"
    )
    a.assert_money_equals(deal["cr"]["concluded_value_cents"], 0, "concluded_value_cents")
    assert acquisition["tail_coverage_required"] is False
    a.assert_money_equals(acquisition["tail_premium_cents"], 0, "tail_premium_cents")


def test_criticality_multiplier_applies_to_the_already_rounded_award(api: ApiClient):
    """An RN lands strictly inside the clamp band on the twice-rounded award.

    PRD: "A criticality multiplier is then applied to that **already-rounded**
    raw award: 12500 basis points — a twenty-five percent premium — when
    `role_code` is `RN`, `BILLER`, or `PRACTICE_MANAGER`, and 10000 basis points,
    leaving the award unchanged, for `MA` and `FRONT_DESK`."

    Design: Difficulty/combinatorial_formula/retention_bonus_nested_min_max_with_criticality
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    offer = create_offer(
        api,
        acquisition["id"],
        staff_member_name="Dana Whitfield",
        role_code=ROLE_CODE_RN,
        legacy_annual_wage_cents=8_000_000,
        legacy_pto_hours=80,
        credited_service_months=130,
        offer_expires_on="2026-10-31",
    )

    a.assert_money_equals(offer["uplift_component_cents"], 480_000, "uplift_component_cents")
    a.assert_money_equals(offer["pto_component_cents"], 153_846, "pto_component_cents")
    a.assert_money_equals(
        offer["offered_annual_wage_cents"], 8_633_846, "offered_annual_wage_cents"
    )
    assert offer["wage_floor_applied"] is False
    a.assert_money_equals(offer["retention_bonus_cents"], 1_187_154, "retention_bonus_cents")
    assert RETENTION_BONUS_FLOOR_CENTS < offer["retention_bonus_cents"] < RETENTION_BONUS_CAP_CENTS


def test_bonus_clamp_raises_to_the_floor_and_lowers_to_the_cap(api: ApiClient):
    """Both sides of the clamp fire, in the order the floor precedes the cap.

    PRD: "Finally the result is clamped in a fixed order: the floor of 100000
    cents is applied first, raising any smaller award up to it, and the cap of
    1500000 cents is applied second, bringing any larger award down to it."

    Design: Difficulty/combinatorial_formula/retention_bonus_nested_min_max_with_criticality
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    front_desk = create_offer(
        api,
        acquisition["id"],
        staff_member_name="Tomas Reyes",
        role_code=ROLE_CODE_FRONT_DESK,
        legacy_annual_wage_cents=3_400_000,
        legacy_pto_hours=0,
        credited_service_months=6,
        offer_expires_on="2026-10-31",
    )
    practice_manager = create_offer(
        api,
        acquisition["id"],
        staff_member_name="Grace Okonkwo",
        role_code=ROLE_CODE_PRACTICE_MANAGER,
        legacy_annual_wage_cents=12_000_000,
        legacy_pto_hours=160,
        credited_service_months=200,
        offer_expires_on="2026-10-31",
    )

    a.assert_money_equals(
        front_desk["offered_annual_wage_cents"], 3_600_000, "offered_annual_wage_cents"
    )
    assert front_desk["wage_floor_applied"] is True
    a.assert_money_equals(
        front_desk["retention_bonus_cents"], RETENTION_BONUS_FLOOR_CENTS, "retention_bonus_cents"
    )
    assert front_desk["retention_bonus_cents"] != 72_000

    a.assert_money_equals(
        practice_manager["offered_annual_wage_cents"], 13_421_538, "offered_annual_wage_cents"
    )
    assert practice_manager["wage_floor_applied"] is False
    a.assert_money_equals(
        practice_manager["retention_bonus_cents"],
        RETENTION_BONUS_CAP_CENTS,
        "retention_bonus_cents",
    )
    assert practice_manager["retention_bonus_cents"] != 1_845_461

    refreshed = read_acquisition(api, acquisition["id"])
    a.assert_retention_pool(refreshed, 3_000_000, 0, 3_000_000)
