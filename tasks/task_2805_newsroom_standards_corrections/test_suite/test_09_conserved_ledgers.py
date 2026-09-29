"""Ledgers that must land back on their opening balance to the unit."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as W
from test_helpers import make_executive_editor_headers


class TestReviewerMinutesSurviveBookAndRelease:
    """``reserved_minutes + available_minutes`` before, during and after."""

    def _two_booked_slots(self, api, desk):
        reviewer = W.add_legal_reviewer(
            api, desk, full_name="Kai Brandt", weekly_capacity_minutes=600
        )
        A.assert_minute_ledger(reviewer, 0, 600)
        story = W.open_story(
            api,
            desk,
            "Disputed testimony from the zoning hearing",
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
        second = W.book_slot(
            api,
            desk,
            review["id"],
            reviewer,
            "2026-08-04T11:00:00Z",
            "2026-08-04T12:30:00Z",
        )
        return reviewer, first, second

    def test_two_bookings_of_different_lengths_commit_their_exact_sum(
        self, api, desk
    ):
        """Sixty and ninety minutes commit one hundred and fifty.

        PRD §3.4: "The system guarantees that `reserved_minutes` and
        `available_minutes` always sum to exactly `weekly_capacity_minutes`,
        before and after every operation, cascades included." PRD §3.4 also
        computes the committed total by re-aggregation rather than arithmetic on
        the running figure: "It is always recomputed as the sum of
        `duration_minutes` over every booking of that reviewer whose `status` is
        `SCHEDULED`."

        Design: Difficulty/compensating_invariant/reviewer_minutes_conserved_across_two_bookings_and_their_cancellations
        """
        reviewer, first, second = self._two_booked_slots(api, desk)

        assert first["duration_minutes"] == 60
        assert second["duration_minutes"] == 90

        committed = W.read_reviewer(api, desk, reviewer["id"])
        A.assert_minute_ledger(committed, 150, 450)
        A.assert_minutes_conserved(committed)

    def test_releasing_both_slots_in_reverse_order_restores_the_balance(
        self, api, desk
    ):
        """The cancellations compensate exactly, with no drift.

        PRD §3.4: "Releasing a slot deliberately is the compensating action for
        booking it. A `LegalCounsel`, `StandardsEditor` or `ExecutiveEditor`
        cancels a `SCHEDULED` booking by supplying a `cancellation_reason`, which
        is stored on the record; the booking moves `SCHEDULED → CANCELLED`, the
        reviewer's ledger is re-aggregated so the minutes return to
        `available_minutes` and leave `reserved_minutes`, and the reviewer's
        `version` is incremented by one." PRD §3.4 adds that "`COMPLETED` and
        `CANCELLED` bookings contribute zero".

        Design: Difficulty/compensating_invariant/reviewer_minutes_conserved_across_two_bookings_and_their_cancellations
        """
        reviewer, first, second = self._two_booked_slots(api, desk)

        W.cancel_slot(api, desk, second["id"])
        after_first_release = W.read_reviewer(api, desk, reviewer["id"])
        A.assert_minute_ledger(after_first_release, 60, 540)

        W.cancel_slot(api, desk, first["id"])
        restored = W.read_reviewer(api, desk, reviewer["id"])
        A.assert_minute_ledger(restored, 0, 600)
        A.assert_minutes_conserved(restored)

        assert (
            W.read_assignment(api, desk, first["id"])["status"]
            == C.ASSIGNMENT_CANCELLED
        )
        assert (
            W.read_assignment(api, desk, second["id"])["status"]
            == C.ASSIGNMENT_CANCELLED
        )


class TestPenaltyPointsSurviveAnOverturnedFinding:
    """The journalist ledger is a re-aggregation, not a running balance."""

    def _two_sustained_findings_and_a_second_editor(self, api, desk):
        appeal_hearer = W.add_journalist(
            api,
            desk,
            "Iris Halloran",
            "iris@ledger.test",
            C.TITLE_EXECUTIVE_EDITOR,
        )
        first = W.sustained_investigation(
            api,
            desk,
            desk.reporter_id,
            C.ALLEGATION_PLAGIARISM,
            C.SEVERITY_SERIOUS,
            allegation_summary="Two paragraphs lifted from a trade publication.",
        )
        W.set_clock(api, desk, "2026-08-02T00:00:00Z")
        second = W.sustained_investigation(
            api,
            desk,
            desk.reporter_id,
            C.ALLEGATION_FABRICATION,
            C.SEVERITY_EGREGIOUS,
            allegation_summary="A quoted official does not exist.",
        )
        return appeal_hearer, first, second

    def test_the_second_finding_takes_the_repeat_surcharge_and_suspends(
        self, api, desk
    ):
        """Nine, plus three for fabrication, plus two for the prior, is fourteen.

        PRD §3.7: "First the desk counts how many of this journalist's other
        investigations were already `SUSTAINED` with a `decided_at` strictly
        earlier than the logical clock's current reading, ordering by
        `decided_at` ascending with `created_at` ascending as the tie-break; that
        count is stored on the case as `prior_sustained_count`." PRD §3.7 then
        sums: "the severity's base — 2 points for `MINOR`, 5 for `SERIOUS`, 9 for
        `EGREGIOUS` — plus a 3-point surcharge when `allegation_type` is
        `FABRICATION`, plus a 2-point repeat surcharge when
        `prior_sustained_count` is 1 or more." PRD §3.7 keeps the journalist's own
        figure as "the full sum of `penalty_points` over every investigation of
        that journalist whose `status` is `SUSTAINED`".

        Design: Difficulty/compensating_invariant/journalist_points_conserved_when_second_sustained_finding_is_overturned
        """
        _, first, second = self._two_sustained_findings_and_a_second_editor(
            api, desk
        )

        assert first["penalty_points"] == 5
        assert second["prior_sustained_count"] == 1
        assert second["penalty_points"] == 14

        reporter = W.read_journalist(api, desk, desk.reporter_id)
        assert reporter["penalty_points"] == 19
        assert reporter["employment_status"] == C.EMPLOYMENT_SUSPENDED

    def test_overturning_the_second_finding_returns_the_ledger_to_five(
        self, api, desk
    ):
        """The compensating action re-sums what is left, and lifts the suspension.

        PRD §3.7: "An `OVERTURNED` outcome is the compensating action for the
        sustained decision. It takes the case `SUSTAINED → OVERTURNED`, which is
        terminal, records `appeal_outcome` as `OVERTURNED`, resets the case's own
        `penalty_points` to 0 and its `disclosure_obligation` to `NONE`, and
        re-runs the journalist's ledger as the sum over their remaining
        `SUSTAINED` investigations. If that sum falls below 12, the journalist's
        `employment_status` returns `SUSPENDED → ACTIVE` with their `version`
        advanced by one."

        Design: Difficulty/compensating_invariant/journalist_points_conserved_when_second_sustained_finding_is_overturned
        """
        appeal_hearer, first, second = (
            self._two_sustained_findings_and_a_second_editor(api, desk)
        )

        overturned = get_success_data(
            api.appeal_investigation(
                second["id"],
                F.appeal_payload(
                    C.APPEAL_OVERTURNED,
                    "The disputed source has been produced and verified.",
                ),
                make_executive_editor_headers(appeal_hearer["id"]),
            )
        )

        assert overturned["status"] == C.INVESTIGATION_OVERTURNED
        assert overturned["appeal_outcome"] == C.APPEAL_OVERTURNED
        assert overturned["penalty_points"] == 0
        assert overturned["disclosure_obligation"] == C.OBLIGATION_NONE

        untouched = W.read_investigation(api, desk, first["id"])
        assert untouched["status"] == C.INVESTIGATION_SUSTAINED
        assert untouched["penalty_points"] == 5

        reporter = W.read_journalist(api, desk, desk.reporter_id)
        assert reporter["penalty_points"] == 5
        assert reporter["employment_status"] == C.EMPLOYMENT_ACTIVE
