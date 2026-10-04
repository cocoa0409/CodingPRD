"""Interview scheduling, weighted scoring with the minimum-dimension cap,
and the half-open calendar overlap rule."""

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_START,
    TEST_USERS,
    api_client,
    begin_review,
    complete_interview,
    create_applicant,
    create_application,
    get_application,
    schedule_interview,
    set_clock,
    submit_application,
    validate_error,
    validate_success,
)

PLACER = TEST_USERS["placement_officer_headers"]


def _under_review_with_interview(**interview_overrides):
    """Applicant + application driven to INTERVIEWING with one SCHEDULED
    interview. Returns (applicant, application, interview)."""
    applicant = create_applicant()
    application = create_application(applicant["id"])
    submit_application(application["id"], applicant["id"])
    begin_review(application["id"])
    interview = schedule_interview(application["id"], **interview_overrides)
    return applicant, application, interview


class TestInterviewScoring:
    def test_interview_overall_recommend_tier_rounding(self):
        """PRD §3.3: "The system then computes the interview's
        `overall_score` as thirty per cent of the motivation score, plus
        twenty-five per cent each of the adaptability and skill-competency
        scores, plus twenty per cent of the cross-cultural score, rounding the
        weighted sum half-up to two decimal places."
        PRD §3.3: "Otherwise an `overall_score` of at least 4.0 earns
        `STRONGLY_RECOMMEND`, at least 3.0 earns `RECOMMEND`, at least 2.5
        earns `NEUTRAL`, and anything below that earns `NOT_RECOMMENDED`."

        Design: Corner/calculations/interview_overall_recommend_tier_rounding
        """
        set_clock(DEFAULT_CLOCK_START)
        _, application, interview = _under_review_with_interview()
        completed = complete_interview(
            interview["id"],
            motivation_score=4.0, adaptability_score=3.0,
            skill_competency_score=3.0, cross_cultural_score=3.0,
        )
        assert completed["overall_score"] == pytest.approx(3.30, abs=1e-9)
        assert completed["recommendation"] == "RECOMMEND"
        assert completed["status"] == "COMPLETED"
        assert get_application(application["id"])["status"] == "EVALUATED"

    def test_interview_dimension_cap_overrides_high_weighted_sum(self):
        """PRD §3.3: "The `recommendation` is derived in a fixed order: round
        first, then apply the minimum-dimension cap, then tier. If the lowest
        of the four dimension scores falls below 2.0, the recommendation is
        `NOT_RECOMMENDED` regardless of the weighted sum."

        Design: Difficulty/combinatorial_formula/interview_overall_weighted_sum_with_dimension_cap
        """
        set_clock(DEFAULT_CLOCK_START)
        _, application, interview = _under_review_with_interview()
        completed = complete_interview(
            interview["id"],
            motivation_score=5.0, adaptability_score=5.0,
            skill_competency_score=5.0, cross_cultural_score=1.5,
        )
        # 0.30*5 + 0.25*5 + 0.25*5 + 0.20*1.5 = 4.30 — alone that tiers
        # STRONGLY_RECOMMEND, but the 1.5 dimension is below the 2.0 floor.
        assert completed["overall_score"] == pytest.approx(4.30, abs=1e-9)
        assert completed["recommendation"] == "NOT_RECOMMENDED", \
            "the minimum-dimension cap must override the 4.30 weighted sum"
        assert completed["status"] == "COMPLETED"
        assert get_application(application["id"])["status"] == "EVALUATED"

    def test_interview_min_dimension_at_floor_not_capped(self):
        """PRD §3.3: "The `recommendation` is derived in a fixed order: round
        first, then apply the minimum-dimension cap, then tier. If the lowest
        of the four dimension scores falls below 2.0, the recommendation is
        `NOT_RECOMMENDED` regardless of the weighted sum. Otherwise an
        `overall_score` of at least 4.0 earns `STRONGLY_RECOMMEND`, at least
        3.0 earns `RECOMMEND`, at least 2.5 earns `NEUTRAL`, and anything
        below that earns `NOT_RECOMMENDED`."

        Design: Difficulty/combinatorial_formula/interview_overall_weighted_sum_with_dimension_cap
        """
        set_clock(DEFAULT_CLOCK_START)
        _, application, interview = _under_review_with_interview()
        completed = complete_interview(
            interview["id"],
            motivation_score=4.5, adaptability_score=4.5,
            skill_competency_score=4.5, cross_cultural_score=2.0,
        )
        # Minimum dimension is exactly 2.0, which is NOT below 2.0, so the cap
        # must not fire; 0.30*4.5 + 0.25*4.5 + 0.25*4.5 + 0.20*2.0 = 4.00.
        assert completed["overall_score"] == pytest.approx(4.00, abs=1e-9)
        assert completed["recommendation"] == "STRONGLY_RECOMMEND"
        assert get_application(application["id"])["status"] == "EVALUATED"


