"""One write that travels four links down the desk's dependency chain."""

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import fixtures as W


class TestAdjudicationReachesTheDeskPosture:
    """Correction → story → newsroom count → newsroom posture."""

    def _severe_identification_adjudication(self, api):
        desk = W.build_desk(api, high_severity_open_threshold=1)
        story = W.open_story(
            api,
            desk,
            "Who signed the demolition order",
            defamation_claim_count=3,
            privacy_subject_count=1,
            unverified_document_count=0,
        )
        request = W.file_correction(
            api,
            desk,
            story["id"],
            submitter_type=C.SUBMITTER_SUBJECT,
            submitter_email="legal@sunsetblock.test",
            claim_text=(
                "The story names our client as the signatory; she never signed "
                "the order."
            ),
            claimed_error_category=C.CATEGORY_IDENTIFICATION,
            reader_reported_reach=150000,
            subject_named=True,
        )
        W.start_investigation(api, desk, request["id"])
        adjudicated = W.adjudicate(
            api,
            desk,
            request["id"],
            C.OUTCOME_CORRECTION,
            C.CATEGORY_IDENTIFICATION,
            150000,
            notice_text=(
                "An earlier version named the wrong signatory on the "
                "demolition order."
            ),
        )
        return desk, story, adjudicated

    def test_the_severe_finding_lands_on_the_request_and_on_its_story(
        self, api
    ):
        """Links one and two: the request is graded and the story is marked.

        PRD §3.6: "When `outcome_type` is anything other than `NO_ACTION`, the
        request moves to `ADJUDICATED`; `adjudicated_severity_score`,
        `adjudicated_severity_band` and `placement` are computed; the story's
        `standards_status` becomes `CORRECTED`; when the adjudicated band is
        `MAJOR` or `SEVERE` the story's `severe_correction_count` is
        incremented and its `risk_index_actual` recomputed". An
        `IDENTIFICATION` error (8) against a named subject (4) at a verified
        reach of 150,000 (6) raws at 18, which bands `SEVERE` and takes the
        3-point severe surcharge.

        Design: Difficulty/transitive_cascade/adjudication_cascades_correction_to_story_to_newsroom_posture
        """
        desk, story, adjudicated = self._severe_identification_adjudication(api)

        assert adjudicated["status"] == C.CORRECTION_ADJUDICATED
        A.assert_adjudicated_severity(adjudicated, 21, C.BAND_SEVERE)
        assert adjudicated["placement"] == C.PLACEMENT_TOP_OF_STORY

        reread = W.read_story(api, desk, story["id"])
        A.assert_story_counters(reread, severe_corrections=1)
        assert reread["standards_status"] == C.STD_CORRECTED

    def test_the_same_write_escalates_the_desk_wide_posture(self, api):
        """Links three and four: the pool grows and the gate trips.

        PRD §2.9 counts in that pool "the number of correction requests
        belonging to stories of this newsroom whose `status` is `ADJUDICATED`
        and whose `adjudicated_severity_band` is either `MAJOR` or `SEVERE`",
        and rules that "Otherwise, when it reaches the threshold or more, the
        posture is `HEIGHTENED`" with "Both comparisons are inclusive: a count
        exactly equal to the threshold is already `HEIGHTENED`". PRD §2.9 also
        pins when the recomputation happens: "The posture is recomputed on
        newsroom creation, on every correction adjudication and resolution, and
        on every misconduct investigation opening, decision and appeal."

        Design: Difficulty/transitive_cascade/adjudication_cascades_correction_to_story_to_newsroom_posture
        """
        desk, _, _ = self._severe_identification_adjudication(api)

        newsroom = W.read_newsroom(api, desk)

        A.assert_posture(newsroom, C.POSTURE_HEIGHTENED, 1)

        summary = W.read_summary(api, desk)
        assert summary["open_high_severity_count"] == 1
        assert summary["standards_posture"] == C.POSTURE_HEIGHTENED


