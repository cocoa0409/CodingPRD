"""Refusals that turn on who is acting, or on what state the record is in."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as W
from test_helpers import make_legal_counsel_headers


class TestSegregationOfDutiesOnInvestigations:
    """The editor who opened a case may not be the one who decides it."""

    def test_the_opening_editor_cannot_record_the_finding_on_their_own_case(
        self, api, desk
    ):
        """403 arrives before the case has any chance to move.

        PRD §2.10: "Four decisions in this API are structurally barred to anyone
        with a stake in the outcome, and the refusal in every case is
        `ERR_SEGREGATION_OF_DUTIES` with HTTP status 403." PRD §2.10 names this
        one: "Deciding a misconduct investigation is barred both to its subject
        and to the editor who opened it: the acting `X-User-ID` must not equal the
        investigation's `journalist_id` and must not equal its
        `opened_by_user_id`." PRD §3.7 fixes what an undecided case still looks
        like: "The investigation opens in `status` `OPENED` with `penalty_points`
        0 and `disclosure_obligation` `NONE`, snapshots `prior_sustained_count`,
        and stamps `opened_by_user_id` from the acting `X-User-ID` together with
        `opened_at` from the logical clock", and cases in "`OPENED`,
        `EVIDENCE_REVIEW`, `RESPONSE_PENDING`, `UNFOUNDED` or `OVERTURNED`
        contribute zero" to the journalist's ledger.

        Design: Corner/errors/standards_editor_deciding_the_investigation_they_opened_returns_segregation_of_duties
        """
        investigation = W.open_investigation(api, desk, desk.reporter_id)
        W.advance_to_response_pending(api, desk, investigation["id"])

        response = api.decide_investigation(
            investigation["id"],
            F.disposition_payload(
                C.DISPOSITION_SUSTAINED,
                "The opener trying to decide their own case.",
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_SEGREGATION_OF_DUTIES, 403)

        undecided = W.read_investigation(api, desk, investigation["id"])
        assert undecided["status"] == C.INVESTIGATION_RESPONSE_PENDING
        assert undecided["penalty_points"] == 0
        assert undecided["decided_by_user_id"] is None

        subject = W.read_journalist(api, desk, desk.reporter_id)
        assert subject["penalty_points"] == 0
        assert subject["employment_status"] == C.EMPLOYMENT_ACTIVE


class TestAppealAdmissibility:
    """An appeal exists only against a finding that was actually made."""

    def test_an_appeal_against_a_freshly_opened_case_is_refused(self, api, desk):
        """``OPENED`` is not ``SUSTAINED``, so there is nothing to hear.

        PRD §3.7: "A sustained finding may be appealed, and only an
        `ExecutiveEditor` hears it. The appeal supplies an `appeal_outcome` of
        `UPHELD` or `OVERTURNED` and optionally an `appeal_note`. The
        investigation must be `SUSTAINED`, or the appeal is refused with
        `ERR_APPEAL_NOT_ALLOWED`". PRD §3.7 also fixes the opening record: "The
        investigation opens in `status` `OPENED` with `penalty_points` 0 and
        `disclosure_obligation` `NONE`, snapshots `prior_sustained_count`, and
        stamps `opened_by_user_id` from the acting `X-User-ID` together with
        `opened_at` from the logical clock."

        Design: Corner/errors/appealing_an_undecided_investigation_returns_appeal_not_allowed
        """
        investigation = W.open_investigation(
            api,
            desk,
            desk.reporter_id,
            allegation_summary=(
                "A passage closely tracks an unattributed source."
            ),
        )

        response = api.appeal_investigation(
            investigation["id"],
            F.appeal_payload(
                C.APPEAL_OVERTURNED, "Appealing a finding that was never made."
            ),
            desk.exec_headers,
        )

        validate_error(response, E.ERR_APPEAL_NOT_ALLOWED, 409)

        reread = W.read_investigation(api, desk, investigation["id"])
        assert reread["status"] == C.INVESTIGATION_OPENED
        assert reread["appeal_outcome"] is None
        assert reread["disclosure_obligation"] == C.OBLIGATION_NONE


class TestClearanceUnderHeightenedPosture:
    """One open serious case is enough to withdraw the editor's authority."""

    def test_a_standards_editor_may_not_clear_once_the_posture_tightens(self, api):
        """With the threshold at 1, a single open case reaches ``HEIGHTENED``.

        PRD §2.9: "When `open_high_severity_count` reaches twice the threshold or
        more, the posture is `LOCKDOWN`. Otherwise, when it reaches the threshold
        or more, the posture is `HEIGHTENED`. Below the threshold it is `OPEN`."
        The count itself includes "the number of misconduct investigations whose
        subject journalist belongs to this newsroom, whose `status` is `OPENED`,
        `EVIDENCE_REVIEW` or `RESPONSE_PENDING`, and whose `severity` is either
        `SERIOUS` or `EGREGIOUS`." PRD §2.9 then withdraws the authority: "Under
        `HEIGHTENED`, clearing a review round is reserved to an
        `ExecutiveEditor`; when a `StandardsEditor` attempts it, the refusal is
        `ERR_HEIGHTENED_REQUIRES_EXEC`." PRD §3.3 says what a refused clearance
        leaves behind: "On success the round moves `STANDARDS_CLEARED →
        CLEARED`, `cleared_at` is stamped from the logical clock, and the story
        advances `IN_REVIEW → CLEARED` with its `version` incremented by one."

        Design: Corner/errors/standards_editor_clearing_under_heightened_posture_returns_heightened_requires_exec
        """
        desk = W.build_desk(api, high_severity_open_threshold=1)
        second_reporter = W.add_reporter(api, desk)

        story = W.open_story(api, desk, "Ready to clear")
        review = W.submit_review(api, desk, story["id"], high_risk_declared=False)
        W.record_standards_pass(api, desk, review["id"])

        W.open_high_severity_investigation(api, desk, second_reporter["id"])

        response = api.clear_review(review["id"], {}, desk.sed_headers)

        validate_error(response, E.ERR_HEIGHTENED_REQUIRES_EXEC, 403)

        A.assert_posture(W.read_newsroom(api, desk), C.POSTURE_HEIGHTENED, 1)

        unmoved = W.read_review(api, desk, review["id"])
        assert unmoved["status"] == C.REVIEW_STANDARDS_CLEARED
        assert unmoved["cleared_at"] is None
        assert (
            W.read_story(api, desk, story["id"])["publication_status"]
            == C.PUB_IN_REVIEW
        )


