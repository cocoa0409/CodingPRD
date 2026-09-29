"""Pricing at underwriting: the additive rate stack, the four-way term floor and
the inclusive leverage cap (PRD §3.4).

An aged single-wide in the worst wind zone exercises every spread in the stack
at once, and two loans 417 cents apart straddle the leverage cap exactly.
"""

from test_helpers import (
    ApiErrorId,
    assert_valuation_breakdown,
    fixtures,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"

# ─── The aged single-wide of the rate-and-term instance ───
AGED_BORROWER = {
    "full_name": "Marcus Ojeda",
    "credit_score": 745,
    "monthly_income_cents": 410000,
    "state_code": "GA",
}
AGED_UNIT = {
    "manufacturer": "Fleetwood",
    "model_year": 1996,
    "width_class": "SINGLE_WIDE",
    "square_feet": 1080,
    "condition_grade": "FAIR",
    "installation_type": "PIER_AND_ANCHOR",
    "wind_zone": 3,
    "land_parcel_apn": "112-08-119",
    "land_county": "Bulloch",
    "land_value_cents": 1400000,
}
AGED_PRINCIPAL_CENTS = 1500000
# Thirty years of age at 350 bps is 10500 bps, capped at 7000, so 3000 bps of
# guide value survives 1080 sqft * 4500 c/sqft at the single-wide multiplier.
AGED_BOOK_BASE_CENTS = 1458000
AGED_CONDITION_CENTS = -174960
AGED_LOCATION_CENTS = 131220
AGED_INSTALLATION_CENTS = 250000
AGED_CERTIFIED_CENTS = 1664260
AGED_LTV_BPS = 9013
# 875 base + 50 private land + 175 personal property - 125 credit tier
# + 150 leverage tier + 60 wind surcharge.
AGED_APR_BPS = 1185
AGED_TERM_MONTHS = 120
AGED_REQUESTED_TERM_MONTHS = 240

# ─── The two loans straddling the leverage cap ───
CAP_CERTIFIED_CENTS = 5776403
PRINCIPAL_AT_CAP_CENTS = 5487583
PRINCIPAL_OVER_CAP_CENTS = 5488000
LTV_CAP_BPS = 9500
AT_CAP_APR_BPS = 1425
AT_CAP_TERM_MONTHS = 240


def _aged_single_wide_application(api):
    """A 1996 single-wide on the applicant's own land with a priced-ready loan."""
    scenario = fixtures.setup_private_land_collateral(
        api,
        clock=CLOCK,
        borrower_overrides=AGED_BORROWER,
        unit_overrides=AGED_UNIT,
        record_documents=False,
    )
    scenario["valuation"] = fixtures.create_certified_valuation(
        api, scenario["unit"]["id"], scenario["guide"]["id"], "ORIGINATION"
    )
    scenario["loan"] = fixtures.open_loan(
        api,
        scenario["borrower"]["id"],
        scenario["unit"]["id"],
        scenario["valuation"]["id"],
        AGED_PRINCIPAL_CENTS,
        AGED_REQUESTED_TERM_MONTHS,
    )
    return scenario


def _community_collateral_with_two_applications(api):
    """One certified valuation of 5776403 cents carrying two draft applications."""
    scenario = fixtures.setup_community_collateral(
        api, clock=CLOCK, agreement="EXECUTED"
    )
    valuation = fixtures.create_certified_valuation(
        api, scenario["unit"]["id"], scenario["guide"]["id"], "ORIGINATION"
    )
    assert valuation["certified_value_cents"] == CAP_CERTIFIED_CENTS
    scenario["valuation"] = valuation
    scenario["loan_at_cap"] = fixtures.open_loan(
        api,
        scenario["borrower"]["id"],
        scenario["unit"]["id"],
        valuation["id"],
        PRINCIPAL_AT_CAP_CENTS,
        AT_CAP_TERM_MONTHS,
    )
    scenario["loan_over_cap"] = fixtures.open_loan(
        api,
        scenario["borrower"]["id"],
        scenario["unit"]["id"],
        valuation["id"],
        PRINCIPAL_OVER_CAP_CENTS,
        AT_CAP_TERM_MONTHS,
    )
    return scenario


def test_apr_stack_sums_every_spread_including_the_wind_surcharge_before_clamping(api):
    """PRD §3.4: "Rate is then assembled as an additive stack of integer
    basis-point spreads, and only after the entire stack has been summed is a
    two-sided clamp applied — never term by term."
    PRD §3.4: "Finally, a wind-exposure surcharge of 60 basis points is added
    when, and only when, the unit's `wind_zone` is 3 **and** its
    `installation_type` is `PIER_AND_ANCHOR`; a zone-3 unit on a permanent
    foundation, or a piered unit in zone 1 or 2, takes no surcharge."

    Design: Difficulty/combinatorial_formula/rate_and_term_nested_clamp_by_remaining_useful_life
    """
    scenario = _aged_single_wide_application(api)

    loan = validate_success(
        api.submit_underwriting(scenario["loan"]["id"], fixtures.ANALYST)
    )

    assert loan["underwriting_state"] == "UNDERWRITING"
    assert loan["ltv_bps"] == AGED_LTV_BPS
    assert loan["apr_bps"] == AGED_APR_BPS, (
        "875 base + 50 private land + 175 personal property - 125 credit tier "
        "+ 150 leverage tier + 60 wind surcharge"
    )


def test_term_is_bound_by_remaining_useful_life_not_by_the_requested_term(api):
    """PRD §3.4: "Term is the smallest survivor of four independent caps, every
    one of which applies."
    PRD §3.4: "The fourth is the collateral's remaining useful life in months,
    computed as forty years less the age implied by the valuation — that is,
    forty less the difference between the valuation's `valuation_year` and the
    unit's `model_year` — multiplied by twelve, and floored at zero so an
    over-age unit contributes a cap of zero rather than a negative one."

    Design: Difficulty/combinatorial_formula/rate_and_term_nested_clamp_by_remaining_useful_life
    """
    scenario = _aged_single_wide_application(api)
    assert scenario["loan"]["requested_term_months"] == AGED_REQUESTED_TERM_MONTHS

    loan = validate_success(
        api.submit_underwriting(scenario["loan"]["id"], fixtures.ANALYST)
    )

    assert loan["term_months"] == AGED_TERM_MONTHS, (
        "a 1996 unit valued in 2026 has ten years of useful life left, so the "
        "fourth cap of 120 months defeats the requested 240, the private-land "
        "placement cap of 300 and the personal-property cap of 240"
    )
    assert loan["underwriting_state"] == "UNDERWRITING", (
        "120 months clears the 60-month floor, so the submission stands"
    )


def test_depreciation_cap_leaves_thirty_percent_of_guide_value_on_an_aged_unit(api):
    """PRD §3.3: "Depreciation in basis points is that age in years multiplied by
    the guide's `annual_depreciation_bps`, but capped: the depreciation may never
    exceed 7000 basis points, which is ten thousand basis points less a
    3000-basis-point residual floor, so at least thirty percent of guide value
    always survives no matter how old the unit is."
    PRD §3.3: "The `condition_adjustment_cents` figure is `book_base_cents`
    multiplied by the condition rate for the unit's `condition_grade` divided by
    ten thousand, rounded half up — where the rate is a credit of 800 basis
    points for `EXCELLENT`, exactly zero for `GOOD`, a charge of 1200 basis
    points for `FAIR`, and a charge of 2500 basis points for `POOR`."

    Design: Difficulty/combinatorial_formula/rate_and_term_nested_clamp_by_remaining_useful_life
    """
    scenario = _aged_single_wide_application(api)
    valuation = scenario["valuation"]

    assert valuation["valuation_year"] == 2026
    assert valuation["location_key"] == "PRIVATE_LAND"
    assert_valuation_breakdown(
        valuation,
        book_base_cents=AGED_BOOK_BASE_CENTS,
        condition_adjustment_cents=AGED_CONDITION_CENTS,
        location_adjustment_cents=AGED_LOCATION_CENTS,
        installation_adjustment_cents=AGED_INSTALLATION_CENTS,
        forced_sale_discount_cents=0,
        detach_and_move_cost_cents=0,
        certified_value_cents=AGED_CERTIFIED_CENTS,
    )


def test_leverage_of_exactly_nine_thousand_five_hundred_basis_points_passes(api):
    """PRD §3.4: "The `ltv_bps` figure is `principal_cents` multiplied by ten
    thousand and divided by the valuation's `certified_value_cents`, rounded half
    up to a whole basis point — the only rounded quantity in the whole pricing
    walk."
    PRD §3.4: "If the result exceeds 9500 basis points the submission is refused
    with `ERR_LTV_CAP_EXCEEDED` (HTTP 422); a computed value of exactly 9500
    passes."

    Design: Difficulty/boundary_precision_check/ltv_exactly_at_cap_passes_one_basis_point_over_fails
    """
    scenario = _community_collateral_with_two_applications(api)

    loan = validate_success(
        api.submit_underwriting(scenario["loan_at_cap"]["id"], fixtures.ANALYST)
    )

    assert loan["ltv_bps"] == LTV_CAP_BPS
    assert loan["apr_bps"] == AT_CAP_APR_BPS, (
        "the 9001-to-9500 leverage tier adds 150 basis points"
    )
    assert loan["term_months"] == AT_CAP_TERM_MONTHS
    assert loan["underwriting_state"] == "UNDERWRITING"


def test_leverage_one_basis_point_over_the_cap_is_refused_and_leaves_pricing_null(api):
    """PRD §3.4: "If the result exceeds 9500 basis points the submission is
    refused with `ERR_LTV_CAP_EXCEEDED` (HTTP 422); a computed value of exactly
    9500 passes."
    PRD §3.4: "Submitting the application for underwriting is the pricing act: it
    advances `underwriting_state` from `DRAFT` to `UNDERWRITING` and, in doing
    so, computes and stores `ltv_bps`, `apr_bps` and `term_months`, all three of
    which are null until this succeeds."

    Design: Difficulty/boundary_precision_check/ltv_exactly_at_cap_passes_one_basis_point_over_fails
    """
    scenario = _community_collateral_with_two_applications(api)
    loan_id = scenario["loan_over_cap"]["id"]

    validate_error(
        api.submit_underwriting(loan_id, fixtures.ANALYST),
        ApiErrorId.ERR_LTV_CAP_EXCEEDED.value,
        422,
    )

    loan = fixtures.read_loan(api, loan_id)
    assert loan["underwriting_state"] == "DRAFT"
    assert loan["ltv_bps"] is None
    assert loan["apr_bps"] is None
    assert loan["term_months"] is None
