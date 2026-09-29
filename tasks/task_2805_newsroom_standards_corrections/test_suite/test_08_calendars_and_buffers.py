"""Two contended calendars whose interval arithmetic differs on purpose."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as W


class TestOutsideActivityHalfOpenWindow:
    """A journalist's own calendar, running ``[starts_on, ends_on)``."""

    def _approved_consulting_and_two_pending_requests(self, api, desk):
        approved = W.approved_activity(
            api,
            desk,
            "2026-09-01T00:00:00Z",
            "2026-09-10T00:00:00Z",
            activity_type=C.ACTIVITY_CONSULTING,
            compensated=True,
            related_beat="transit",
            host_organization="Civic Data Lab",
        )
        touching = W.request_activity(
            api,
            desk,
            "2026-09-10T00:00:00Z",
            "2026-09-15T00:00:00Z",
            activity_type=C.ACTIVITY_SPEAKING,
            compensated=False,
            related_beat="transit",
            host_organization="State Press Club",
        )
        overlapping = W.request_activity(
            api,
            desk,
            "2026-09-09T00:00:00Z",
            "2026-09-12T00:00:00Z",
            activity_type=C.ACTIVITY_BOARD_SERVICE,
            compensated=False,
            related_beat="transit",
            host_organization="Riverside Trust",
        )
        return approved, touching, overlapping

    def test_an_engagement_starting_when_another_ends_is_admitted(
        self, api, desk
    ):
        """A zero-length gap is not an overlap on a half-open window.

        PRD §3.8: "That window is half-open, running from `starts_on` inclusive
        up to but excluding `ends_on`: an overlap exists when the new `starts_on`
        falls strictly before the other request's `ends_on` and the other
        request's `starts_on` falls strictly before the new `ends_on`. Touching
        endpoints are therefore admissible — a new engagement beginning at the
        exact instant an approved one ends is accepted."

        Design: Difficulty/resource_temporal_overlap/outside_activity_half_open_window_admits_touching_endpoints_rejects_true_overlap
        """
        _, touching, _ = self._approved_consulting_and_two_pending_requests(
            api, desk
        )

        decided = W.decide_activity(api, desk, touching["id"], C.DECISION_APPROVE)

        assert decided["status"] == C.ACTIVITY_APPROVED
        A.assert_declared_instant(decided["decided_at"])

    def test_a_genuine_intersection_is_refused_and_leaves_the_row_requested(
        self, api, desk
    ):
        """A window running through an occupied one is a true overlap.

        PRD §3.8: "any true intersection is refused with
        `ERR_OUTSIDE_ACTIVITY_OVERLAP`." Only decided rows occupy the calendar,
        because PRD §3.8 measures the overlap against "any already-`APPROVED`
        activity of the same journalist", and a refused decision leaves the
        request where PRD §3.8 created it: "The request is created in `status`
        `REQUESTED`."

        Design: Difficulty/resource_temporal_overlap/outside_activity_half_open_window_admits_touching_endpoints_rejects_true_overlap
        """
        approved, touching, overlapping = (
            self._approved_consulting_and_two_pending_requests(api, desk)
        )
        W.decide_activity(api, desk, touching["id"], C.DECISION_APPROVE)

        response = api.decide_activity_request(
            overlapping["id"],
            F.activity_decision_payload(C.DECISION_APPROVE),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_OUTSIDE_ACTIVITY_OVERLAP, 409)

        refused = W.read_activity_request(api, desk, overlapping["id"])
        assert refused["status"] == C.ACTIVITY_REQUESTED
        assert refused["decided_at"] is None
        assert (
            W.read_activity_request(api, desk, approved["id"])["status"]
            == C.ACTIVITY_APPROVED
        )


class TestReviewerSlotTurnaroundBuffer:
    """A reviewer's ledger, whose slots are widened by half an hour each side."""

    def _reviewer_holding_a_nine_to_ten_slot(self, api, desk):
        reviewer = W.add_legal_reviewer(
            api, desk, full_name="Kai Brandt", weekly_capacity_minutes=600
        )
        story = W.open_story(
            api,
            desk,
            "Allegations against the harbor authority",
            defamation_claim_count=2,
            privacy_subject_count=1,
        )
        review = W.submit_review(api, desk, story["id"], high_risk_declared=True)
        first = W.book_slot(
            api,
            desk,
            review["id"],
            reviewer,
            "2026-08-04T09:00:00Z",
            "2026-08-04T10:00:00Z",
        )
        return reviewer, review, first

    def test_a_twenty_nine_minute_gap_collides(self, api, desk):
        """One minute inside the buffer is a collision.

        PRD §3.4: "a collision exists when the new slot's `starts_at` falls
        earlier than the other slot's `ends_at` extended by thirty minutes and
        the other slot's `starts_at` falls earlier than the new slot's `ends_at`
        extended by thirty minutes. In practice, a slot that begins exactly
        thirty minutes after another one ends is admissible, while one that
        begins twenty-nine minutes after is refused with
        `ERR_REVIEWER_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/reviewer_slot_closed_interval_buffer_rejects_twenty_nine_minute_gap_admits_thirty
        """
        reviewer, review, first = self._reviewer_holding_a_nine_to_ten_slot(
            api, desk
        )

        response = api.create_assignment(
            F.assignment_payload(
                review["id"],
                reviewer["id"],
                "2026-08-04T10:29:00Z",
                "2026-08-04T11:29:00Z",
                W.reviewer_version(api, desk, reviewer["id"]),
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_REVIEWER_SLOT_CONFLICT, 409)

        unchanged = W.read_reviewer(api, desk, reviewer["id"])
        A.assert_minute_ledger(unchanged, 60, 540)
        assert (
            W.read_assignment(api, desk, first["id"])["status"]
            == C.ASSIGNMENT_SCHEDULED
        )

    def test_a_gap_of_exactly_thirty_minutes_is_admitted(self, api, desk):
        """The buffer's own edge is admissible, and the minutes accumulate.

        PRD §3.4: "a slot that begins exactly thirty minutes after another one
        ends is admissible". PRD §3.4 derives the second slot's length the same
        way as the first: "the server derives `duration_minutes` as the number of
        whole minutes between the two instants: take the elapsed seconds, divide
        by 60 and truncate downward."

        Design: Difficulty/resource_temporal_overlap/reviewer_slot_closed_interval_buffer_rejects_twenty_nine_minute_gap_admits_thirty
        """
        reviewer, review, first = self._reviewer_holding_a_nine_to_ten_slot(
            api, desk
        )

        second = W.book_slot(
            api,
            desk,
            review["id"],
            reviewer,
            "2026-08-04T10:30:00Z",
            "2026-08-04T11:30:00Z",
        )

        assert second["duration_minutes"] == 60
        assert second["status"] == C.ASSIGNMENT_SCHEDULED
        A.assert_minute_ledger(W.read_reviewer(api, desk, reviewer["id"]), 120, 480)
        assert (
            W.read_assignment(api, desk, first["id"])["status"]
            == C.ASSIGNMENT_SCHEDULED
        )