class TestClosedRoundsRefuseFurtherVerdicts:
    """``STANDARDS_CLEARED`` is closed, whatever the verdict on offer."""

    def test_a_late_legal_read_on_a_closed_round_is_refused(
        self, api, desk, legal_reviewer
    ):
        """The legal verdict belongs to ``SUBMITTED`` and nowhere else.

        PRD §3.3: "A verdict may only be recorded while the round is at the stage
        that verdict belongs to: `SUBMITTED` for a legal verdict, and `SUBMITTED`
        or `LEGAL_CLEARED` for a standards verdict. A round that has reached
        `CLEARED`, `BLOCKED`, `CHANGES_REQUESTED` or `STANDARDS_CLEARED` is closed
        to further verdicts, and the refusal is `ERR_REVIEW_ROUND_NOT_OPEN`." PRD
        §3.3 describes what the legal pass would otherwise have written: "The
        verdict carries a `legal_verdict` of `PASS`, `CHANGES_REQUIRED` or
        `BLOCK`, together with the defamation and privacy analysis itself:
        `defamation_findings`, the count of defamation exposures the lawyer
        actually found, and `privacy_findings`, the count of privacy exposures,
        each an integer between 0 and 50 inclusive."

        The round is driven along the legal track, so its
        ``requires_legal_review`` is true and the only rule this request breaks
        is the round-open one. PRD §3.3 gives a round whose
        ``requires_legal_review`` is false its own, separate refusal —
        "Recording a legal verdict on a round whose `requires_legal_review` is
        false has no declared transition and is refused with
        `ERR_INVALID_STATE`" — and PRD §2.12 reports that generic state
        violation ahead of this one, placing step 11 above step 14.

        Design: Corner/errors/legal_verdict_on_a_standards_cleared_round_returns_review_round_not_open
        """
        story = W.open_story(api, desk, "A round already closed to the lawyers")
        review = W.submit_review(api, desk, story["id"], high_risk_declared=True)
        W.record_legal_pass(api, desk, review["id"], legal_reviewer)
        W.record_standards_pass(api, desk, review["id"])

        response = api.record_legal_verdict(
            review["id"],
            F.legal_verdict_payload(
                C.VERDICT_BLOCK,
                defamation_findings=3,
                privacy_findings=1,
                findings_note="A late legal read on a closed round.",
            ),
            make_legal_counsel_headers(legal_reviewer["id"]),
        )

        validate_error(response, E.ERR_REVIEW_ROUND_NOT_OPEN, 409)

        unmoved = W.read_review(api, desk, review["id"])
        assert unmoved["status"] == C.REVIEW_STANDARDS_CLEARED
        # The refused BLOCK wrote nothing: the earlier PASS and its zero
        # findings are still the round's legal analysis of record.
        assert unmoved["legal_verdict"] == C.VERDICT_PASS
        assert unmoved["defamation_findings"] == 0
        assert unmoved["privacy_findings"] == 0
        assert (
            W.read_story(api, desk, story["id"])["publication_status"]
            == C.PUB_IN_REVIEW
        )


