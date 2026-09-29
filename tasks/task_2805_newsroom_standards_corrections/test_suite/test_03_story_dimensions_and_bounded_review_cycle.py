"""Lifecycles that are neither a single line nor an unbounded loop."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as W


class TestStoryTwoDimensions:
    """``publication_status`` and ``standards_status`` on one story."""

    def _published_then_clarified(self, api, desk):
        story = W.published_story(
            api,
            desk,
            "Two claims about the school bond timetable",
            defamation_claim_count=2,
            privacy_subject_count=1,
            unverified_document_count=0,
        )
        request = W.file_correction(
            api,
            desk,
            story["id"],
            submitter_type=C.SUBMITTER_READER,
            submitter_email="reader@inbox.test",
            claim_text=(
                "The bond timetable paragraph omits the extension approved in June."
            ),
            claimed_error_category=C.CATEGORY_CONTEXT,
            reader_reported_reach=500,
            subject_named=False,
        )
        W.start_investigation(api, desk, request["id"])
        adjudicated = W.adjudicate(
            api,
            desk,
            request["id"],
            C.OUTCOME_CLARIFICATION,
            C.CATEGORY_CONTEXT,
            500,
            notice_text="This story has been clarified to note the June extension.",
        )
        return story, adjudicated

    def test_correction_lifecycle_leaves_the_publication_dimension_untouched(
        self, api, desk
    ):
        """A published story that is corrected stays published.

        PRD §2.11: "A story carries two independent state dimensions that
        advance on disjoint triggers." The same paragraph adds that "The two
        dimensions never interact except at one point — unpublishing writes
        both, driving `publication_status` to `UNPUBLISHED` and
        `standards_status` to `RETRACTED` in the same operation", and this
        correction is not an unpublication. PRD §3.6 supplies the two standards
        edges walked here: intake "is admissible while the story's
        `standards_status` is `CLEAN` or `CORRECTED`, and in both cases it
        drives that dimension to `UNDER_INQUIRY`", and on adjudication "the
        story's `standards_status` becomes `CORRECTED`".

        Design: Difficulty/non_linear_state_machine/story_publication_and_standards_dimensions_advance_independently
        """
        story, _ = self._published_then_clarified(api, desk)

        reread = W.read_story(api, desk, story["id"])

        A.assert_story_dimensions(reread, C.PUB_PUBLISHED, C.STD_CORRECTED)
        assert reread["published_at"] == story["published_at"]
        assert reread["unpublished_at"] is None

    def test_a_trivial_clarification_moves_neither_risk_figure(self, api, desk):
        """The standards dimension advances without repricing the story.

        PRD §3.5: the actual index "adds six points for every one of the
        story's correction requests whose `status` is `ADJUDICATED` or
        `RESOLVED` and whose `adjudicated_severity_band` is `MAJOR` or
        `SEVERE`" — and PRD §3.5 adds that "neither do adjudicated requests
        banded `TRIVIAL` or `MINOR`". Two potentially defamatory assertions (6)
        and one identifiable private individual (2) leave both indices at 8.00,
        which PRD §3.2 bands as a `risk_tier` that is "`HIGH` when
        `risk_index_estimate` is 40.00 or greater, `ELEVATED` when it is 20.00
        or greater but below 40.00, and `STANDARD` otherwise". PRD §3.6 places
        the notice: "A `CLARIFICATION` is placed at the `END_OF_STORY`."

        Design: Difficulty/non_linear_state_machine/story_publication_and_standards_dimensions_advance_independently
        """
        story, adjudicated = self._published_then_clarified(api, desk)

        A.assert_adjudicated_severity(adjudicated, 3, C.BAND_TRIVIAL)
        assert adjudicated["placement"] == C.PLACEMENT_END_OF_STORY

        reread = W.read_story(api, desk, story["id"])
        A.assert_risk_figures(
            reread, estimate=8.00, actual=8.00, tier=C.TIER_STANDARD
        )
        A.assert_story_counters(reread, severe_corrections=0)


class TestBoundedRevisionCycle:
    """The ``SUBMITTED ↔ CHANGES_REQUESTED`` loop and where it stops."""

    def test_the_loop_may_be_walked_while_the_round_is_below_the_cap(
        self, api, desk
    ):
        """Each revival counts the round up and blanks both verdicts.

        PRD §3.3: "Resubmission moves the round `CHANGES_REQUESTED →
        SUBMITTED`, increments `review_round` by one, clears both
        `legal_verdict` and `standards_verdict` back to null so the next round
        starts from a blank record, drives the story from `DRAFT` back to
        `IN_REVIEW`, recomputes `risk_index_estimate` and advances the story's
        `version` by one."

        Design: Difficulty/non_linear_state_machine/review_cannot_resubmit_after_third_round_changes_requested
        """
        story = W.open_story(
            api,
            desk,
            "Draft profile of the incoming commissioner",
            defamation_claim_count=1,
        )
        review = W.submit_review(api, desk, story["id"], high_risk_declared=False)
        assert review["review_round"] == 1
        assert review["status"] == C.REVIEW_SUBMITTED

        for expected_round in (2, 3):
            sent_back = W.record_standards_changes_required(
                api, desk, review["id"]
            )
            assert sent_back["status"] == C.REVIEW_CHANGES_REQUESTED
            assert (
                W.read_story(api, desk, story["id"])["publication_status"]
                == C.PUB_DRAFT
            )

            revived = W.resubmit_round(api, desk, review["id"])
            assert revived["review_round"] == expected_round
            assert revived["status"] == C.REVIEW_SUBMITTED
            assert revived["legal_verdict"] is None
            assert revived["standards_verdict"] is None
            assert (
                W.read_story(api, desk, story["id"])["publication_status"]
                == C.PUB_IN_REVIEW
            )

    def test_a_fourth_submission_from_the_third_round_is_refused(
        self, api, desk
    ):
        """The cycle terminates at the third round, and nothing moves.

        PRD §3.3: "This `DRAFT → IN_REVIEW → DRAFT → IN_REVIEW` loop is the
        revision cycle, and it terminates because `review_round` is capped at
        3: resubmission requires `review_round` to be less than 3, so a round
        that has already reached its third submission cannot be sent round a
        fourth time, and the attempt is refused with `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/review_cannot_resubmit_after_third_round_changes_requested
        """
        story = W.open_story(
            api,
            desk,
            "Draft profile of the incoming commissioner",
            defamation_claim_count=1,
        )
        review = W.third_round_changes_requested(api, desk, story["id"])
        assert review["review_round"] == 3
        assert review["status"] == C.REVIEW_CHANGES_REQUESTED

        response = api.resubmit_review(
            review["id"],
            F.resubmit_payload(revision_note="Fourth attempt."),
            desk.reporter_headers,
        )

        validate_error(response, E.ERR_INVALID_STATE, 409)

        unchanged = W.read_review(api, desk, review["id"])
        assert unchanged["review_round"] == 3
        assert unchanged["status"] == C.REVIEW_CHANGES_REQUESTED
        assert (
            W.read_story(api, desk, story["id"])["publication_status"]
            == C.PUB_DRAFT
        )