class TestInterviewCalendar:
    def test_interview_cancel_reverts_application_to_under_review(self):
        """PRD §3.3: "Cancelling a `SCHEDULED` interview moves it to
        `CANCELLED`, and if no other `SCHEDULED` interview remains for the
        application, the application reverts from `INTERVIEWING` to
        `UNDER_REVIEW`, free to be interviewed again."
        PRD §3.3: "Against a `SCHEDULED` interview — completing or cancelling
        a non-`SCHEDULED` one fails with `ERR_INVALID_STATE` — the officer
        records four dimension scores, `motivation_score`,
        `adaptability_score`, `skill_competency_score`, and
        `cross_cultural_score`, each between 1.0 and 5.0 or the request fails
        with `ERR_VALIDATION`."

        Design: Corner/state_machines/interview_cancel_reverts_application_to_under_review
        """
        set_clock(DEFAULT_CLOCK_START)
        _, application, interview = _under_review_with_interview()
        assert get_application(application["id"])["status"] == "INTERVIEWING"

        cancelled = validate_success(
            api_client.cancel_interview(interview["id"], PLACER), 200)
        assert cancelled["status"] == "CANCELLED"
        assert get_application(application["id"])["status"] == "UNDER_REVIEW", \
            "cancelling the last SCHEDULED interview reverts the application"

        # A cancelled interview cannot be completed afterwards.
        validate_error(
            api_client.complete_interview(
                interview["id"],
                {"motivation_score": 4.0, "adaptability_score": 3.0,
                 "skill_competency_score": 3.0, "cross_cultural_score": 3.0},
                PLACER),
            ApiErrorId.ERR_INVALID_STATE, 409)

        # The review loop: a fresh interview can be scheduled again.
        second = schedule_interview(
            application["id"],
            scheduled_start="2026-09-06T14:00:00Z",
            scheduled_end="2026-09-06T15:00:00Z",
        )
        assert second["status"] == "SCHEDULED"
        assert get_application(application["id"])["status"] == "INTERVIEWING"

    def test_interview_adjacency_allowed_overlap_rejected(self):
        """PRD §3.3: "One officer's calendar may not double-book: for the
        same `interviewer_id`, the new window must not overlap any existing
        `SCHEDULED` interview, where two half-open windows overlap exactly
        when the new one starts before the existing one ends and the existing
        one starts before the new one ends. Adjacency is allowed — a window
        beginning precisely when another ends does not overlap, and neither
        does one ending precisely when another begins — and a genuine overlap
        is rejected with `ERR_INTERVIEW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/interview_half_open_adjacency_allowed_overlap_rejected
        """
        set_clock(DEFAULT_CLOCK_START)
        # Existing SCHEDULED interview 14:00-15:00 for interviewer officer-1.
        _under_review_with_interview()

        bob = create_applicant()
        bob_app = create_application(bob["id"])
        submit_application(bob_app["id"], bob["id"])
        begin_review(bob_app["id"])
        # Adjacent: starts exactly when the existing interview ends.
        adjacent = schedule_interview(
            bob_app["id"],
            scheduled_start="2026-09-05T15:00:00Z",
            scheduled_end="2026-09-05T16:00:00Z",
        )
        assert adjacent["status"] == "SCHEDULED"
        assert get_application(bob_app["id"])["status"] == "INTERVIEWING"

        cy = create_applicant()
        cy_app = create_application(cy["id"])
        submit_application(cy_app["id"], cy["id"])
        begin_review(cy_app["id"])
        # Strictly overlapping: 14:30 < 15:00 and 14:00 < 15:30.
        validate_error(
            api_client.create_interview(
                cy_app["id"],
                {"interviewer_id": "officer-1",
                 "scheduled_start": "2026-09-05T14:30:00Z",
                 "scheduled_end": "2026-09-05T15:30:00Z"},
                PLACER),
            ApiErrorId.ERR_INTERVIEW_OVERLAP, 409)
        assert get_application(cy_app["id"])["status"] == "UNDER_REVIEW", \
            "a rejected interview must not move the application"

    def test_cancelled_interviews_no_longer_constrain_calendar(self):
        """PRD §3.3: "Completed or cancelled interviews no longer constrain
        the calendar."
        PRD §3.3: "a genuine overlap is rejected with `ERR_INTERVIEW_OVERLAP`
        (HTTP 409). Completed or cancelled interviews no longer constrain the
        calendar."

        Design: Difficulty/resource_temporal_overlap/interview_half_open_adjacency_allowed_overlap_rejected
        """
        set_clock(DEFAULT_CLOCK_START)
        _, application, interview = _under_review_with_interview()
        validate_success(api_client.cancel_interview(interview["id"], PLACER), 200)
        assert get_application(application["id"])["status"] == "UNDER_REVIEW"

        # The 14:30-15:30 window overlapped the cancelled 14:00-15:00 one;
        # with the cancellation it is schedulable for the same interviewer.
        bob = create_applicant()
        bob_app = create_application(bob["id"])
        submit_application(bob_app["id"], bob["id"])
        begin_review(bob_app["id"])
        freed = schedule_interview(
            bob_app["id"],
            scheduled_start="2026-09-05T14:30:00Z",
            scheduled_end="2026-09-05T15:30:00Z",
        )
        assert freed["status"] == "SCHEDULED"
        assert get_application(bob_app["id"])["status"] == "INTERVIEWING"
