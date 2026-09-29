"""Thresholds that admit the value sitting exactly on them."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as W


class TestPostureTripsAtTheThresholdItself:
    """``open_high_severity_count`` against ``high_severity_open_threshold``."""

    def _carrier_story(self, api, desk):
        return W.open_story(
            api,
            desk,
            "Two disputed identifications",
            defamation_claim_count=0,
            privacy_subject_count=0,
            unverified_document_count=0,
        )

    def _adjudicated_identification_complaint(
        self, api, desk, story_id, label, claim, notice_text
    ):
        """File, investigate and adjudicate one ``SEVERE`` complaint.

        The three steps run to completion before the next complaint is filed,
        because PRD §3.6 admits intake only "while the story's
        `standards_status` is `CLEAN` or `CORRECTED`" and drives that dimension
        to `UNDER_INQUIRY` on the way in. Adjudicating each complaint returns
        the story to `CORRECTED`, which is the edge the next intake needs.
        """
        request = W.file_correction(
            api,
            desk,
            story_id,
            submitter_type=C.SUBMITTER_SUBJECT,
            submitter_email=f"{label}@subject.test",
            claim_text=claim,
            claimed_error_category=C.CATEGORY_IDENTIFICATION,
            reader_reported_reach=150000,
            subject_named=True,
        )
        W.start_investigation(api, desk, request["id"])
        return W.adjudicate(
            api,
            desk,
            request["id"],
            C.OUTCOME_CORRECTION,
            C.CATEGORY_IDENTIFICATION,
            150000,
            notice_text=notice_text,
        )

    def test_one_case_short_of_the_threshold_leaves_the_desk_open(
        self, api, desk
    ):
        """A count of one against a threshold of two is still ``OPEN``.

        PRD §2.9: "Below the threshold it is `OPEN`." The default threshold is
        the one in force here, which PRD §2.9 gives as "an integer between 1 and
        20 inclusive, defaulting to 2".

        Design: Difficulty/boundary_precision_check/posture_flips_exactly_at_high_severity_open_threshold_not_one_below
        """
        story = self._carrier_story(api, desk)

        self._adjudicated_identification_complaint(
            api,
            desk,
            story["id"],
            "first",
            "The first name attached to the settlement is not mine.",
            "An earlier version named the wrong party to the settlement.",
        )

        newsroom = W.read_newsroom(api, desk)
        assert newsroom["high_severity_open_threshold"] == 2
        A.assert_posture(newsroom, C.POSTURE_OPEN, 1)

    def test_reaching_the_threshold_exactly_escalates_to_heightened(
        self, api, desk
    ):
        """A count of two against a threshold of two is already ``HEIGHTENED``.

        PRD §2.9: "When `open_high_severity_count` reaches twice the threshold or
        more, the posture is `LOCKDOWN`. Otherwise, when it reaches the threshold
        or more, the posture is `HEIGHTENED`. Below the threshold it is `OPEN`.
        Both comparisons are inclusive: a count exactly equal to the threshold is
        already `HEIGHTENED`, and a count exactly equal to double the threshold
        is already `LOCKDOWN`." Two is the threshold and not yet its double, so
        the desk stops at `HEIGHTENED`.

        Design: Difficulty/boundary_precision_check/posture_flips_exactly_at_high_severity_open_threshold_not_one_below
        """
        story = self._carrier_story(api, desk)

        self._adjudicated_identification_complaint(
            api,
            desk,
            story["id"],
            "first",
            "The first name attached to the settlement is not mine.",
            "An earlier version named the wrong party to the settlement.",
        )
        second = self._adjudicated_identification_complaint(
            api,
            desk,
            story["id"],
            "second",
            "The second name is also wrong.",
            "A second party was also misnamed.",
        )

        A.assert_adjudicated_severity(second, 21, C.BAND_SEVERE)
        A.assert_posture(W.read_newsroom(api, desk), C.POSTURE_HEIGHTENED, 2)
        A.assert_story_counters(
            W.read_story(api, desk, story["id"]), severe_corrections=2
        )


class TestCapacityAdmitsTheExactlyFullBooking:
    """``reserved_minutes + duration_minutes`` against the weekly capacity."""

    def _reviewer_with_nine_hours_booked(self, api, desk):
        reviewer = W.add_legal_reviewer(
            api, desk, full_name="Kai Brandt", weekly_capacity_minutes=600
        )
        story = W.open_story(
            api,
            desk,
            "The lease documents nobody will confirm",
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
            "2026-08-04T18:00:00Z",
        )
        assert first["duration_minutes"] == 540
        A.assert_minute_ledger(
            W.read_reviewer(api, desk, reviewer["id"]), 540, 60
        )
        return reviewer, review, first

    def test_the_booking_that_lands_exactly_on_capacity_is_admitted(
        self, api, desk
    ):
        """Six hundred of six hundred minutes is accepted, not refused.

        PRD §3.4: "The reviewer's `reserved_minutes` as they stand before the
        booking, plus the new slot's `duration_minutes`, must be no greater than
        `weekly_capacity_minutes`. Equality is admissible — a booking that
        consumes the reviewer's last remaining minute exactly is accepted — while
        exceeding the capacity by even one minute is refused with
        `ERR_REVIEWER_CAPACITY_EXCEEDED`." PRD §3.4 also guarantees that
        "`reserved_minutes` and `available_minutes` always sum to exactly
        `weekly_capacity_minutes`".

        Design: Difficulty/boundary_precision_check/assignment_admitted_when_reserved_plus_new_equals_capacity_exactly
        """
        reviewer, review, _ = self._reviewer_with_nine_hours_booked(api, desk)

        second = W.book_slot(
            api,
            desk,
            review["id"],
            reviewer,
            "2026-08-04T19:00:00Z",
            "2026-08-04T20:00:00Z",
        )

        assert second["duration_minutes"] == 60
        assert second["status"] == C.ASSIGNMENT_SCHEDULED
        filled = W.read_reviewer(api, desk, reviewer["id"])
        A.assert_minute_ledger(filled, 600, 0)
        A.assert_minutes_conserved(filled)

    def test_the_next_minute_of_demand_is_refused_and_changes_nothing(
        self, api, desk
    ):
        """With the ledger exactly full, one more hour is over capacity.

        PRD §3.4: "exceeding the capacity by even one minute is refused with
        `ERR_REVIEWER_CAPACITY_EXCEEDED`. Because the admission test runs first,
        `available_minutes` can never go negative." PRD §3.4 counts the ledger by
        full re-aggregation: "It is always recomputed as the sum of
        `duration_minutes` over every booking of that reviewer whose `status` is
        `SCHEDULED`."

        Design: Difficulty/boundary_precision_check/assignment_admitted_when_reserved_plus_new_equals_capacity_exactly
        """
        reviewer, review, first = self._reviewer_with_nine_hours_booked(api, desk)
        W.book_slot(
            api,
            desk,
            review["id"],
            reviewer,
            "2026-08-04T19:00:00Z",
            "2026-08-04T20:00:00Z",
        )

        response = api.create_assignment(
            F.assignment_payload(
                review["id"],
                reviewer["id"],
                "2026-08-04T21:00:00Z",
                "2026-08-04T22:00:00Z",
                W.reviewer_version(api, desk, reviewer["id"]),
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_REVIEWER_CAPACITY_EXCEEDED, 422)

        unchanged = W.read_reviewer(api, desk, reviewer["id"])
        A.assert_minute_ledger(unchanged, 600, 0)
        assert (
            W.read_assignment(api, desk, first["id"])["status"]
            == C.ASSIGNMENT_SCHEDULED
        )
