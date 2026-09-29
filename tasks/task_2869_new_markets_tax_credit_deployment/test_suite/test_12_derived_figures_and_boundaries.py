"""Numbers that are computed from disjoint inputs, at their exact boundaries.

A distress score and a distress tier answer different questions, so a high
score can sit in a low tier; a hundredth of a point of poverty flips a tract
from eligible to ineligible; a projection over six prongs keeps its declared
order; and a clawback runs its ladder and its interest as two separate
roundings.
"""
from test_helpers import (
    CLOCK_DEFAULT_UTC,
    REVIEWER_ANNUAL_USER_ID,
    REVIEWER_ELIGIBILITY_USER_ID,
    SPONSOR_DELTA_USER_ID,
    annual_test_payload,
    assert_append_only_fields,
    assert_census_tract,
    assert_cents,
    assert_instant,
    assert_pct,
    create_census_tract_payload,
    create_qalicb_payload,
    eligibility_test_payload,
    get_success_data,
    make_agency_headers,
    make_qalicb_sponsor_headers,
    make_reviewer_headers,
    read_award,
    read_qalicb,
    read_qei,
    set_clock,
    setup_deployed_investment,
    validate_success,
)


def _register(api, **stats):
    return validate_success(
        api.create_census_tract(
            create_census_tract_payload(**stats), make_agency_headers()
        ),
        201,
    )


def test_a_tract_can_score_eighty_eight_and_still_sit_in_the_moderate_tier(api):
    """The tier reads the criteria count first; the score alone decides nothing.

    PRD: "`severe_criteria_met_count` counts how many of three independent
    criteria the tract meets, and is therefore an integer from 0 through 3: the
    `poverty_rate_pct` being at least 30.00 counts as one, the `mfi_ratio_pct` being
    at most 60.00 counts as one, and the `unemployment_ratio` being at least 1.50
    counts as one."

    PRD: "The score is then 40 times the poverty factor plus 35 times the income
    factor plus 25 times the unemployment factor, rounded half-up to 2 decimal
    places, and finally capped at 100.00."

    PRD: "A tract can therefore score very high and still land in `MODERATE` when
    it meets zero severe criteria — a tract at poverty 28.00, income ratio 62.00 and
    unemployment ratio 1.40 scores 88.83 with a severe-criteria count of zero, and is
    `MODERATE`."

    PRD: "Otherwise, a tract meeting at least 1 severe criterion *and* scoring at
    least 50.00 is `HIGH`."

    Design: Corner/calculations/tract_distress_tier_stays_moderate_despite_a_distress_score_of_88_83
    """
    set_clock(api, CLOCK_DEFAULT_UTC)
    high_score = _register(
        api,
        tract_code="28049000200",
        poverty_rate_pct=28.00,
        mfi_ratio_pct=62.00,
        unemployment_ratio=1.40,
    )
    low_score = _register(
        api,
        tract_code="28049000300",
        poverty_rate_pct=30.00,
        mfi_ratio_pct=70.00,
        unemployment_ratio=1.20,
    )

    assert_census_tract(high_score)
    assert high_score["is_low_income_community"] is True
    assert_pct(high_score["distress_score"], 88.83, "distress_score")
    assert high_score["severe_criteria_met_count"] == 0
    assert high_score["distress_tier"] == "MODERATE"

    assert_census_tract(low_score)
    assert_pct(low_score["distress_score"], 67.50, "distress_score")
    assert low_score["severe_criteria_met_count"] == 1
    assert low_score["distress_tier"] == "HIGH"

    assert low_score["distress_score"] < high_score["distress_score"], (
        "the lower-scoring tract must nonetheless hold the higher tier"
    )
    for tract in (high_score, low_score):
        assert tract["eligible_for_qlici"] is True
        assert tract["qualifies_by_contiguity"] is False


ANCHOR_TRACT = {
    "tract_code": "28049000100",
    "poverty_rate_pct": 32.00,
    "mfi_ratio_pct": 55.00,
    "unemployment_ratio": 1.80,
}


