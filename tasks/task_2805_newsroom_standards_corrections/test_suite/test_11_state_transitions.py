"""Edges the declared state machines have, and edges they deliberately lack."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as W


class TestAnonymousSourceOpeningState:
    """``AnonymousSourceApproval`` at the moment it is filed."""

    def test_a_filed_request_is_undecided_and_already_documented(self, api, desk):
        """Documentation is derived at creation, not at the decision.

        PRD §3.2: "The record is created in `status` `REQUESTED`, and at that
        moment the server computes `documentation_complete`, which is true exactly
        when `identity_known_to_editor` is true **and** `justification_text` is at
        least 20 characters long, and false otherwise." PRD §3.2 also confirms
        that nothing has entered the approved pool yet: "Approvals in `REQUESTED`,
        `DENIED` or `REVOKED` contribute nothing to this base".

        Design: Corner/state_machines/anonymous_source_starts_in_requested_with_documentation_complete_derived
        """
        story = W.open_story(api, desk, "Inside the permit office")

        response = api.create_source_approval(
            F.source_approval_payload(
                story["id"],
                source_alias="permit-clerk",
                source_category=C.SOURCE_CATEGORY_GOVERNMENT,
                harm_risk=C.HARM_ELEVATED,
                identity_known_to_editor=True,
                corroboration_count=1,
                justification_text=(
                    "Only person with direct access to the permit ledger."
                ),
            ),
            desk.reporter_headers,
        )

        approval = validate_success(response, 201)

        assert approval["status"] == C.SOURCE_REQUESTED
        assert approval["documentation_complete"] is True
        assert approval["decided_by_user_id"] is None
        assert approval["decided_at"] is None

        reread = W.read_story(api, desk, story["id"])
        A.assert_story_counters(reread, approved_sources=0)
        A.assert_risk_figures(reread, estimate=0.00)

    def test_a_second_decision_on_a_decided_source_is_refused_without_double_counting(
        self, api, desk
    ):
        """The approve edge leaves ``REQUESTED``, so there is nothing to decide.

        PRD §3.2: "Deciding a record that is no longer `REQUESTED` is refused with
        `ERR_SOURCE_ALREADY_DECIDED`." PRD §3.2 also fixes what the first decision
        already did: "On success the server stores `decided_by_user_id` and
        `decided_at`, increments the story's `approved_anonymous_source_count`,
        recomputes the story's `risk_index_estimate` and `risk_tier`", where
        §3.2's base takes the story's approvals at `ELEVATED` harm risk, takes
        "the smaller of that count and 5, and multiply by 2".

        Design: Corner/state_machines/second_source_decision_returns_source_already_decided
        """
        story = W.open_story(api, desk, "One source, two decisions")
        approval = W.approved_source(
            api,
            desk,
            story["id"],
            source_alias="permit-clerk",
            harm_risk=C.HARM_ELEVATED,
            corroboration_count=1,
            justification_text=(
                "Direct access to the permit ledger over four years."
            ),
        )

        response = api.decide_source_approval(
            approval["id"],
            F.source_decision_payload(
                C.DECISION_DENY, "Second thoughts arrive too late."
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_SOURCE_ALREADY_DECIDED, 409)

        undisturbed = get_success_data(
            api.get_source_approval(approval["id"], desk.sed_headers)
        )
        assert undisturbed["status"] == C.SOURCE_APPROVED
        reread = W.read_story(api, desk, story["id"])
        A.assert_story_counters(reread, approved_sources=1)
        A.assert_risk_figures(reread, estimate=2.00)

    def test_revoking_the_only_source_of_a_published_story_reprices_and_reopens_it(
        self, api, desk
    ):
        """The revocation reaches the actual index and the standards dimension.

        PRD §3.2: "the story's `approved_anonymous_source_count` is decremented
        and its `revoked_anonymous_source_count` incremented,
        `risk_index_estimate` and `risk_tier` are recomputed because the approved
        pool shrank, `risk_index_actual` is recomputed as well when the story is
        `PUBLISHED`", and "Crucially, a published story that now carries a revoked
        source is no longer clean: if its `standards_status` was `CLEAN` or
        `CORRECTED`, it becomes `UNDER_INQUIRY`." PRD §3.5 prices the loss: to the
        documentation term "it adds seven points for every revoked anonymous
        source, counted from `revoked_anonymous_source_count`."

        Design: Corner/state_machines/source_revocation_on_published_story_sets_under_inquiry_and_reprices_actual
        """
        story = W.open_story(api, desk, "The source who later recanted")
        approval = W.approved_source(
            api,
            desk,
            story["id"],
            source_alias="permit-clerk",
            harm_risk=C.HARM_ELEVATED,
            corroboration_count=2,
            justification_text="Direct knowledge of the permit backlog.",
        )
        review = W.standards_cleared_round(api, desk, story["id"])
        W.clear_round(api, desk, review["id"])
        W.publish_story(api, desk, story["id"])

        revoked = W.revoke_source(api, desk, approval["id"])

        assert revoked["status"] == C.SOURCE_REVOKED
        assert isinstance(revoked["revocation_reason"], str)

        reread = W.read_story(api, desk, story["id"])
        A.assert_story_counters(reread, approved_sources=0, revoked_sources=1)
        A.assert_risk_figures(reread, estimate=0.00, actual=7.00)
        A.assert_story_dimensions(reread, C.PUB_PUBLISHED, C.STD_UNDER_INQUIRY)

        A.assert_total_count(
            api.list_audit_events(
                desk.newsroom_id,
                desk.exec_headers,
                {"event_type": C.EVENT_SOURCE_REVOKED},
            ),
            1,
        )


class TestConflictDisclosureTerminalStates:
    """``ConflictDisclosure`` after a review has already landed."""

    def test_a_second_review_of_an_acknowledged_disclosure_is_refused(
        self, api, desk
    ):
        """All three review outcomes are terminal, so there is no second pass.

        PRD §3.8: "Review is only available from `SUBMITTED`; a second review of
        the same disclosure is refused with `ERR_INVALID_STATE`." PRD §3.8 also
        fixes what the acknowledgement left behind: "`ACKNOWLEDGE` moves the
        disclosure `SUBMITTED → ACKNOWLEDGED` and leaves `restricted_beats`
        empty."

        Design: Corner/state_machines/disclosure_review_from_acknowledged_terminal_state_returns_invalid_state
        """
        disclosure = W.file_disclosure(
            api,
            desk,
            disclosure_type=C.DISCLOSURE_FINANCIAL,
            subject_entity_name="Northline Advisory",
            description="Small equity position inherited last year.",
        )
        W.review_disclosure(api, desk, disclosure["id"], C.REVIEW_ACKNOWLEDGE)

        response = api.review_disclosure(
            disclosure["id"],
            F.disclosure_review_payload(C.REVIEW_IMPOSE_RESTRICTION, ["energy"]),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_INVALID_STATE, 409)

        reread = W.read_disclosure(api, desk, disclosure["id"])
        assert reread["status"] == C.DISCLOSURE_ACKNOWLEDGED
        assert reread["restricted_beats"] == []
        assert (
            W.read_journalist(api, desk, desk.reporter_id)["restricted_beats"] == []
        )


class TestReviewTrackOrdering:
    """``PrePublicationReview`` on the legal track, taken out of order."""

    def test_a_standards_verdict_before_the_legal_pass_is_refused(self, api, desk):
        """With ``requires_legal_review`` true the lawyer must speak first.

        PRD §3.3: "On a round that requires legal review, the standards verdict
        may only be recorded once the round is `LEGAL_CLEARED` — the legal `PASS`
        must already be on the record — and an attempt made while the round is
        still `SUBMITTED` is refused with `ERR_LEGAL_VERDICT_REQUIRED`." PRD §3.3
        pins the track at submission: `requires_legal_review` "is true when
        `high_risk_declared` is true **or** when the story's `risk_tier` is `HIGH`
        at that moment, and false otherwise."

        Design: Corner/state_machines/standards_verdict_before_legal_verdict_returns_legal_verdict_required
        """
        story = W.open_story(
            api,
            desk,
            "Allegations the lawyers must see",
            defamation_claim_count=2,
            privacy_subject_count=1,
        )
        review = W.submit_review(api, desk, story["id"], high_risk_declared=True)
        assert review["requires_legal_review"] is True

        response = api.record_standards_verdict(
            review["id"],
            F.standards_verdict_payload(
                C.VERDICT_PASS, "Trying to skip the legal stage."
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_LEGAL_VERDICT_REQUIRED, 409)

        reread = W.read_review(api, desk, review["id"])
        assert reread["status"] == C.REVIEW_SUBMITTED
        assert reread["requires_legal_review"] is True
        assert reread["standards_verdict"] is None
        assert (
            W.read_story(api, desk, story["id"])["publication_status"]
            == C.PUB_IN_REVIEW
        )


class TestCorrectionRequestEdges:
    """``CorrectionRequest``, whose two closing branches differ in weight."""

    def test_a_no_action_outcome_dismisses_the_complaint_and_returns_the_story_to_clean(
        self, api, desk
    ):
        """The smaller branch: no notice, no severe counter, no posture move.

        PRD §3.6: "When `outcome_type` is `NO_ACTION`, the branch is strictly
        smaller. The request moves to `DISMISSED` instead of `ADJUDICATED`,
        `placement` is null and `notice_text` stays null, the story's
        `open_correction_request_count` is decremented, and the story's `version`
        advances by one. There is no notice, no increment to
        `severe_correction_count`, and no posture cascade. The story returns to
        `standards_status` `CLEAN` precisely when this dismissal was the last open
        complaint against it — that is, when `open_correction_request_count` was 1
        before the decrement and so reaches 0 — and when its
        `severe_correction_count` is 0." The complaint's own grade comes from PRD
        §3.6's first run: "the category is `claimed_error_category`, the reach is
        `reader_reported_reach`, and the subject flag is set exactly when
        `submitter_type` is `SUBJECT`."

        Design: Corner/state_machines/no_action_adjudication_dismisses_request_and_returns_story_to_clean
        """
        story = W.open_story(api, desk, "A complaint that will not stand up")
        request = W.investigating_correction(
            api,
            desk,
            story["id"],
            claim_text="The council vote tally looks wrong to me.",
            claimed_error_category=C.CATEGORY_FACTUAL,
            reader_reported_reach=500,
            subject_named=False,
        )
        A.assert_provisional_severity(request, 7, C.BAND_MINOR)

        dismissed = W.adjudicate(
            api,
            desk,
            request["id"],
            C.OUTCOME_NO_ACTION,
            C.CATEGORY_CONTEXT,
            0,
        )

        assert dismissed["status"] == C.CORRECTION_DISMISSED
        assert dismissed["placement"] is None
        assert dismissed["notice_text"] is None

        reread = W.read_story(api, desk, story["id"])
        A.assert_story_counters(reread, open_corrections=0, severe_corrections=0)
        assert reread["standards_status"] == C.STD_CLEAN
        A.assert_posture(W.read_newsroom(api, desk), C.POSTURE_OPEN, 0)

    def test_resolving_a_request_that_was_never_investigated_is_refused(
        self, api, desk
    ):
        """``INTAKE`` has no resolve edge, so nothing is stamped.

        PRD §3.6: "A `PublicEditor`, `StandardsEditor` or `ExecutiveEditor` closes
        out an `ADJUDICATED` request, optionally recording a `resolution_note`,
        which takes it `ADJUDICATED → RESOLVED`. Resolving from any other state is
        refused with `ERR_INVALID_STATE`. Both `notice_published_at` and
        `resolved_at` are stamped from the logical clock". PRD §3.6 leaves the
        story's counter where intake put it: "Intake also increments the story's
        `open_correction_request_count`".

        Design: Corner/state_machines/resolve_from_intake_returns_invalid_state
        """
        story = W.open_story(api, desk, "A fresh complaint")
        request = W.file_correction(
            api,
            desk,
            story["id"],
            claim_text="The quotation is garbled.",
            claimed_error_category=C.CATEGORY_QUOTE,
            reader_reported_reach=200,
            subject_named=False,
        )

        response = api.resolve_correction_request(
            request["id"],
            F.resolution_payload("Trying to close a request nobody investigated."),
            desk.public_editor_headers,
        )

        validate_error(response, E.ERR_INVALID_STATE, 409)

        reread = W.read_correction_request(api, desk, request["id"])
        assert reread["status"] == C.CORRECTION_INTAKE
        assert reread["notice_published_at"] is None
        assert reread["resolved_at"] is None
        A.assert_story_counters(
            W.read_story(api, desk, story["id"]), open_corrections=1
        )
