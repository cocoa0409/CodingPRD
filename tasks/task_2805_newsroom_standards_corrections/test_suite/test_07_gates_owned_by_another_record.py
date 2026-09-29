"""Transitions a record cannot admit or refuse from its own fields alone."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import fixtures as W


class TestClearanceGatedByTheDeskPosture:
    """The round's own state is ready; the newsroom's is not."""

    def _locked_desk_with_a_round_awaiting_clearance(self, api):
        desk = W.build_desk(api, high_severity_open_threshold=1)
        locked = W.lockdown_desk(api, desk)
        story = W.open_story(
            api,
            desk,
            "A routine council vote recap",
            defamation_claim_count=0,
            privacy_subject_count=0,
            unverified_document_count=0,
        )
        review = W.standards_cleared_round(api, desk, story["id"])
        return desk, locked, story, review

    def test_the_clear_is_refused_while_the_newsroom_is_locked_down(self, api):
        """A ready round cannot close because of rows on other stories.

        PRD §3.3: "Clearing is refused outright when the newsroom's
        `standards_posture` is `LOCKDOWN` (`ERR_POSTURE_LOCKDOWN`)". PRD §3.3
        also fixes what a successful clear would have written: "On success the
        round moves `STANDARDS_CLEARED → CLEARED`, `cleared_at` is stamped from
        the logical clock, and the story advances `IN_REVIEW → CLEARED` with its
        `version` incremented by one."

        Design: Difficulty/cross_entity_state_dependency/review_clear_blocked_by_newsroom_posture_then_admitted_after_corrections_resolve
        """
        desk, _, story, review = self._locked_desk_with_a_round_awaiting_clearance(
            api
        )
        A.assert_posture(W.read_newsroom(api, desk), C.POSTURE_LOCKDOWN, 2)

        response = api.clear_review(review["id"], {}, desk.sed_headers)

        validate_error(response, E.ERR_POSTURE_LOCKDOWN, 409)

        unchanged = W.read_review(api, desk, review["id"])
        assert unchanged["status"] == C.REVIEW_STANDARDS_CLEARED
        assert unchanged["cleared_at"] is None
        assert (
            W.read_story(api, desk, story["id"])["publication_status"]
            == C.PUB_IN_REVIEW
        )

    def test_the_identical_clear_succeeds_once_the_notices_are_published(
        self, api
    ):
        """Resolving the other stories' corrections unlocks this round.

        PRD §3.6: on resolution, "because the request has left `ADJUDICATED` and
        therefore left the high-severity pool described in §2.9 — the newsroom's
        `open_high_severity_count` is re-derived and `standards_posture` may fall
        back to `OPEN`. Publishing the notice is what lets the desk breathe
        again." PRD §2.9 agrees: "Corrections leave that pool the moment their
        notice is published and the request reaches `RESOLVED`, which is
        precisely what allows the posture to relax again."

        Design: Difficulty/cross_entity_state_dependency/review_clear_blocked_by_newsroom_posture_then_admitted_after_corrections_resolve
        """
        desk, locked, story, review = (
            self._locked_desk_with_a_round_awaiting_clearance(api)
        )
        api.clear_review(review["id"], {}, desk.sed_headers)

        for request in locked["requests"]:
            W.resolve_correction(api, desk, request["id"])

        A.assert_posture(W.read_newsroom(api, desk), C.POSTURE_OPEN, 0)

        cleared = W.clear_round(api, desk, review["id"])

        assert cleared["status"] == C.REVIEW_CLEARED
        A.assert_declared_instant(cleared["cleared_at"])
        assert (
            W.read_story(api, desk, story["id"])["publication_status"]
            == C.PUB_CLEARED
        )


class TestPublicationGatedByAnUndecidedSource:
    """The story is cleared; one of its child rows is not.

    A ``GOVERNMENT`` source at ``ELEVATED`` harm risk contributes two points to
    the sourcing base and one potentially defamatory assertion contributes
    three, so the story's index is 5.00 either side of the second decision — a
    ``LOW`` harm-risk source adds nothing.
    """

    def _cleared_story_with_one_source_still_requested(self, api, desk):
        story = W.open_story(
            api,
            desk,
            "Two sources inside the permit office",
            defamation_claim_count=1,
        )
        W.approved_source(
            api,
            desk,
            story["id"],
            source_alias="permit-clerk",
            source_category=C.SOURCE_CATEGORY_GOVERNMENT,
            harm_risk=C.HARM_ELEVATED,
            identity_known_to_editor=True,
            corroboration_count=1,
            justification_text="Only person with direct access to the permit ledger.",
        )
        undecided = W.request_source(
            api,
            desk,
            story["id"],
            source_alias="front-desk",
            source_category=C.SOURCE_CATEGORY_GOVERNMENT,
            harm_risk=C.HARM_LOW,
            identity_known_to_editor=True,
            corroboration_count=1,
            justification_text="Confirms the timeline of the permit filings.",
        )
        review = W.standards_cleared_round(api, desk, story["id"])
        W.clear_round(api, desk, review["id"])
        return story, undecided

    def test_publication_is_refused_while_a_source_is_still_requested(
        self, api, desk
    ):
        """One undecided child row holds the whole story back.

        PRD §3.5: "No anonymous-source approval of the story may still be
        sitting in `REQUESTED`, and none may have been `REVOKED` — an unresolved
        source or a withdrawn one both refuse publication with
        `ERR_SOURCE_NOT_APPROVED`, while `APPROVED` and `DENIED` records are both
        fine, the first because it was cleared and the second because it will not
        appear in the copy."

        Design: Difficulty/cross_entity_state_dependency/publish_blocked_by_undecided_anonymous_source_then_admitted_after_approval
        """
        story, undecided = self._cleared_story_with_one_source_still_requested(
            api, desk
        )
        assert undecided["status"] == C.SOURCE_REQUESTED

        response = api.publish_story(story["id"], {}, desk.exec_headers)

        validate_error(response, E.ERR_SOURCE_NOT_APPROVED, 422)

        held = W.read_story(api, desk, story["id"])
        assert held["publication_status"] == C.PUB_CLEARED
        assert held["published_at"] is None

    def test_deciding_the_source_admits_the_publication_and_prices_the_base(
        self, api, desk
    ):
        """Advancing the child row, not the parent, opens the gate.

        PRD §3.2: on approval the server "increments the story's
        `approved_anonymous_source_count`, recomputes the story's
        `risk_index_estimate` and `risk_tier`". On the base PRD §3.2 rules that
        "Approvals in `REQUESTED`, `DENIED` or `REVOKED` contribute nothing to
        this base; a source at `LOW` harm risk contributes nothing either,
        however many of them there are", and PRD §3.5 mints the
        retrospective figure at publication: "Publication is also the moment
        `risk_index_actual` comes into existence, computed for the first time."

        Design: Difficulty/cross_entity_state_dependency/publish_blocked_by_undecided_anonymous_source_then_admitted_after_approval
        """
        story, undecided = self._cleared_story_with_one_source_still_requested(
            api, desk
        )
        api.publish_story(story["id"], {}, desk.exec_headers)

        decided = W.approve_source(api, desk, undecided["id"])
        assert decided["status"] == C.SOURCE_APPROVED

        waiting = W.read_story(api, desk, story["id"])
        A.assert_story_counters(waiting, approved_sources=2)
        A.assert_risk_figures(waiting, estimate=5.00, tier=C.TIER_STANDARD)

        published = W.publish_story(api, desk, story["id"])

        assert published["publication_status"] == C.PUB_PUBLISHED
        A.assert_risk_figures(
            published, estimate=5.00, actual=5.00, tier=C.TIER_STANDARD
        )
