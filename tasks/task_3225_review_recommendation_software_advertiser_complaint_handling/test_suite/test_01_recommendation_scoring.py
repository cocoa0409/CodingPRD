"""Recommendation software scoring: dual variants, input interaction, threshold."""
from test_helpers import (
    OPS,
    ApiErrorId,
    assert_review,
    create_page,
    create_review,
    create_user,
    get_page,
    get_review,
    make_reviewer_headers,
    set_clock,
    validate_success,
)


class TestSubmissionVsReevaluationVariant:
    def test_at_submission_variant_has_no_age_decay(self, api):
        """PRD §3.3: "the recommendation software is immediately evaluated
        against it in its at-submission variant — which simply means the
        age-decay term contributes nothing because `submitted_at` equals the
        current logical time."
        PRD §3.3: "Start from a base of 300 plus 4 times the author's
        `trust_score` (clamped into 0..100 before multiplication), giving a
        base in the range 300 to 700."
        PRD §3.3: "A score of at least 700 transitions the review toward
        `DISPLAYED`; anything below 700 transitions it toward `FILTERED`."

        Design: Difficulty/dual_variant_calc/recommendation_score_submission_vs_reevaluation
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user()  # default trust_score 50
        page = create_page()
        review = create_review(page["id"], author["id"], rating=4)
        assert review["recommendation_score_x1000"] == 300 + 4 * 50
        assert review["recommendation_state"] == "FILTERED"
        assert review["edited_flag"] is False

    def test_reevaluation_variant_applies_age_decay(self, api):
        """PRD §3.3: "This re-evaluation variant applies both the age-decay
        term and the edit penalty, then applies the threshold rule".
        PRD §3.3: "Then compute the review's age in days as the integer floor
        of (current logical time minus `submitted_at`) divided by 86400
        seconds, cap that age at 100 days, and subtract 2 per capped day."

        Design: Difficulty/dual_variant_calc/recommendation_score_submission_vs_reevaluation
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user()  # trust 50 -> base 500
        page = create_page()
        review = create_review(page["id"], author["id"], rating=4)
        assert review["recommendation_score_x1000"] == 500
        # 10 days of aging: 500 - 2*10 = 480; still FILTERED.
        set_clock("2026-09-11T00:00:00Z")
        reeval = validate_success(api.evaluate_review(review["id"], OPS))
        assert reeval["recommendation_score_x1000"] == 480
        assert reeval["recommendation_state"] == "FILTERED"


class TestScoringInputInteraction:
    def test_age_decay_flips_displayed_to_filtered_and_recomputes_page(self, api):
        """PRD §3.3: "From `DISPLAYED`, the review drops to `FILTERED` whenever
        the re-computed score is below 700".
        PRD §3.3: "every transition out of `DISPLAYED` decrements the count and
        recomputes the average."

        Design: Difficulty/combinatorial_formula/recommendation_score_three_input_interaction
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user(trust_score=100)  # base 700
        page = create_page()
        review = create_review(page["id"], author["id"], rating=5)
        assert review["recommendation_score_x1000"] == 700
        assert review["recommendation_state"] == "DISPLAYED"
        assert get_page(page["id"])["displayed_review_count"] == 1
        # 30 days of aging: 700 - 60 = 640 < 700 -> FILTERED, count back to 0.
        set_clock("2026-10-01T00:00:00Z")
        reeval = validate_success(api.evaluate_review(review["id"], OPS))
        assert reeval["recommendation_score_x1000"] == 640
        assert reeval["recommendation_state"] == "FILTERED"
        page_after = get_page(page["id"])
        assert page_after["displayed_review_count"] == 0
        assert page_after["displayed_rating_avg_x100"] == 0

    def test_suspension_penalty_combines_with_age_decay(self, api):
        """PRD §3.3: "If the author's `status` is `SUSPENDED`, subtract 200."
        PRD §3.1: "Suspending a user transitions their `status` to `SUSPENDED`;
        on the next recommendation evaluation, any of their currently
        `DISPLAYED` reviews will be re-scored with the suspension penalty
        applied".

        Design: Difficulty/combinatorial_formula/recommendation_score_three_input_interaction
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user(trust_score=100)
        page = create_page()
        review = create_review(page["id"], author["id"], rating=5)
        assert review["recommendation_state"] == "DISPLAYED"
        set_clock("2026-10-01T00:00:00Z")  # age 30d -> 640
        validate_success(api.suspend_user(author["id"], OPS))
        reeval = validate_success(api.evaluate_review(review["id"], OPS))
        # 700 - 60 (age) - 200 (suspended) = 440.
        assert reeval["recommendation_score_x1000"] == 440
        assert reeval["recommendation_state"] == "FILTERED"
        assert get_page(page["id"])["displayed_review_count"] == 0


