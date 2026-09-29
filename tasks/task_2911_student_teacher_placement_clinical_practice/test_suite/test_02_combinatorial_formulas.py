"""Where the rounding happens, and which subtotal a tier is read from.

Both money formulas in this contract are pinned not only in their inputs but in
the *order* of their steps: the weekly stipend rate is rounded before it meets
the week count, and the travel allowance tier is chosen from the mileage
subtotal before the allowance is added to it.  Each test asserts the pinned
figure and names the figure a mis-ordered implementation would produce.
"""
from test_helpers import (
    assert_agreement_ledger,
    assert_stipend,
    confirm,
    read_agreement,
    setup_proposed_placement,
)

FAR_CANDIDATE = {"home_grid_x": 10, "home_grid_y": 47}
TWO_WEEK_REQUEST = {"weeks_scheduled": 2, "max_commute_miles": 40}
EIGHT_WEEK_REQUEST = {"weeks_scheduled": 8}


def test_the_weekly_rate_is_rounded_before_it_is_multiplied_by_the_weeks(api):
    """12345 at 5 percent is 12962 a week and 181468 across 14 weeks.

    PRD §3.6: "With a weekly rate of 12345 cents and a teacher on two
    consecutive terms, the rate becomes 12345 multiplied by 1.05, or 12962.25
    cents, which rounds half up to `stipend_weekly_cents` of 12962; a 14-week
    term accrues 12962 times 14, or 181468 cents gross. Rounding the product
    instead of the rate would yield 181472 and is wrong."

    Design: Difficulty/combinatorial_formula/stipend_weekly_rate_rounded_before_weeks_multiplication
    """
    scenario = setup_proposed_placement(api)

    placement = confirm(api, scenario.placement_id)

    assert_stipend(placement, variant="PROVISIONAL", weekly_cents=12962,
                   weeks_credited=14, gross_cents=181468)
    assert placement["stipend_gross_cents"] != 181472, (
        "181472 is round_half_up(12345 * 1.05 * 14) — the product rounded")
    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=0, seats_committed=1,
                            stipend_committed_cents=181468)


def test_the_longevity_tier_multiplies_the_rate_before_that_rounding(api):
    """A teacher on three consecutive terms is worth 13580 a week.

    PRD §3.6: "A teacher with no consecutive terms keeps 12345 per week; a
    teacher with three or more earns 12345 multiplied by 1.10, or 13579.5,
    which rounds half up to 13580 per week."

    Design: Difficulty/combinatorial_formula/stipend_weekly_rate_rounded_before_weeks_multiplication
    """
    scenario = setup_proposed_placement(api,
                                        teacher={"consecutive_terms_hosted": 3})

    placement = confirm(api, scenario.placement_id)

    assert_stipend(placement, variant="PROVISIONAL", weekly_cents=13580,
                   weeks_credited=14, gross_cents=190120)
    assert placement["stipend_gross_cents"] != 190113, (
        "190113 is round_half_up(12345 * 1.10 * 14) — the product rounded")


def test_the_travel_tier_is_read_from_the_pre_allowance_subtotal(api):
    """A 37-mile commute for two weeks reimburses 53546, not 52059.

    PRD §3.6: "a 37-mile commute credited for 2 weeks bills 740 miles for a
    subtotal of 49580 cents, which sits in the first tier, so the allowance is
    8 percent of 49580, or 3966.4 cents rounding to 3966, for a total of 53546
    cents — re-selecting the tier from that 53546 total would wrongly apply 5
    percent and produce 52059."

    Design: Difficulty/combinatorial_formula/travel_allowance_tier_pinned_to_pre_allowance_subtotal
    """
    scenario = setup_proposed_placement(api, candidate=dict(FAR_CANDIDATE),
                                        request=dict(TWO_WEEK_REQUEST))

    placement = confirm(api, scenario.placement_id)

    assert placement["commute_miles"] == 37, (
        "Manhattan distance from (10, 47) to (10, 10)")
    assert_stipend(placement, variant="PROVISIONAL", weeks_credited=2,
                   gross_cents=25924, travel_cents=53546)
    assert placement["travel_reimbursement_cents"] != 52059, (
        "52059 applies the 5 percent tier read off the post-allowance total")


def test_a_subtotal_above_the_first_tier_takes_the_five_percent_band(api):
    """An eight-week 14-mile term bills 75040 and reimburses 78792.

    PRD §3.6: "an 8-week placement bills 1120 miles, 75040 cents, 3752 cents
    and 78792 cents".

    Design: Difficulty/combinatorial_formula/travel_allowance_tier_pinned_to_pre_allowance_subtotal
    """
    scenario = setup_proposed_placement(api, request=dict(EIGHT_WEEK_REQUEST))

    placement = confirm(api, scenario.placement_id)

    assert placement["commute_miles"] == 14, (
        "Manhattan distance from (2, 4) to (10, 10)")
    assert_stipend(placement, variant="PROVISIONAL", weeks_credited=8,
                   gross_cents=103696, travel_cents=78792)
    assert placement["travel_reimbursement_cents"] != 81043, (
        "81043 would apply the 8 percent tier of the lower band")
