"""Boundary and precision edges on two different metric families.

The first group pins the inclusive score-versus-tier-minimum comparison at
two-decimal precision; the second pins the empty-denominator and inclusive
survey-cutoff edges of the live program evaluation.
"""
from test_helpers import (
    ADMIN,
    REVIEWER,
    ApiErrorId,
    api_client,
    assert_score,
    assert_status,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.constants import DEFAULT_CLOCK


def _two_claims_scoring_exactly_eighty_point_eight():
    """One UNDER_REVIEW claim on the 80.80 tier and one on the 80.81 tier.

    All five criteria are declared conformant, so both claims score 76.00 in
    AUTHENTICATION, 60.00 in SOFTWARE_UPDATE and 100.00 in the other two areas,
    weighting to 80.80 with a minimum area score of exactly 60.00.
    """
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program("SELF_ATTESTATION")
    strict_tier = validate_success(
        api_client.create_program_tier(
            factories.create_program_tier_payload(
                tier_code="TIER_1_STRICT", min_overall_score=80.81
            ),
            ADMIN,
        ),
        201,
    )
    thermostat_category = validate_success(
        api_client.create_device_category(
            factories.create_device_category_payload(
                strict_tier["id"],
                category_code="SMART_THERMOSTAT",
                display_name="Smart Thermostat",
            ),
            ADMIN,
        ),
        201,
    )
    sponsor = fixtures.enrol_manufacturer()

    speaker = fixtures.register_product(program, sponsor)
    at_minimum = fixtures.open_assessment(program, sponsor, speaker)
    fixtures.attach_responses(program, sponsor, at_minimum)
    at_minimum = validate_success(
        api_client.submit_assessment(at_minimum["id"], sponsor.headers), 201
    )

    thermostat = fixtures.register_product(
        program,
        sponsor,
        category_id=thermostat_category["id"],
        model_name="Northwind Thermostat T3",
        sku="NW-THM-T3",
        retail_units_shipped=9000,
    )
    below_minimum = fixtures.open_assessment(program, sponsor, thermostat)
    fixtures.attach_responses(program, sponsor, below_minimum)
    below_minimum = validate_success(
        api_client.submit_assessment(below_minimum["id"], sponsor.headers), 201
    )
    return {
        "program": program,
        "strict_tier": strict_tier,
        "sponsor": sponsor,
        "at_minimum": at_minimum,
        "below_minimum": below_minimum,
    }


class TestScoreExactlyAtTierMinimumApprovesAndOneHundredthAboveRejects:
    """The approval gate is an inclusive `>=` read at two decimal places."""

    def test_score_sitting_exactly_on_the_minimum_is_approved(self):
        """80.80 against a minimum of 80.80 clears the bar inclusively.

        PRD: "An approval requires that `status` is `UNDER_REVIEW`, that a third-party-route assessment already has at least one test engagement whose `status` is `COMPLETED` (otherwise `ERR_THIRD_PARTY_TEST_REQUIRED`), and that `decided_overall_score` is greater than or equal to the tier's `min_overall_score` (otherwise `ERR_SCORE_BELOW_MINIMUM`)."
        Design: Difficulty/boundary_precision_check/score_exactly_at_tier_minimum_approves_and_one_hundredth_above_rejects
        """
        ctx = _two_claims_scoring_exactly_eighty_point_eight()
        decided = validate_success(
            api_client.decide_assessment(
                ctx["at_minimum"]["id"],
                factories.decide_payload(
                    "APPROVED",
                    reviewer_note="Score sits exactly on the TIER_1 minimum.",
                ),
                REVIEWER,
            ),
            201,
        )
        assert_status(decided, "status", "APPROVED")
        assert_score(decided["decided_overall_score"], 80.80, "decided_overall_score")
        assert_status(decided, "grade", "B")

    def test_score_one_hundredth_below_the_minimum_is_rejected(self):
        """The same 80.80 against a minimum of 80.81 fails the score gate.

        PRD: "Note that the score gate reads the score and not the `grade`: a tier whose `min_overall_score` sits above 80.00 can legitimately reject a claim whose `grade` is still `B`."
        Design: Difficulty/boundary_precision_check/score_exactly_at_tier_minimum_approves_and_one_hundredth_above_rejects
        """
        ctx = _two_claims_scoring_exactly_eighty_point_eight()
        response = api_client.decide_assessment(
            ctx["below_minimum"]["id"],
            factories.decide_payload(
                "APPROVED",
                reviewer_note="Attempted approval one hundredth below the TIER_1_STRICT minimum.",
            ),
            REVIEWER,
        )
        validate_error(response, ApiErrorId.ERR_SCORE_BELOW_MINIMUM.value)
        assert response.status_code == 422, response.text

        unchanged = validate_success(
            api_client.get_assessment(ctx["below_minimum"]["id"], ADMIN)
        )
        assert_status(unchanged, "status", "UNDER_REVIEW")
        assert unchanged.get("decided_by_user_id") is None, unchanged.get("decided_by_user_id")

    def test_both_claims_carry_the_same_grade_and_ungated_floor(self):
        """Identical grade B and an exactly-60.00 floor leave only the score to separate them.

        PRD: "If the smallest area score is 60.00 or above, the overall score is simply the weighted sum and `gate_applied` is false."
        Design: Difficulty/boundary_precision_check/score_exactly_at_tier_minimum_approves_and_one_hundredth_above_rejects
        """
        ctx = _two_claims_scoring_exactly_eighty_point_eight()
        for assessment in (ctx["at_minimum"], ctx["below_minimum"]):
            current = validate_success(api_client.get_assessment(assessment["id"], ADMIN))
            assert_score(current["decided_overall_score"], 80.80, "decided_overall_score")
            assert_score(current["decided_min_area_score"], 60.00, "decided_min_area_score")
            assert_status(current, "grade", "B")
            assert current["gate_applied"] is False, current["gate_applied"]


FUTURE_WAVE = {
    "survey_period_label": "2026-Q4",
    "survey_period_end": "2026-12-31T00:00:00Z",
    "respondents_count": 100,
    "recognized_count": 90,
}
BOUNDARY_WAVE = {
    "survey_period_label": "2026-Q3",
    "survey_period_end": DEFAULT_CLOCK,
    "respondents_count": 40,
    "recognized_count": 14,
}


def _empty_program_with_one_future_wave():
    """No manufacturers, no products, no grants, one wave the clock has not reached."""
    fixtures.set_clock(DEFAULT_CLOCK)
    fixtures.record_survey(**FUTURE_WAVE)


def _assert_no_null_rates(evaluation):
    for field in ("manufacturer_participation_rate", "consumer_recognition_rate"):
        assert evaluation.get(field) is not None, f"{field} must never be null: {evaluation}"


class TestEmptyAndZeroCountDenominatorsInProgramEvaluation:
    """Empty and zero-count denominators, and the inclusive survey cutoff."""

    def test_wholly_empty_program_reports_zero_rates_rather_than_null(self):
        """With no manufacturers and no closed waves both rates read exactly 0.00.

        PRD: "`manufacturer_participation_rate` is 100 times `participating_manufacturer_count` divided by `enrolled_manufacturer_count`, rounded half-up to two decimal places — except that when `enrolled_manufacturer_count` is zero the rate is exactly 0.00."
        Design: Difficulty/boundary_precision_check/empty_and_zero_count_denominators_in_program_evaluation
        """
        _empty_program_with_one_future_wave()
        evaluation = fixtures.program_evaluation()
        _assert_no_null_rates(evaluation)
        assert evaluation["enrolled_manufacturer_count"] == 0, evaluation
        assert evaluation["participating_manufacturer_count"] == 0, evaluation
        assert_score(evaluation["manufacturer_participation_rate"], 0.00,
                     "manufacturer_participation_rate")
        assert evaluation["eligible_product_count"] == 0, evaluation
        assert evaluation["labeled_product_count"] == 0, evaluation
        assert evaluation["respondents_count"] == 0, evaluation
        assert evaluation["recognized_total"] == 0, evaluation
        assert_score(evaluation["consumer_recognition_rate"], 0.00, "consumer_recognition_rate")
        assert_status(evaluation, "evaluation_grade", "BELOW_TARGET")

    def test_one_enrolled_manufacturer_without_any_grant_keeps_the_rate_at_zero(self):
        """A non-empty denominator with a zero numerator still reads 0.00.

        PRD: "`participating_manufacturer_count` is the count of *distinct* manufacturers for which some label grant exists whose product belongs to that manufacturer and whose `grant_status` is either `ACTIVE` or `SUSPENDED`."
        Design: Difficulty/boundary_precision_check/empty_and_zero_count_denominators_in_program_evaluation
        """
        _empty_program_with_one_future_wave()
        fixtures.enrol_manufacturer()
        evaluation = fixtures.program_evaluation()
        _assert_no_null_rates(evaluation)
        assert evaluation["enrolled_manufacturer_count"] == 1, evaluation
        assert evaluation["participating_manufacturer_count"] == 0, evaluation
        assert_score(evaluation["manufacturer_participation_rate"], 0.00,
                     "manufacturer_participation_rate")

    def test_wave_closing_exactly_on_the_clock_instant_is_counted(self):
        """A wave whose `survey_period_end` equals the clock enters the aggregate.

        PRD: "The upper bound is inclusive, so a wave whose `survey_period_end` equals the clock instant to the second is included, and future-dated waves are excluded until the clock reaches them."
        Design: Difficulty/boundary_precision_check/empty_and_zero_count_denominators_in_program_evaluation
        """
        _empty_program_with_one_future_wave()
        fixtures.enrol_manufacturer()
        fixtures.record_survey(**BOUNDARY_WAVE)
        evaluation = fixtures.program_evaluation()
        assert evaluation["respondents_count"] == 40, evaluation
        assert evaluation["recognized_total"] == 14, evaluation
        assert_score(evaluation["consumer_recognition_rate"], 35.00, "consumer_recognition_rate")

    def test_recognition_target_is_inclusive_so_the_grade_becomes_partial(self):
        """35.00 against a 35.00 target clears one of the two targets.

        PRD: "A program that clears exactly one of the two targets is graded `PARTIAL`."
        Design: Difficulty/boundary_precision_check/empty_and_zero_count_denominators_in_program_evaluation
        """
        _empty_program_with_one_future_wave()
        fixtures.enrol_manufacturer()
        fixtures.record_survey(**BOUNDARY_WAVE)
        evaluation = fixtures.program_evaluation()
        assert_score(evaluation["manufacturer_participation_rate"], 0.00,
                     "manufacturer_participation_rate")
        assert_score(evaluation["consumer_recognition_rate"], 35.00, "consumer_recognition_rate")
        assert_status(evaluation, "evaluation_grade", "PARTIAL")
        assert evaluation["recognized_total"] == 14, (
            "the future-dated wave must stay out of the aggregate"
        )