class TestRecommendationThresholdBoundary:
    def test_score_exactly_700_is_displayed(self, api):
        """PRD §3.3: "A score of at least 700 transitions the review toward
        `DISPLAYED`; anything below 700 transitions it toward `FILTERED`."
        PRD §3.3: "Every transition into `DISPLAYED` increments the parent
        page's `displayed_review_count` and recomputes its
        `displayed_rating_avg_x100`".

        Design: Difficulty/boundary_precision_check/recommendation_threshold_699_vs_700
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user(trust_score=100)  # 300 + 4*100 = 700 exactly
        page = create_page()
        review = create_review(page["id"], author["id"], rating=4)
        assert review["recommendation_score_x1000"] == 700
        assert review["recommendation_state"] == "DISPLAYED"
        assert get_page(page["id"])["displayed_review_count"] == 1

    def test_score_696_is_filtered(self, api):
        """PRD §3.3: "A score of at least 700 transitions the review toward
        `DISPLAYED`; anything below 700 transitions it toward `FILTERED`."

        Design: Difficulty/boundary_precision_check/recommendation_threshold_699_vs_700
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user(trust_score=99)  # 300 + 4*99 = 696
        page = create_page()
        review = create_review(page["id"], author["id"], rating=4)
        assert review["recommendation_score_x1000"] == 696
        assert review["recommendation_state"] == "FILTERED"
        assert get_page(page["id"])["displayed_review_count"] == 0


class TestReviewCreationDefaults:
    def test_review_creation_stamps_system_fields(self, api):
        """PRD §3.3: "The system records `page_id`, stamps `author_user_id`
        from `X-User-ID`, captures `submitted_at` from the logical clock, and
        initializes `edited_flag` to false and `evidence_confirmed` to false."
        PRD §2.5: "Every first-class resource carries a server-minted `id` (a
        UUID, with no type prefix)".

        Design: Corner/entities/review_create_defaults_and_system_fields
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user()
        page = create_page()
        review = create_review(page["id"], author["id"], rating=3)
        assert_review(review)
        assert review["author_user_id"] == author["id"]
        assert review["page_id"] == page["id"]
        assert review["edited_flag"] is False
        assert review["evidence_confirmed"] is False
        assert review["submitted_at"].startswith("2026-09-01T00:00:00")
        assert review["recommendation_score_x1000"] == 500
        assert review["recommendation_state"] == "FILTERED"


class TestInitialState:
    def test_high_trust_review_is_displayed_immediately(self, api):
        """PRD §3.3: "The review's `recommendation_state` starts at `PENDING`,
        and the recommendation software is immediately evaluated against it in
        its at-submission variant".
        PRD §3.3: "A score of at least 700 transitions the review toward
        `DISPLAYED`; anything below 700 transitions it toward `FILTERED`."

        Design: Corner/state_machines/review_initial_state_pending_or_scored
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user(trust_score=100)
        page = create_page()
        review = create_review(page["id"], author["id"], rating=5)
        assert review["recommendation_state"] == "DISPLAYED"
        assert review["recommendation_score_x1000"] == 700


class TestLogicalClockDefault:
    def test_default_clock_is_2026_09_01(self, api):
        """PRD §2.4: "At server startup, the logical "now" is exactly
        `2026-09-01T00:00:00Z`, and the server must not silently fall back to
        wall-clock time."

        Design: Corner/endpoints/clock_default_and_set
        """
        # Deliberately no set_clock call: observe the startup default.
        author = create_user()
        page = create_page()
        review = create_review(page["id"], author["id"], rating=4)
        assert review["submitted_at"].startswith("2026-09-01T00:00:00")
