"""Selection-score computation: the two variants, the bonus stack, the band."""
import pytest

from test_helpers import (
    ApiErrorId,
    err,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    DECIDER,
    REVIEWER,
    create_application,
    create_applicant,
    create_region,
    decide,
    review,
    setup_selection_pipeline,
)


class TestSelectionScoreVariants:
    """The provisional variant reads the self-reported GPA; the final one does not."""

    def test_final_score_reads_verified_gpa_and_clears_the_band(self, api):
        """PRD §3.2: "A newly submitted application enters the pipeline at `SUBMITTED`, with its `revision_count` set to 0, and its `selection_score` computed immediately using the provisional variant described below."
        PRD §3.3: "The final selection score is the same composite as the provisional score, computed with one substitution: the academic term reads the transcript-verified `verified_gpa` recorded at review instead of the self-reported `gpa`."
        PRD §3.3: "The decision writes the computed value to `final_selection_score`, records the deciding operator in `decided_by_user_id`, and moves the application to `SELECTED` or `REJECTED`."

        With gpa 3.90 the provisional score is 84.63 and would fail the band;
        the transcript-verified 4.00 lifts the final score to exactly 85.00.

        Design: Difficulty/dual_variant_calc/selection_score_provisional_vs_final_gpa
        """
        scenario = setup_selection_pipeline(
            applicant_overrides={"gpa": 3.90},
            application_overrides={"subject_area": "ENGLISH", "grade_preference": "HIGH"},
            verified_gpa=4.00,
            decision=None,
        )
        app_id = scenario["application"]["id"]

        provisional = validate_success(api.get_application(app_id, REVIEWER))
        assert provisional["selection_score"] == pytest.approx(84.63, abs=0.001), (
            "provisional score must read the self-reported gpa 3.90"
        )

        decided = validate_success(api.decide_application(app_id, "SELECT", DECIDER))
        assert decided["final_selection_score"] == pytest.approx(85.00, abs=0.001), (
            "final score must read the transcript-verified gpa 4.00"
        )
        assert decided["status"] == "SELECTED"
        assert decided["decided_by_user_id"] == DECIDER["X-User-ID"]
        assert decided["final_selection_score"] != provisional["selection_score"], (
            "the two variants must diverge when verified_gpa != gpa"
        )

    def test_select_gate_reads_only_the_final_variant(self, api):
        """PRD §3.3: "The two variants therefore diverge on exactly those applications whose verified GPA differs from the self-reported one, and only the final variant feeds the selection band."
        PRD §3.3: "a `SELECT` requires the final selection score to be at or above 85.00, and a selection requested below that band is refused with `ERR_SCORE_BELOW_THRESHOLD` (HTTP 422)."

        The provisional score is exactly 85.00 but the verified GPA drops the
        final score to 84.96, so the same application is refused.

        Design: Difficulty/dual_variant_calc/selection_score_provisional_vs_final_gpa
        """
        scenario = setup_selection_pipeline(
            applicant_overrides={"gpa": 4.00},
            application_overrides={"subject_area": "ENGLISH", "grade_preference": "HIGH"},
            verified_gpa=3.99,
            decision=None,
        )
        app_id = scenario["application"]["id"]

        provisional = validate_success(api.get_application(app_id, REVIEWER))
        assert provisional["selection_score"] == pytest.approx(85.00, abs=0.001)

        response = api.decide_application(app_id, "SELECT", DECIDER)
        validate_error(response, err(ApiErrorId.ERR_SCORE_BELOW_THRESHOLD), 422)

        after = validate_success(api.get_application(app_id, REVIEWER))
        assert after["status"] == "UNDER_REVIEW", (
            "the refused decision must leave the application in the pipeline"
        )


