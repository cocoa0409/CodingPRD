"""
The five ordered steps of the guideline worksheet, read one step at a time.

Each scenario runs the worksheet on two or three cases that differ in exactly one
income figure or one boolean, so the step under test is the only thing that can
account for the difference between the results — the imputation branch, the band
search, the credit-then-floor ordering and the reserve guard in turn.
"""

from typing import Any, Dict, Optional

from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_START


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _calculated_two_child_order(
    ssn_cp: str,
    ssn_ncp: str,
    cp_income: Optional[int],
    ncp_income: Optional[int],
    ncp_income_source: str = "VERIFIED_WAGE_RECORD",
    supports_second_family: bool = False,
) -> Dict[str, Any]:
    """
    Open a two-child case for one pair of income figures and run the worksheet
    once, returning the calculated order.

    Passing ``None`` for an income omits the field and its provenance entirely,
    which is the difference between an absent figure and an unverified one.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Dana Alvarez",
            "ssn_last4": ssn_cp,
            "monthly_gross_income_cents": cp_income,
        },
        ncp_overrides={
            "full_name": "Rene Alvarez",
            "ssn_last4": ssn_ncp,
            "monthly_gross_income_cents": ncp_income,
            "income_verification_source": ncp_income_source,
            "supports_second_family": supports_second_family,
            "has_valid_drivers_license": True,
        },
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    fx.open_paternity_action(scenario.case_id, "PRESUMED_MARITAL")
    order = fx.draft_order(
        scenario.case_id,
        order_type="CURRENT_SUPPORT",
        origin_state_code="MN",
        effective_date="2026-08-01",
    )
    return fx.calculate_order(order["id"])


# ---------------------------------------------------------------------------
# Step one: the imputation branch is keyed on the provenance, not on absence
# ---------------------------------------------------------------------------


def test_01_an_unverified_reported_income_imputes_exactly_as_an_absent_one_does():
    """
    A reported 300,000 whose source is `NONE` produces the same order as no figure.

    The obligor's figure is imputed rather than taken whenever the obligor's `monthly_gross_income_cents` is absent *or* the obligor's `income_verification_source` is `NONE`: in that case the obligor is credited with an imputed monthly income of 182,000 cents, which is 1,820 dollars a month, and `imputation_applied` is recorded as true.

    Whichever figures are actually used are written to `guideline_cp_income_cents` and `guideline_ncp_income_cents`, so a reader can always see what the run was based on.

    Design: Corner/calculations/guideline_imputation_applies_when_income_is_unverified
    """
    absent = _calculated_two_child_order("6101", "6102", 100000, None)
    unverified = _calculated_two_child_order(
        "6103", "6104", 100000, 300000, ncp_income_source="NONE"
    )

    for order in (absent, unverified):
        assert order["imputation_applied"] is True
        assert order["guideline_ncp_income_cents"] == 182000
        assert order["guideline_cp_income_cents"] == 100000
        # Combined 282000 is inside band one, whose two-child rate is 0.28.
        assert order["guideline_basic_obligation_cents"] == 78960
        # round_half_up_4dp(182000 / 282000) = round_half_up_4dp(0.645390...).
        assert order["guideline_ncp_share_ratio"] == 0.6454
        # round_half_up(78960 * 0.6454), below the available 182000 - 113200.
        assert order["guideline_monthly_cents"] == 50961

    # The reported 300000 never entered the formula at all.
    assert unverified["guideline_monthly_cents"] == absent["guideline_monthly_cents"]


def test_02_a_self_reported_figure_is_honoured_and_produces_a_different_order():
    """
    The same 300,000, stamped `SELF_REPORTED`, is used instead of the imputed figure.

    Otherwise the obligor's stored figure is used and `imputation_applied` is recorded as false.

    The band chosen is the first band whose ceiling is greater than or equal to the combined income, so a combined income of exactly 400,000 cents still falls in the first band and a combined income of exactly 800,000 cents still falls in the second.

    Design: Corner/calculations/guideline_imputation_applies_when_income_is_unverified
    """
    unverified = _calculated_two_child_order(
        "6103", "6104", 100000, 300000, ncp_income_source="NONE"
    )
    self_reported = _calculated_two_child_order(
        "6105", "6106", 100000, 300000, ncp_income_source="SELF_REPORTED"
    )

    assert self_reported["imputation_applied"] is False
    assert self_reported["guideline_ncp_income_cents"] == 300000
    # Combined 400000 sits on the band-one ceiling, so the rate is still 0.28.
    assert self_reported["guideline_basic_obligation_cents"] == 112000
    assert self_reported["guideline_ncp_share_ratio"] == 0.75
    assert self_reported["guideline_monthly_cents"] == 84000

    # The only difference between the two chains is the enum value.
    assert self_reported["guideline_monthly_cents"] != unverified["guideline_monthly_cents"]


# ---------------------------------------------------------------------------
# Step five: the reserve guard, on both sides of zero available income
# ---------------------------------------------------------------------------


def test_03_available_income_of_exactly_zero_still_collapses_to_the_minimum_order():
    """
    An obligor earning the reserve to the cent pays the statutory minimum.

    The obligor's available income is the obligor's guideline income minus a self-support reserve of 113,200 cents, which is 1,132 dollars a month.

    If that available amount is zero or negative, the guideline result is the statutory minimum order of 5,000 cents — 50 dollars a month — regardless of anything computed earlier.

    Design: Corner/calculations/self_support_reserve_floors_the_order_at_the_minimum
    """
    below = _calculated_two_child_order("6111", "6112", 200000, 100000)
    exactly = _calculated_two_child_order("6113", "6114", 200000, 113200)

    assert below["guideline_basic_obligation_cents"] == 84000
    assert below["guideline_ncp_share_ratio"] == 0.3333
    # The proportional share of 27997 is discarded: available is -13200.
    assert below["guideline_monthly_cents"] == 5000

    # Combined 313200; round_half_up(313200 * 0.28) and 113200 / 313200.
    assert exactly["guideline_basic_obligation_cents"] == 87696
    assert exactly["guideline_ncp_share_ratio"] == 0.3614
    # Available is exactly zero, and the guard is "zero or negative".
    assert exactly["guideline_monthly_cents"] == 5000
    assert exactly["imputation_applied"] is False


def test_04_one_cent_of_available_income_skips_the_minimum_entirely():
    """
    113,201 leaves one cent available, and one cent is the whole order.

    Otherwise the guideline result is the smaller of the credited share and the available amount.

    Design: Corner/calculations/self_support_reserve_floors_the_order_at_the_minimum
    """
    exactly = _calculated_two_child_order("6113", "6114", 200000, 113200)
    one_cent_more = _calculated_two_child_order("6115", "6116", 200000, 113201)

    # round_half_up(313201 * 0.28) lands on the same 87696.
    assert one_cent_more["guideline_basic_obligation_cents"] == 87696
    assert one_cent_more["guideline_ncp_share_ratio"] == 0.3614
    assert one_cent_more["multi_family_credit_cents"] == 0
    # min(credited share 31693, available 1); the minimum never enters this branch.
    assert one_cent_more["guideline_monthly_cents"] == 1

    # One extra cent of income cuts the order from 5000 to 1.
    assert exactly["guideline_monthly_cents"] > one_cent_more["guideline_monthly_cents"]


# ---------------------------------------------------------------------------
# Step four: the credit lands before the floor, and rounds half up
# ---------------------------------------------------------------------------


def test_05_the_credit_is_taken_first_so_the_floor_never_sees_the_raw_share():
    """
    Crediting then flooring gives 38,132; flooring then crediting would give 33,896.

    When the obligor's `supports_second_family` is true, `multi_family_credit_cents` is the obligor's share multiplied by 0.10 — a ten percent credit — rounded half up to whole cents; when it is false, `multi_family_credit_cents` is zero.

    Because the credit is applied before the reserve floor rather than after it, crediting first and then flooring produces a different number from flooring first, and the earlier order is the one this system implements.

    Design: Corner/calculations/multi_family_credit_is_applied_before_the_reserve
    """
    order = _calculated_two_child_order(
        "6121", "6122", 200000, 151333, supports_second_family=True
    )

    # Combined 351333; round_half_up(351333 * 0.28) = round_half_up(98373.24).
    assert order["guideline_basic_obligation_cents"] == 98373
    assert order["guideline_ncp_share_ratio"] == 0.4307
    # round_half_up(42369 * 0.10) = round_half_up(4236.9).
    assert order["multi_family_credit_cents"] == 4237
    # min(after-credit 38132, available 151333 - 113200 = 38133).
    assert order["guideline_monthly_cents"] == 38132
    assert order["guideline_monthly_cents"] != 33896


def test_06_a_credit_of_exactly_half_a_cent_rounds_away_from_zero():
    """
    5,000.5 cents of credit becomes 5,001, not the even 5,000.

    The default across the guideline worksheet, the interest engine, the waiver computation, the mandatory-deduction derivation and the arrears-recovery derivation is round half up to the nearest whole cent — a value ending in exactly half a cent rounds away from zero.

    The credited share is the obligor's share minus that credit.

    Design: Corner/calculations/multi_family_credit_is_applied_before_the_reserve
    """
    order = _calculated_two_child_order(
        "6123", "6124", 200000, 200040, supports_second_family=True
    )

    # Combined 400040 clears the band-one ceiling, so the rate is 0.25.
    assert order["guideline_basic_obligation_cents"] == 100010
    # round_half_up_4dp(200040 / 400040) = round_half_up_4dp(0.500049...).
    assert order["guideline_ncp_share_ratio"] == 0.5
    assert order["multi_family_credit_cents"] == 5001
    # 50005 - 5001, far below the available 200040 - 113200.
    assert order["guideline_monthly_cents"] == 45004
    # 45005 is the bankers-rounding answer, where 5000.5 falls to the even 5000.
    assert order["guideline_monthly_cents"] != 45005


# ---------------------------------------------------------------------------
# Step two: the band ceiling is inclusive and only one rate is ever applied
# ---------------------------------------------------------------------------


def test_07_a_combined_income_of_exactly_the_ceiling_stays_in_the_first_band():
    """
    400,000 keeps the 0.28 rate; 400,001 drops to 0.25 and costs 9,000 less.

    Within the chosen band the rate depends on the number of children on the case, with three or more children all sharing one rate: in the first band the rate is 0.20 for one child, 0.28 for two children and 0.33 for three or more; in the second band 0.17, 0.25 and 0.30; in the third band 0.14, 0.21 and 0.25.

    The basic obligation, written to `guideline_basic_obligation_cents`, is the combined income multiplied by that rate, rounded half up to whole cents.

    Design: Corner/calculations/income_band_boundary_at_four_hundred_thousand_stays_in_band_one
    """
    on_the_ceiling = _calculated_two_child_order("6131", "6132", 100000, 300000)
    one_cent_over = _calculated_two_child_order("6133", "6134", 100001, 300000)

    assert on_the_ceiling["guideline_cp_income_cents"] == 100000
    assert on_the_ceiling["guideline_ncp_income_cents"] == 300000
    assert on_the_ceiling["guideline_basic_obligation_cents"] == 112000
    assert on_the_ceiling["guideline_ncp_share_ratio"] == 0.75
    assert on_the_ceiling["guideline_monthly_cents"] == 84000

    # round_half_up(400001 * 0.25) = round_half_up(100000.25).
    assert one_cent_over["guideline_basic_obligation_cents"] == 100000
    assert one_cent_over["guideline_ncp_share_ratio"] == 0.75
    assert one_cent_over["guideline_monthly_cents"] == 75000

    assert on_the_ceiling["guideline_monthly_cents"] - one_cent_over["guideline_monthly_cents"] == 9000


def test_08_the_chosen_rate_applies_to_the_whole_combined_figure():
    """
    There is no blending: the second band's rate is charged on all 400,001.

    **Step two** selects one rate from a tiered table using the combined income — the sum of the two guideline incomes.

    Three bands exist: the first band covers combined incomes up to and including 400,000 cents a month, the second covers combined incomes up to and including 800,000 cents, and the third is unbounded.

    Design: Corner/calculations/income_band_boundary_at_four_hundred_thousand_stays_in_band_one
    """
    one_cent_over = _calculated_two_child_order("6133", "6134", 100001, 300000)

    combined = (
        one_cent_over["guideline_cp_income_cents"]
        + one_cent_over["guideline_ncp_income_cents"]
    )
    assert combined == 400001
    assert one_cent_over["guideline_basic_obligation_cents"] == 100000
    # 103000 is the blended figure 0.28 on the first 400000 plus 0.25 on the cent.
    assert one_cent_over["guideline_basic_obligation_cents"] != 103000
    assert one_cent_over["imputation_applied"] is False
