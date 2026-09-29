"""Who may act, whose record they must be, and whose work they may touch."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as W
from test_helpers import (
    headers_without_user_id,
    make_legal_counsel_headers,
    make_reporter_headers,
)


class TestEndpointRoleLists:
    """A recognised role that the endpoint simply does not admit."""

    def test_a_reporter_cannot_record_the_standards_verdict_on_their_own_round(
        self, api, desk
    ):
        """The verdict is the desk's to give, not the writer's.

        PRD §2.1: "If the headers are well formed but the declared role is not
        among the roles the target endpoint admits, the refusal is
        `ERR_UNAUTHORIZED`." PRD §4 admits only `StandardsEditor` and
        `ExecutiveEditor` on `POST
        /standards-desk/pre-publication-reviews/{id}/standards-verdict`, and PRD
        §3.3 agrees: "A `StandardsEditor` or `ExecutiveEditor` records the
        standards verdict, supplying a `standards_verdict` of `PASS`,
        `CHANGES_REQUIRED` or `BLOCK` and optionally a `findings_note`." PRD §2.12
        puts the check at step 3, "Role membership in the endpoint's authorised
        list — `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/reporter_recording_a_standards_verdict_returns_unauthorized
        """
        story = W.open_story(api, desk, "Marking my own homework")
        review = W.submit_review(api, desk, story["id"], high_risk_declared=False)

        response = api.record_standards_verdict(
            review["id"],
            F.standards_verdict_payload(C.VERDICT_PASS, "Passing my own story."),
            desk.reporter_headers,
        )

        validate_error(response, E.ERR_UNAUTHORIZED, 403)

        unmoved = W.read_review(api, desk, review["id"])
        assert unmoved["status"] == C.REVIEW_SUBMITTED
        assert unmoved["standards_verdict"] is None

    def test_the_lawyer_who_read_the_copy_cannot_publish_it(
        self, api, desk, legal_reviewer
    ):
        """Publication is the accountable editor's act alone.

        PRD §3.5: "Publication is the accountable editor's act alone. An
        `ExecutiveEditor` publishes a story with no request body, and the
        operation advances `publication_status` from `CLEARED` to `PUBLISHED`."
        PRD §2.1 supplies the refusal: "If the headers are well formed but the
        declared role is not among the roles the target endpoint admits, the
        refusal is `ERR_UNAUTHORIZED`." PRD §3.2 keeps `published_at` where it
        was, since the story opens "with `risk_index_actual`, `published_at`,
        `unpublished_at` and `editors_note_text` all null."

        Design: Corner/rbac/legal_counsel_publishing_a_story_returns_unauthorized
        """
        story = W.open_story(api, desk, "Cleared and waiting")
        review = W.standards_cleared_round(api, desk, story["id"])
        W.clear_round(api, desk, review["id"])

        response = api.publish_story(
            story["id"], {}, make_legal_counsel_headers(legal_reviewer["id"])
        )

        validate_error(response, E.ERR_UNAUTHORIZED, 403)

        unmoved = W.read_story(api, desk, story["id"])
        assert unmoved["publication_status"] == C.PUB_CLEARED
        assert unmoved["published_at"] is None

    def test_the_public_editors_remit_stops_short_of_misconduct(self, api, desk):
        """Corrections are theirs; disciplinary cases are not.

        PRD §2.1: "If the headers are well formed but the declared role is not
        among the roles the target endpoint admits, the refusal is
        `ERR_UNAUTHORIZED`." PRD §3.7 reserves the operation: allegations "are
        handled through a staged investigation that a `StandardsEditor` or
        `ExecutiveEditor` opens by naming the subject in `journalist_id`, the
        `allegation_type` — `PLAGIARISM`, `FABRICATION` or `UNDISCLOSED_COI` — a
        `severity` of `MINOR`, `SERIOUS` or `EGREGIOUS` assessed by the desk and
        fixed at opening, and an `allegation_summary` of 1 to 4000 characters."
        PRD §2.12 places that ahead of any lookup: step 3 is "Role membership in
        the endpoint's authorised list — `ERR_UNAUTHORIZED`" and step 7 is
        "Request-body identifier resolution — the 404 for the referenced type."

        Design: Corner/rbac/public_editor_opening_a_misconduct_investigation_returns_unauthorized
        """
        response = api.create_investigation(
            F.investigation_payload(
                desk.reporter_id,
                C.ALLEGATION_UNDISCLOSED_COI,
                C.SEVERITY_SERIOUS,
                "A reader alleges an undisclosed relationship.",
            ),
            desk.public_editor_headers,
        )

        validate_error(response, E.ERR_UNAUTHORIZED, 403)

        A.assert_total_count(
            api.list_investigations(
                desk.sed_headers, {"journalist_id": desk.reporter_id}
            ),
            0,
        )


class TestHeaderPresenceBeforeAnythingElse:
    """Authentication is step 1, so it answers before ownership does."""

    def test_a_story_filed_without_an_acting_identity_is_unauthenticated(
        self, api, desk
    ):
        """Declaring the role is not enough on its own.

        PRD §2.1: "Every request must carry two headers. `X-User-ID` identifies
        the acting user; `X-User-Role` declares the capacity in which they are
        acting." PRD §2.1 continues: "If either header is absent, or if
        `X-User-Role` is not one of those five strings, the request is refused
        with `ERR_UNAUTHENTICATED`." PRD §2.12 puts it first: step 1 is "Header
        presence and role recognition — `ERR_UNAUTHENTICATED`", ahead of step 4,
        "Reporter ownership on `POST /standards-desk/stories`, `POST
        /standards-desk/anonymous-source-approvals`, `POST
        /standards-desk/pre-publication-reviews`, `POST
        /standards-desk/pre-publication-reviews/{id}/resubmit`, `POST
        /standards-desk/conflict-disclosures`, `POST
        /standards-desk/outside-activity-requests` and `POST
        /standards-desk/training-records` — `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/request_without_user_id_header_returns_unauthenticated
        """
        response = api.create_story(
            F.story_payload(desk.newsroom_id, desk.reporter_id, "Filed by nobody"),
            headers_without_user_id(C.ROLE_REPORTER),
        )

        validate_error(response, E.ERR_UNAUTHENTICATED, 401)

        A.assert_total_count(
            api.list_stories(desk.exec_headers, {"newsroom_id": desk.newsroom_id}),
            0,
        )


class TestEntityBackedIdentityBinding:
    """The acting id must resolve, and the record it names must fit the role."""

    def test_the_standards_editors_own_id_will_not_pass_as_a_reporter(
        self, api, desk
    ):
        """A real journalist row is not automatically the right journalist row.

        PRD §2.1: "Four of the five roles are **entity-backed**, meaning
        `X-User-ID` must resolve to a real persisted record whose own attributes
        agree with the declared role", and specifically: "When `X-User-Role` is
        `Reporter`, `X-User-ID` is the `id` of the acting `Journalist`, and that
        journalist's `role_title` must be `REPORTER`." PRD §2.1 fixes the refusal:
        "A mismatch between `X-User-ID` and the backing record's type or title,
        and any case where `X-User-ID` does not resolve at all, is
        `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/reporter_role_bound_to_a_standards_editor_record_returns_unauthorized
        """
        response = api.create_story(
            F.story_payload(
                desk.newsroom_id, desk.sed_id, "An editor pretending to report"
            ),
            make_reporter_headers(desk.sed_id),
        )

        validate_error(response, E.ERR_UNAUTHORIZED, 403)

        A.assert_total_count(
            api.list_stories(desk.exec_headers, {"newsroom_id": desk.newsroom_id}),
            0,
        )

    def test_a_colleague_with_the_same_role_still_cannot_submit_the_story(
        self, api, desk
    ):
        """Ownership is checked per journalist, not per masthead title.

        PRD §2.1: "Separately from role membership, a `Reporter` may only write
        resources that belong to them. Story creation must name the acting
        reporter in `lead_journalist_id`; a review submission or resubmission must
        come from the story's own lead journalist; an anonymous-source request
        must be filed by the lead journalist of the story it concerns; and a
        conflict disclosure, outside-activity request or training record must name
        the acting journalist in `journalist_id`. A reporter reaching for another
        journalist's resource receives `ERR_UNAUTHORIZED`." PRD §3.3 confirms whose
        act it is: "The story's own lead journalist starts a round, which advances
        `publication_status` from `DRAFT` to `IN_REVIEW` and creates a review
        record in `status` `SUBMITTED` at `review_round` 1."

        Design: Corner/rbac/reporter_submitting_another_reporters_story_returns_unauthorized
        """
        story = W.open_story(api, desk, "Somebody else's byline")
        expected_version = W.story_version(api, desk, story["id"])
        colleague = W.add_reporter(api, desk)

        response = api.create_review(
            F.review_payload(
                story["id"],
                expected_version,
                high_risk_declared=False,
                submission_note="Submitting a colleague's story.",
            ),
            make_reporter_headers(colleague["id"]),
        )

        validate_error(response, E.ERR_UNAUTHORIZED, 403)

        assert (
            W.read_story(api, desk, story["id"])["publication_status"] == C.PUB_DRAFT
        )
        A.assert_total_count(
            api.list_story_reviews(story["id"], desk.sed_headers), 0
        )


class TestOpaquePublicEditorIdentity:
    """The one role whose acting id is never matched against a record."""

    def test_an_operator_id_matching_no_journalist_may_take_in_and_open_a_complaint(
        self, api, desk, alternate_public_editor_headers
    ):
        """Two consecutive writes from an identity the desk cannot resolve.

        PRD §2.1: "`PublicEditor` is the exception. When `X-User-Role` is
        `PublicEditor`, `X-User-ID` is an opaque operator identifier for the
        reader-advocate desk and is not tied to any persisted entity." PRD §3.6
        gives the role both operations: complaints are logged when "A
        `PublicEditor` or `StandardsEditor` opens a correction request against a
        story", and then "A `PublicEditor` or `StandardsEditor` opens the
        investigation, taking the request `INTAKE → INVESTIGATING` and optionally
        recording an `assigned_note`; the request's `version` advances by one."
        PRD §3.6 grades the complaint from its own account: "Start from the error
        category's weight: `IDENTIFICATION` is worth 8 points, `FACTUAL` 6, `QUOTE`
        5, `NUMERIC` 4 and `CONTEXT` 3. Add 4 points when the subject flag is set
        and nothing when it is not. Add a reach component: 6 points when the reach
        is 100,000 or more, otherwise 4 points when it is 10,000 or more,
        otherwise 2 points when it is 1,000 or more, otherwise nothing." PRD §3.6
        then bands and scores it: "The band is then read off the raw figure and
        off nothing else: `SEVERE` when raw is 16 or more, `MAJOR` when raw is 11
        or more but below 16, `MINOR` when raw is 6 or more but below 11, and
        `TRIVIAL` below 6. Only then is the stored score produced, by adding a
        placement surcharge determined by that band — nothing for `TRIVIAL`, 1
        point for `MINOR`, 2 points for `MAJOR`, 3 points for `SEVERE`." PRD §3.6
        also moves the story: "Intake is admissible while the story's
        `standards_status` is `CLEAN` or `CORRECTED`, and in both cases it drives
        that dimension to `UNDER_INQUIRY`."

        Design: Corner/rbac/public_editor_opaque_identity_may_take_in_and_open_a_correction
        """
        story = W.open_story(api, desk, "A complaint arrives")

        filed = validate_success(
            api.create_correction_request(
                F.correction_request_payload(
                    story["id"],
                    submitter_type=C.SUBMITTER_READER,
                    submitter_email="reader@example.test",
                    claim_text="The council vote count is off by one.",
                    claimed_error_category=C.CATEGORY_NUMERIC,
                    reader_reported_reach=1500,
                    subject_named=False,
                ),
                alternate_public_editor_headers,
            ),
            201,
        )

        opened = validate_success(
            api.start_correction_investigation(
                filed["id"],
                F.start_investigation_payload("Pulling the clerk's tally."),
                alternate_public_editor_headers,
            )
        )

        assert opened["status"] == C.CORRECTION_INVESTIGATING
        A.assert_provisional_severity(opened, 7, C.BAND_MINOR)

        reread = W.read_story(api, desk, story["id"])
        A.assert_story_counters(reread, open_corrections=1)
        assert reread["standards_status"] == C.STD_UNDER_INQUIRY