class TestSelectionScoreBonusStack:
    """The weighted base plus the campus-tier and high-need-subject bonuses."""

    def test_plain_application_scores_weighted_base(self, api):
        """PRD §3.2: "The leadership assessment enters at a weight of 0.45 and the achievement assessment at a weight of 0.40, both taken exactly as recorded on the applicant."
        PRD §3.2: "the GPA used — the self-reported `gpa` in this provisional variant — is compared against 4.0, the smaller of the two values is divided by 4.0, and the result is expressed on a 0-to-100 scale."
        PRD §3.2: "Only after every bonus has been added is the result rounded half up to 2 decimal places; that rounded value is the provisional `selection_score`."

        Design: Difficulty/combinatorial_formula/selection_score_bonus_stack_mode_a
        """
        region = create_region()
        applicant = create_applicant(
            campus_tier="STANDARD", leadership_score=88.0, achievement_score=76.0, gpa=3.50
        )
        application = create_application(
            applicant["id"], region["id"], subject_area="ENGLISH", grade_preference="HIGH"
        )

        data = validate_success(api.get_application(application["id"], REVIEWER))
        assert data["selection_score"] == pytest.approx(83.13, abs=0.001), (
            "0.45*88.0 + 0.40*76.0 + 0.15*(3.50/4.0*100) = 83.125 -> 83.13"
        )

    def test_priority_campus_and_high_need_subject_bonuses_stack(self, api):
        """PRD §3.2: "If the applicant was sourced from a `PRIORITY` campus, 5.0 is added and the running total is capped at 100.0."
        PRD §3.2: "If the application's `subject_area` is `MATH`, `SCIENCE` or `SPED` — the subjects the program treats as high-need — a further 7.0 is added, and the total is capped at 100.0 again."

        Design: Difficulty/combinatorial_formula/selection_score_bonus_stack_mode_a
        """
        region = create_region()
        plain_applicant = create_applicant(
            campus_tier="STANDARD", leadership_score=88.0, achievement_score=76.0, gpa=3.50
        )
        plain = create_application(
            plain_applicant["id"], region["id"], subject_area="ENGLISH", grade_preference="HIGH"
        )
        bonused_applicant = create_applicant(
            campus_tier="PRIORITY", leadership_score=88.0, achievement_score=76.0, gpa=3.50
        )
        bonused = create_application(
            bonused_applicant["id"], region["id"], subject_area="MATH", grade_preference="HIGH"
        )

        plain_score = validate_success(api.get_application(plain["id"], REVIEWER))["selection_score"]
        bonused_score = validate_success(api.get_application(bonused["id"], REVIEWER))[
            "selection_score"
        ]

        assert bonused_score == pytest.approx(95.13, abs=0.001), (
            "83.125 + 5.0 PRIORITY + 7.0 MATH = 95.125 -> 95.13"
        )
        assert bonused_score - plain_score == pytest.approx(12.00, abs=0.001), (
            "the two bonuses are worth exactly 12.00 on this base"
        )


class TestSelectionBandBoundary:
    """The SELECT band is inclusive at exactly 85.00."""

    def test_exactly_85_clears_the_band(self, api):
        """PRD §3.3: "a `SELECT` requires the final selection score to be at or above 85.00, and a selection requested below that band is refused with `ERR_SCORE_BELOW_THRESHOLD` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/selection_band_boundary_at_exactly_85
        """
        scenario = setup_selection_pipeline(
            applicant_overrides={"gpa": 4.00},
            application_overrides={"subject_area": "ENGLISH", "grade_preference": "HIGH"},
            verified_gpa=4.00,
            decision=None,
        )
        data = validate_success(
            api.decide_application(scenario["application"]["id"], "SELECT", DECIDER)
        )
        assert data["final_selection_score"] == pytest.approx(85.00, abs=0.001)
        assert data["status"] == "SELECTED"

    def test_just_below_85_is_refused(self, api):
        """PRD §3.3: "a `SELECT` requires the final selection score to be at or above 85.00, and a selection requested below that band is refused with `ERR_SCORE_BELOW_THRESHOLD` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/selection_band_boundary_at_exactly_85
        """
        scenario = setup_selection_pipeline(
            applicant_overrides={"gpa": 3.99},
            application_overrides={"subject_area": "ENGLISH", "grade_preference": "HIGH"},
            verified_gpa=3.99,
            decision=None,
        )
        app_id = scenario["application"]["id"]
        response = api.decide_application(app_id, "SELECT", DECIDER)
        validate_error(response, err(ApiErrorId.ERR_SCORE_BELOW_THRESHOLD), 422)

        after = validate_success(api.get_application(app_id, REVIEWER))
        assert after["status"] == "UNDER_REVIEW"
        assert after.get("decided_by_user_id") is None
