"""Difficulty claims about half-open intervals and mandatory buffers."""

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    fixtures,
    get_assignment_data,
    validate_error,
)


class TestHalfOpenAssignmentIntervals:
    """The interval runs from started_on inclusive to scheduled_end_on
    exclusive."""

    def test_interval_inside_a_predecessors_scheduled_window_is_rejected(self, api):
        """PRD §2.10: "Assignment intervals on the same engagement and role
        must not overlap; the interval is half-open, running from `started_on`
        inclusive to `scheduled_end_on` exclusive".

        Design: Difficulty/resource_temporal_overlap/assignment_slots_are_half_open_and_adjacency_is_allowed
        """
        world = fixtures.scenario_half_open_intervals(api)
        fixtures.set_clock(api, "2026-06-15T00:00:00Z")
        fixtures.end_assignment_ok(
            api, world["reviewer_assignment"]["id"], world["ep_headers"]
        )

        response = fixtures.staff(
            api, world["engagement"]["id"], world["reviewer"]["id"], "EQ_REVIEWER",
            "2026-06-15T00:00:00Z", "2026-12-15T00:00:00Z",
            ep_headers=world["ep_headers"],
        )
        validate_error(response, ApiErrorId.ERR_ROLE_ASSIGNMENT_OVERLAP)

        ended = get_assignment_data(api, world["reviewer_assignment"]["id"])
        assert ended["status"] == "ENDED"
        assert_same_instant(ended["ended_on"], "2026-06-15T00:00:00Z")

    def test_adjacency_at_the_scheduled_end_is_admitted(self, api):
        """PRD §2.10: "an assignment that begins exactly at another's
        `scheduled_end_on` is permitted."

        Design: Difficulty/resource_temporal_overlap/assignment_slots_are_half_open_and_adjacency_is_allowed
        """
        world = fixtures.scenario_half_open_intervals(api)
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        fixtures.end_assignment_ok(
            api, world["concurring_assignment"]["id"], world["ep_headers"]
        )

        replacement = fixtures.staff_ok(
            api, world["engagement"]["id"], world["concurring"]["id"], "CONCURRING_PARTNER",
            "2026-07-01T00:00:00Z", "2027-01-01T00:00:00Z",
            ep_headers=world["ep_headers"],
        )
        assert replacement["status"] == "ACTIVE"
        assert_same_instant(replacement["started_on"], "2026-07-01T00:00:00Z")


class TestReviewSchedulingBuffer:
    """Successor reviews wait five days past the predecessor's due date."""

    def test_review_inside_the_buffer_is_rejected(self, api):
        """PRD §3.8: "the candidate's `received_on` must fall at least 5 days
        after the latest `due_on` among that reviewer's overlapping or adjacent
        reviews of that type. A request that lands inside the buffer is rejected
        with `ERR_REVIEW_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/quality_review_windows_require_a_five_day_buffer
        """
        world = fixtures.scenario_review_buffer(api)
        assert_same_instant(world["existing"]["due_on"], "2026-03-01T00:00:00Z")

        response = fixtures.create_review(
            api, world["engagement"]["id"], world["reviewer"]["id"],
            review_type="ENGAGEMENT_QUALITY_REVIEW",
            received_on="2026-03-05T00:00:00Z", due_on="2026-06-01T00:00:00Z",
            deficiency_count=0,
        )
        validate_error(response, ApiErrorId.ERR_REVIEW_WINDOW_CONFLICT)

    def test_review_exactly_five_days_after_is_admitted(self, api):
        """PRD §3.8: "The review lifecycle begins with the `START` action, which
        moves a `SCHEDULED` review to `IN_PROGRESS`."

        Design: Difficulty/resource_temporal_overlap/quality_review_windows_require_a_five_day_buffer
        """
        world = fixtures.scenario_review_buffer(api)

        review = fixtures.create_review_ok(
            api, world["engagement"]["id"], world["reviewer"]["id"],
            review_type="ENGAGEMENT_QUALITY_REVIEW",
            received_on="2026-03-06T00:00:00Z", due_on="2026-06-06T00:00:00Z",
            deficiency_count=0,
        )
        assert review["status"] == "SCHEDULED"
        assert_same_instant(review["received_on"], "2026-03-06T00:00:00Z")

    def test_buffer_is_scoped_to_the_reviewer_and_review_type(self, api):
        """PRD §3.8: "Two reviews sharing the same `reviewer_id` and the same
        `review_type` must be separated by a mandatory 5-day buffer".

        Design: Difficulty/resource_temporal_overlap/quality_review_windows_require_a_five_day_buffer
        """
        world = fixtures.scenario_review_buffer(api)

        # Same reviewer and same dates, but a different review type.
        review = fixtures.create_review_ok(
            api, world["engagement"]["id"], world["reviewer"]["id"],
            review_type="INSPECTION_READINESS",
            received_on="2026-03-05T00:00:00Z", due_on="2026-06-01T00:00:00Z",
            deficiency_count=0,
        )
        assert review["status"] == "SCHEDULED"
        assert review["review_type"] == "INSPECTION_READINESS"