def test_contiguity_relief_turns_on_at_exactly_fifteen_percent_poverty(api):
    """One hundredth of a point of poverty flips eligibility and the whole tier.

    PRD: "Contiguity relief exists only for tracts that fail that test:
    `qualifies_by_contiguity` is true when the tract is not itself a low-income
    community, *and* an adjoining tract has been named through
    `contiguous_lic_tract_id`, *and* the tract's own `poverty_rate_pct` is at least
    15.00."

    PRD: "The gate that the rest of the system reads is `eligible_for_qlici`, which
    is true when the tract is a low-income community or qualifies by contiguity."

    PRD: "A tract that is not `eligible_for_qlici` is `INELIGIBLE` regardless of its
    statistics."

    PRD: "The income factor is the amount by which the `mfi_ratio_pct` falls short
    of 80.00 — floored at zero, so a tract at or above 80.00 contributes nothing —
    divided by 20.00 and capped at 1."

    Design: Corner/calculations/contiguous_tract_qualifies_at_exactly_15_percent_poverty_and_fails_at_14_99
    """
    set_clock(api, CLOCK_DEFAULT_UTC)
    anchor = _register(api, **ANCHOR_TRACT)

    at_boundary = _register(
        api,
        tract_code="28049000400",
        poverty_rate_pct=15.00,
        mfi_ratio_pct=85.00,
        unemployment_ratio=1.00,
        contiguous_lic_tract_id=anchor["id"],
    )
    below_boundary = _register(
        api,
        tract_code="28049000500",
        poverty_rate_pct=14.99,
        mfi_ratio_pct=85.00,
        unemployment_ratio=1.00,
        contiguous_lic_tract_id=anchor["id"],
    )

    assert at_boundary["is_low_income_community"] is False
    assert at_boundary["qualifies_by_contiguity"] is True
    assert at_boundary["eligible_for_qlici"] is True
    assert_pct(at_boundary["distress_score"], 20.00, "distress_score")
    assert at_boundary["severe_criteria_met_count"] == 0
    assert at_boundary["distress_tier"] == "MODERATE"

    assert below_boundary["qualifies_by_contiguity"] is False
    assert below_boundary["eligible_for_qlici"] is False
    assert_pct(below_boundary["distress_score"], 19.99, "distress_score")
    assert below_boundary["distress_tier"] == "INELIGIBLE"

    assert anchor["distress_tier"] == "SEVERE"
    assert anchor["qualifies_by_contiguity"] is False


def test_the_failed_prongs_projection_keeps_its_declared_order(api):
    """Two of six prongs fail; the array names those two, in the fixed order.

    PRD: "The `failed_prongs` array names every prong that failed, always in the
    fixed order `LOCATION`, `GROSS_INCOME`, `SERVICES`, `TANGIBLE_PROPERTY`,
    `COLLECTIBLES`, `NQFP`, whatever order the inputs arrived in, and it is an empty
    array on a pass."

    PRD: "All bounds are inclusive and compared at 2 decimal places: gross income of
    exactly 50.00 passes and 49.99 fails; collectibles of exactly 5.00 pass and 5.01
    fails."

    PRD: "A failure raises `consecutive_failed_test_count` by 1 and sets
    `latest_test_result` to `FAIL`; if the raised counter is still below 2 the
    business lands in `FAILED`, and once the raised counter reaches 2 the business
    lands in `DISQUALIFIED`."

    Design: Corner/calculations/qalicb_eligibility_failed_prongs_are_listed_in_declaration_order
    """
    set_clock(api, CLOCK_DEFAULT_UTC)
    tract = _register(api, **ANCHOR_TRACT)
    qalicb = validate_success(
        api.create_qalicb(
            create_qalicb_payload(tract["id"]),
            make_qalicb_sponsor_headers(SPONSOR_DELTA_USER_ID),
        ),
        201,
    )

    outcome = validate_success(
        api.run_eligibility_test(
            qalicb["id"],
            eligibility_test_payload(
                gross_income_lic_pct=48.00,
                services_lic_pct=65.00,
                tangible_property_lic_pct=88.00,
                collectibles_pct=6.00,
                nonqualified_financial_property_pct=1.00,
                location_prong_passed=True,
            ),
            make_reviewer_headers(REVIEWER_ELIGIBILITY_USER_ID),
        ),
        201,
    )

    assert outcome["result"] == "FAIL"
    assert outcome["failed_prongs"] == ["GROSS_INCOME", "COLLECTIBLES"], (
        "the projection is ordered by declaration, not by discovery or alphabet"
    )
    assert_pct(outcome["services_lic_pct"], 65.00, "services_lic_pct")
    assert_pct(
        outcome["tangible_property_lic_pct"], 88.00, "tangible_property_lic_pct"
    )
    assert_pct(
        outcome["nonqualified_financial_property_pct"],
        1.00,
        "nonqualified_financial_property_pct",
    )
    assert outcome["location_prong_passed"] is True
    assert_instant(outcome["performed_at"], CLOCK_DEFAULT_UTC, "performed_at")
    assert outcome["performed_by_user_id"] == REVIEWER_ELIGIBILITY_USER_ID
    assert_append_only_fields(outcome, "eligibility test")

    business = read_qalicb(api, qalicb["id"])
    assert business["eligibility_status"] == "FAILED"
    assert business["consecutive_failed_test_count"] == 1
    assert business["last_certified_at"] is None


BIG_GROSS_CENTS = 500_000_000
BIG_PLACEMENT_CENTS = 100_000_000
YEAR_ONE_CLOCK = "2027-09-01T00:00:00.000Z"
INSIDE_CURE_WINDOW_CLOCK = "2028-01-15T00:00:00.000Z"
PAST_CURE_DEADLINE_CLOCK = "2029-08-31T00:00:00.000Z"
CURE_DEADLINE = "2028-02-28T00:00:00.000Z"


def _annual_test(api, qei_id, compliance_year, at_clock):
    set_clock(api, at_clock)
    return get_success_data(
        api.run_annual_test(
            qei_id,
            annual_test_payload(compliance_year),
            make_reviewer_headers(REVIEWER_ANNUAL_USER_ID),
        )
    )