class TestSustainedFabricationReachesTheMinuteLedger:
    """Investigation → journalist → activity, story and round → reviewer."""

    def _suspending_finding(self, api, desk):
        reviewer = W.add_legal_reviewer(
            api, desk, full_name="Lee Park", weekly_capacity_minutes=600
        )
        activity = W.approved_activity(
            api,
            desk,
            "2026-09-01T00:00:00Z",
            "2026-09-05T00:00:00Z",
            activity_type=C.ACTIVITY_SPEAKING,
            compensated=True,
            related_beat="courts",
            host_organization="State Bar Association",
        )
        story = W.open_story(
            api,
            desk,
            "The witness who was never in the courtroom",
            defamation_claim_count=4,
            privacy_subject_count=2,
            unverified_document_count=1,
        )
        review = W.submit_review(api, desk, story["id"], high_risk_declared=True)
        assignment = W.book_slot(
            api,
            desk,
            review["id"],
            reviewer,
            "2026-08-03T09:00:00Z",
            "2026-08-03T10:00:00Z",
        )
        A.assert_minute_ledger(
            W.read_reviewer(api, desk, reviewer["id"]), 60, 540
        )

        investigation = W.open_investigation(
            api,
            desk,
            desk.reporter_id,
            C.ALLEGATION_FABRICATION,
            C.SEVERITY_EGREGIOUS,
            story["id"],
            allegation_summary=(
                "The courtroom witness quoted at length does not exist in the "
                "court record."
            ),
        )
        W.advance_to_response_pending(api, desk, investigation["id"])
        decided = W.decide_investigation(
            api, desk, investigation["id"], C.DISPOSITION_SUSTAINED
        )
        return {
            "reviewer": reviewer,
            "activity": activity,
            "story": story,
            "review": review,
            "assignment": assignment,
            "investigation": decided,
        }

    def test_the_finding_scores_twelve_points_and_suspends_the_reporter(
        self, api, desk
    ):
        """Links one and two: the case is scored and the ledger crosses 12.

        PRD §3.7: "The case's own `penalty_points` are then the severity's base
        — 2 points for `MINOR`, 5 for `SERIOUS`, 9 for `EGREGIOUS` — plus a
        3-point surcharge when `allegation_type` is `FABRICATION`, plus a
        2-point repeat surcharge when `prior_sustained_count` is 1 or more."
        PRD §3.7 then rules: "When the recomputation leaves a journalist's
        `penalty_points` at 12 or more, their `employment_status` moves `ACTIVE
        → SUSPENDED` and their `version` advances by one." The obligation
        follows PRD §3.7 too: "A sustained `FABRICATION` at `EGREGIOUS` severity
        carries `RETRACTION_REVIEW`."

        Design: Difficulty/transitive_cascade/sustained_fabrication_cascades_suspension_to_reviewer_minute_release
        """
        built = self._suspending_finding(api, desk)
        decided = built["investigation"]

        assert decided["status"] == C.INVESTIGATION_SUSTAINED
        assert decided["penalty_points"] == 12
        assert decided["prior_sustained_count"] == 0
        assert decided["disclosure_obligation"] == C.OBLIGATION_RETRACTION_REVIEW

        reporter = W.read_journalist(api, desk, desk.reporter_id)
        assert reporter["penalty_points"] == 12
        assert reporter["employment_status"] == C.EMPLOYMENT_SUSPENDED

    def test_suspension_drags_the_activity_story_round_and_minutes_with_it(
        self, api, desk
    ):
        """Links three and four: four arms, ending at the reviewer's minutes.

        PRD §3.7: "Suspension is not a flag; it is a cascade with four arms.
        Every outside-activity request of that journalist whose `status` is
        `APPROVED` moves `APPROVED → REVOKED` with `revocation_reason` set to
        the string `JOURNALIST_SUSPENDED`. Every story led by that journalist
        whose `publication_status` is `IN_REVIEW` returns to `DRAFT`, each with
        its `version` advanced by one. Every non-terminal review round of those
        stories — any round in `SUBMITTED`, `LEGAL_CLEARED`,
        `STANDARDS_CLEARED` or `CHANGES_REQUESTED` — moves to `BLOCKED`. And
        because those rounds became `BLOCKED`, each of their `SCHEDULED`
        reviewer bookings becomes `CANCELLED`, with each affected reviewer's
        `reserved_minutes` re-aggregated, `available_minutes` following and
        `version` incremented, exactly as §3.4 describes."

        Design: Difficulty/transitive_cascade/sustained_fabrication_cascades_suspension_to_reviewer_minute_release
        """
        built = self._suspending_finding(api, desk)

        activity = W.read_activity_request(api, desk, built["activity"]["id"])
        assert activity["status"] == C.ACTIVITY_REVOKED
        assert activity["revocation_reason"] == C.SUSPENSION_REVOCATION_REASON

        story = W.read_story(api, desk, built["story"]["id"])
        assert story["publication_status"] == C.PUB_DRAFT

        review = W.read_review(api, desk, built["review"]["id"])
        assert review["status"] == C.REVIEW_BLOCKED

        assignment = W.read_assignment(api, desk, built["assignment"]["id"])
        assert assignment["status"] == C.ASSIGNMENT_CANCELLED

        reviewer = W.read_reviewer(api, desk, built["reviewer"]["id"])
        A.assert_minute_ledger(reviewer, 0, 600)