class TestAdjudicationRequiresInvestigation:
    """The correction workflow has its own state error, ahead of the generic one."""

    def test_a_complaint_still_in_intake_cannot_be_decided(self, api, desk):
        """Skipping the investigation step names the correction rule, not step 11.

        PRD §3.6: "The request must be `INVESTIGATING` or `AWAITING_SUBJECT`, and
        an attempt from `INTAKE`, `ADJUDICATED`, `RESOLVED` or `DISMISSED` is
        refused with `ERR_CORRECTION_NOT_INVESTIGATED`." PRD §2.12 places it
        below the generic rule so the specific code wins: step 11 is "Generic
        state admissibility, for every action endpoint that has no more specific
        state error — `ERR_INVALID_STATE`" while step 17 is "Adjudication requires
        the correction to be `INVESTIGATING` or `AWAITING_SUBJECT` —
        `ERR_CORRECTION_NOT_INVESTIGATED`." PRD §3.6 confirms nothing has been
        written yet: the adjudication run "writes `adjudicated_severity_score` and
        `adjudicated_severity_band`, both of which are null until then", and
        `placement` "is also null for the whole time the request sits in `INTAKE`,
        `INVESTIGATING` or `AWAITING_SUBJECT`, because there is no adjudicated
        band to read it from yet."

        Design: Corner/errors/adjudicating_an_intake_request_returns_correction_not_investigated
        """
        story = W.open_story(api, desk, "A complaint nobody has opened")
        request = W.file_correction(
            api,
            desk,
            story["id"],
            submitter_type=C.SUBMITTER_READER,
            submitter_email="reader@example.test",
            claim_text="The figure in the third chart is stale.",
            claimed_error_category=C.CATEGORY_NUMERIC,
            reader_reported_reach=1200,
            subject_named=False,
        )

        response = api.adjudicate_correction_request(
            request["id"],
            F.adjudication_payload(
                C.OUTCOME_CORRECTION,
                C.CATEGORY_NUMERIC,
                1200,
                notice_text="An earlier version used a stale figure.",
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_CORRECTION_NOT_INVESTIGATED, 409)

        unmoved = W.read_correction_request(api, desk, request["id"])
        assert unmoved["status"] == C.CORRECTION_INTAKE
        assert unmoved["adjudicated_severity_score"] is None
        assert unmoved["placement"] is None
        A.assert_story_counters(
            W.read_story(api, desk, story["id"]), severe_corrections=0
        )


class TestSuspendedLeadBlocksTheReviewCycle:
    """Twelve points exactly, and the reporter's own copy stops moving."""

    def test_a_suspended_reporter_cannot_send_their_draft_into_review(
        self, api, desk
    ):
        """An egregious fabrication finding is worth 9 + 3 = 12 on the nose.

        PRD §3.7: the case's points "are then the severity's base — 2 points for
        `MINOR`, 5 for `SERIOUS`, 9 for `EGREGIOUS` — plus a 3-point surcharge
        when `allegation_type` is `FABRICATION`, plus a 2-point repeat surcharge
        when `prior_sustained_count` is 1 or more", and "A sustained `FABRICATION`
        at `EGREGIOUS` severity carries `RETRACTION_REVIEW`." PRD §3.7 then trips
        the threshold: "When the recomputation leaves a journalist's
        `penalty_points` at 12 or more, their `employment_status` moves `ACTIVE →
        SUSPENDED` and their `version` advances by one." PRD §3.3 closes the
        review door: "Submission is only available from `DRAFT`; the lead
        journalist must be `ACTIVE`, or the round is refused with
        `ERR_JOURNALIST_SUSPENDED`."

        Design: Corner/errors/submitting_a_review_for_a_suspended_lead_returns_journalist_suspended
        """
        story = W.open_story(api, desk, "Filed before the finding")
        expected_version = W.story_version(api, desk, story["id"])

        finding = W.suspend_journalist(api, desk, desk.reporter_id)
        assert finding["penalty_points"] == 12
        assert finding["disclosure_obligation"] == C.OBLIGATION_RETRACTION_REVIEW

        response = api.create_review(
            F.review_payload(
                story["id"],
                expected_version,
                high_risk_declared=False,
                submission_note="Trying to move a suspended reporter's story.",
            ),
            desk.reporter_headers,
        )

        validate_error(response, E.ERR_JOURNALIST_SUSPENDED, 409)

        suspended = W.read_journalist(api, desk, desk.reporter_id)
        assert suspended["penalty_points"] == 12
        assert suspended["employment_status"] == C.EMPLOYMENT_SUSPENDED
        assert (
            W.read_story(api, desk, story["id"])["publication_status"] == C.PUB_DRAFT
        )
        A.assert_total_count(
            api.list_story_reviews(story["id"], desk.sed_headers), 0
        )


class TestUnpublishRequiresAPublishedStory:
    """The state gate outranks the justification gate."""

    def test_a_draft_cannot_be_taken_off_a_site_it_never_reached(self, api, desk):
        """``ERR_STORY_NOT_PUBLISHED`` wins over the documented-basis rule.

        PRD §3.5: "The story must be `PUBLISHED`, or the request is refused with
        `ERR_STORY_NOT_PUBLISHED`. Beyond that, at least one of two things must be
        true: either some misconduct investigation with `status` `SUSTAINED` names
        this story, or the story's `severe_correction_count` is 1 or more. If
        neither holds, the removal is refused with
        `ERR_UNPUBLISH_NOT_JUSTIFIED`". PRD §2.12 ranks them: step 13 is
        "Unpublish requires `publication_status` `PUBLISHED` —
        `ERR_STORY_NOT_PUBLISHED`" and step 30 is "Unpublishing requires a
        documented basis — `ERR_UNPUBLISH_NOT_JUSTIFIED`." PRD §3.2 fixes the
        untouched record: the story opens "with `publication_status` `DRAFT` and
        `standards_status` `CLEAN`" and with "`risk_index_actual`, `published_at`,
        `unpublished_at` and `editors_note_text` all null."

        Design: Corner/errors/unpublishing_a_draft_story_returns_story_not_published
        """
        story = W.open_story(api, desk, "Never published at all")

        response = api.unpublish_story(
            story["id"],
            F.unpublish_payload(
                "Removing something that was never live.",
                "This story has been removed.",
            ),
            desk.exec_headers,
        )

        validate_error(response, E.ERR_STORY_NOT_PUBLISHED, 409)

        unmoved = W.read_story(api, desk, story["id"])
        A.assert_story_dimensions(unmoved, C.PUB_DRAFT, C.STD_CLEAN)
        assert unmoved["unpublished_at"] is None