def test_the_year_three_clawback_rounds_the_ladder_and_the_interest_separately(api):
    """A failure inside the cure window only warns; the one past it claws back.

    PRD: "The tier is selected from the **gross** `qei_amount_cents`, never from a
    net or post-fee figure: a gross below 500000000 cents draws a `reserve_bps` of
    500, a gross that is at least 500000000 but below 1500000000 draws 400, and a
    gross of 1500000000 or more draws 300."

    PRD: "On a failing test an investment in `COMPLIANT` moves to `AT_RISK` with
    `cure_deadline_at` set to the logical clock advanced by 180 days."

    PRD: "A failing test against an investment *already* in `AT_RISK` whose
    `cure_deadline_at` the logical clock has passed is the end of the road: the
    investment moves to `RECAPTURED`, the test's `recapture_triggered` is set true,
    and `recapture_trigger_type` is set to `SUBSTANTIALLY_ALL_FAILURE` — or to
    `REINVESTMENT_BREACH` when the same test's `breached_obligation_count` is greater
    than 0, since returned capital left idle past its window is a different sin from
    capital that never qualified."

    PRD: "The order in which the test updates the investment is pinned as well:
    `compliance_years_completed` is set to the tested `compliance_year` **before** any
    recapture arithmetic runs, so an exposure computed in the same request reads the
    year just completed and not the year before it."

    PRD: "Otherwise the claimed amount is the gross `qei_amount_cents` multiplied by
    the ladder's basis points for the completed year count, divided by 10000 and
    rounded half-up. Interest is simple and never compounded, charged at 300 basis
    points per completed year on that cumulative claimed amount rather than year by
    year: the claimed amount multiplied by 300, multiplied by the number of completed
    years, divided by 10000, and rounded half-up as its own separate step."

    PRD: "If the allocatee's `certification_status` is `DECERTIFIED`, or the award
    has at least one investment whose `compliance_status` is `RECAPTURED`, the posture
    is `FROZEN`, which bars both new investment issuance and new sub-allocation
    deployment."

    Design: Corner/calculations/recapture_exposure_at_year_three_on_a_500m_qei_is_81750000_after_a_missed_cure
    """
    scenario = setup_deployed_investment(
        api,
        certification_suffix=110,
        fund_overrides={
            "legal_name": "NMTC Fund II LLC",
            "equity_contribution_cents": 325_000_000,
            "leverage_lender_name": "Delta Bank",
            "leverage_loan_principal_cents": 175_000_000,
            "leverage_loan_rate_bps": 450,
        },
        qei_overrides={"qei_amount_cents": BIG_GROSS_CENTS},
        qlici_overrides={"principal_cents": BIG_PLACEMENT_CENTS},
    )
    qei_id = scenario.qei["id"]

    assert_cents(scenario.qei["qei_amount_cents"], BIG_GROSS_CENTS, "qei_amount_cents")
    assert scenario.qei["reserve_bps"] == 400
    assert_cents(
        scenario.qei["permitted_fees_cents"], 20_000_000, "permitted_fees_cents"
    )
    assert_cents(
        scenario.qei["net_deployable_cents"], 480_000_000, "net_deployable_cents"
    )

    first = _annual_test(api, qei_id, 1, YEAR_ONE_CLOCK)
    assert first["result"] == "FAIL"
    assert first["governing_method"] == "DIRECT_TRACING"
    assert_pct(first["measured_pct_direct"], 20.83, "measured_pct_direct")
    assert_pct(first["governing_pct"], 20.83, "governing_pct")
    after_first = read_qei(api, qei_id)
    assert after_first["compliance_status"] == "AT_RISK"
    assert_instant(after_first["cure_deadline_at"], CURE_DEADLINE, "cure_deadline_at")

    second = _annual_test(api, qei_id, 2, INSIDE_CURE_WINDOW_CLOCK)
    assert second["result"] == "FAIL"
    after_second = read_qei(api, qei_id)
    assert after_second["compliance_status"] == "AT_RISK", (
        "a failure inside the cure window does not escalate"
    )
    assert_instant(
        after_second["cure_deadline_at"], CURE_DEADLINE, "cure_deadline_at"
    )

    third = _annual_test(api, qei_id, 3, PAST_CURE_DEADLINE_CLOCK)
    assert third["result"] == "FAIL"
    assert third["recapture_triggered"] is True

    clawed_back = read_qei(api, qei_id)
    assert clawed_back["compliance_status"] == "RECAPTURED"
    assert clawed_back["recapture_trigger_type"] == "SUBSTANTIALLY_ALL_FAILURE"
    assert clawed_back["compliance_years_completed"] == 3
    assert_cents(
        clawed_back["recapture_exposure_cents"],
        81_750_000,
        "recapture_exposure_cents",
    )

    award = read_award(api, scenario.award["id"])
    assert award["recaptured_qei_count"] == 1
    assert award["at_risk_qei_count"] == 0
    assert award["compliance_posture"] == "FROZEN"
