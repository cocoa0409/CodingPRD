"""Requests that break two rules at once, and which refusal the caller sees."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as W


class TestPublishOfADraftUnderLockdown:
    """State (priority 12) against posture (priority 19)."""

    def _locked_desk_with_an_unreviewed_story(self, api):
        desk = W.build_desk(api, high_severity_open_threshold=1)
        W.lockdown_desk(api, desk)
        follow_up = W.open_story(
            api,
            desk,
            "The follow-up nobody has reviewed yet",
            defamation_claim_count=1,
        )
        return desk, follow_up

    def test_the_draft_state_complaint_outranks_the_posture_complaint(
        self, api
    ):
        """Both rules are broken, and the lower ladder step answers.

        PRD §2.12: "When a single request violates more than one rule, the
        response reports the violation that comes first in the following
        ladder. The ordering is normative, because it decides which of several
        plausible error identifiers the caller actually sees." Step 12 of that
        ladder is "Publish requires `publication_status` `CLEARED` —
        `ERR_STORY_NOT_CLEARED`" and step 19 is "Posture must not be `LOCKDOWN`
        when clearing a review or publishing a story — `ERR_POSTURE_LOCKDOWN`".

        Design: Difficulty/priority_pair_validation_conflict/publish_draft_under_lockdown_returns_story_not_cleared_not_posture_lockdown
        """
        desk, follow_up = self._locked_desk_with_an_unreviewed_story(api)

        response = api.publish_story(follow_up["id"], {}, desk.exec_headers)

        validate_error(response, E.ERR_STORY_NOT_CLEARED, 409)

    def test_neither_the_posture_nor_the_story_moves_on_the_refusal(
        self, api
    ):
        """The refused publication leaves the desk exactly as it found it.

        PRD §2.9: "When `open_high_severity_count` reaches twice the threshold
        or more, the posture is `LOCKDOWN`." PRD §3.2 declares that a story
        "opens with `publication_status` `DRAFT` and `standards_status` `CLEAN`
        ... and with `risk_index_actual`, `published_at`, `unpublished_at` and
        `editors_note_text` all null", and PRD §3.5 stamps `published_at` only
        when a publication actually succeeds.

        Design: Difficulty/priority_pair_validation_conflict/publish_draft_under_lockdown_returns_story_not_cleared_not_posture_lockdown
        """
        desk, follow_up = self._locked_desk_with_an_unreviewed_story(api)

        api.publish_story(follow_up["id"], {}, desk.exec_headers)

        A.assert_posture(W.read_newsroom(api, desk), C.POSTURE_LOCKDOWN, 2)

        reread = W.read_story(api, desk, follow_up["id"])
        assert reread["publication_status"] == C.PUB_DRAFT
        assert reread["published_at"] is None


class TestBookingAForeignReviewerBeyondCapacity:
    """Referential integrity (priority 26) against capacity (priority 35)."""

    def _foreign_reviewer_and_an_open_legal_round(self, api, desk):
        other_newsroom = get_success_data(
            api.create_newsroom(
                F.newsroom_payload(
                    name="Harbor Dispatch",
                    correction_response_sla_hours=48,
                    high_severity_open_threshold=3,
                ),
                desk.exec_headers,
            )
        )
        foreign_reviewer = get_success_data(
            api.create_reviewer(
                F.reviewer_payload(
                    other_newsroom["id"],
                    "Kai Brandt",
                    C.DISCIPLINE_LEGAL,
                    weekly_capacity_minutes=60,
                ),
                desk.exec_headers,
            )
        )
        story = W.open_story(
            api,
            desk,
            "Contested claims about the harbor lease",
            defamation_claim_count=3,
            privacy_subject_count=1,
        )
        review = W.submit_review(api, desk, story["id"], high_risk_declared=True)
        return foreign_reviewer, review

    def test_the_cross_newsroom_reference_outranks_the_capacity_overrun(
        self, api, desk
    ):
        """A two-hour slot on a foreign one-hour reviewer answers referentially.

        PRD §2.12 step 26 is "Cross-newsroom references on `POST
        /standards-desk/stories` and `POST /standards-desk/review-assignments` —
        `ERR_CROSS_NEWSROOM_REFERENCE`" and step 35 is "Reviewer weekly capacity
        — `ERR_REVIEWER_CAPACITY_EXCEEDED`". PRD §3.4 fixes the same order for
        this endpoint on its own terms: "Three further checks stand between a
        booking request and a reserved slot, and they are evaluated in the order
        given here. First, the reviewer must belong to the same newsroom as the
        review's story, or the request is refused with
        `ERR_CROSS_NEWSROOM_REFERENCE`." Capacity comes after all three: "Last
        comes the capacity test."

        Design: Difficulty/priority_pair_validation_conflict/assignment_cross_newsroom_reviewer_beats_capacity_exceeded
        """
        foreign_reviewer, review = self._foreign_reviewer_and_an_open_legal_round(
            api, desk
        )

        response = api.create_assignment(
            F.assignment_payload(
                review["id"],
                foreign_reviewer["id"],
                "2026-08-04T09:00:00Z",
                "2026-08-04T11:00:00Z",
                foreign_reviewer["version"],
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_CROSS_NEWSROOM_REFERENCE, 422)

    def test_the_refused_booking_reserves_no_minutes_and_leaves_the_round_open(
        self, api, desk
    ):
        """Nothing is written on the reviewer or on the round.

        PRD §3.4: "`reserved_minutes` is never adjusted by a delta. It is always
        recomputed as the sum of `duration_minutes` over every booking of that
        reviewer whose `status` is `SCHEDULED`; `COMPLETED` and `CANCELLED`
        bookings contribute zero. `available_minutes` is then the reviewer's
        `weekly_capacity_minutes` less that sum." PRD §3.3 leaves the round
        where it was, because "On a round that requires legal review, the
        standards verdict may only be recorded once the round is
        `LEGAL_CLEARED`".

        Design: Difficulty/priority_pair_validation_conflict/assignment_cross_newsroom_reviewer_beats_capacity_exceeded
        """
        foreign_reviewer, review = self._foreign_reviewer_and_an_open_legal_round(
            api, desk
        )

        api.create_assignment(
            F.assignment_payload(
                review["id"],
                foreign_reviewer["id"],
                "2026-08-04T09:00:00Z",
                "2026-08-04T11:00:00Z",
                foreign_reviewer["version"],
            ),
            desk.sed_headers,
        )

        reread = get_success_data(
            api.get_reviewer(foreign_reviewer["id"], desk.exec_headers)
        )
        A.assert_minute_ledger(reread, 0, 60)
        assert (
            W.read_review(api, desk, review["id"])["status"] == C.REVIEW_SUBMITTED
        )


class TestApprovingAnActivityWithBothAPendingDisclosureAndAnOverlap:
    """Disclosure hygiene (priority 28) against the calendar (priority 32)."""

    def _pending_disclosure_and_an_overlapping_request(self, api, desk):
        first = W.approved_activity(
            api,
            desk,
            "2026-09-01T00:00:00Z",
            "2026-09-10T00:00:00Z",
            activity_type=C.ACTIVITY_CONSULTING,
            compensated=True,
            related_beat="energy",
            host_organization="Northline Advisory",
        )
        disclosure = W.file_disclosure(
            api,
            desk,
            disclosure_type=C.DISCLOSURE_FINANCIAL,
            subject_entity_name="Northline Advisory",
            description=(
                "Holding acquired in the consulting client after the engagement "
                "began."
            ),
        )
        second = W.request_activity(
            api,
            desk,
            "2026-09-05T00:00:00Z",
            "2026-09-15T00:00:00Z",
            activity_type=C.ACTIVITY_SPEAKING,
            compensated=True,
            related_beat="energy",
            host_organization="Northline Advisory",
        )
        return first, disclosure, second

    def test_the_pending_disclosure_outranks_the_overlapping_window(
        self, api, desk
    ):
        """An unreviewed conflict filing answers before the calendar clash.

        PRD §2.12 step 28 is "Outside-activity approval requires no pending
        disclosure — `ERR_COI_DISCLOSURE_PENDING`" and step 32 is
        "Outside-activity interval overlap — `ERR_OUTSIDE_ACTIVITY_OVERLAP`".
        PRD §3.8 states the same order for the approval itself: "Approval
        requires, in order, that the journalist has no conflict disclosure still
        sitting in `SUBMITTED` — an unreviewed disclosure blocks all outside work
        with `ERR_COI_DISCLOSURE_PENDING`; that the request's `related_beat` is
        not a member of the journalist's `restricted_beats` ...; and that the
        requested window does not overlap any already-`APPROVED` activity of the
        same journalist."

        Design: Difficulty/priority_pair_validation_conflict/activity_approval_pending_disclosure_beats_interval_overlap
        """
        _, _, second = self._pending_disclosure_and_an_overlapping_request(
            api, desk
        )

        response = api.decide_activity_request(
            second["id"],
            F.activity_decision_payload(C.DECISION_APPROVE),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_COI_DISCLOSURE_PENDING, 422)

    def test_the_refusal_leaves_all_three_records_where_they_were(
        self, api, desk
    ):
        """The requested activity is not approved, and nothing else shifts.

        PRD §3.8: an outside-activity request "is created in `status`
        `REQUESTED`", a conflict disclosure "is created in `status` `SUBMITTED`
        with `restricted_beats` as an empty array", and it is the decision that
        takes "the request `REQUESTED → APPROVED` or `REQUESTED → DENIED`".

        Design: Difficulty/priority_pair_validation_conflict/activity_approval_pending_disclosure_beats_interval_overlap
        """
        first, disclosure, second = (
            self._pending_disclosure_and_an_overlapping_request(api, desk)
        )

        api.decide_activity_request(
            second["id"],
            F.activity_decision_payload(C.DECISION_APPROVE),
            desk.sed_headers,
        )

        assert (
            W.read_activity_request(api, desk, second["id"])["status"]
            == C.ACTIVITY_REQUESTED
        )
        assert (
            W.read_activity_request(api, desk, first["id"])["status"]
            == C.ACTIVITY_APPROVED
        )
        assert (
            W.read_disclosure(api, desk, disclosure["id"])["status"]
            == C.DISCLOSURE_SUBMITTED
        )
