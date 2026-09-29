"""Well-formed identifiers that name nothing, in the path and in the body."""

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as W

from prd_bench_local_runner.testing import validate_error


class TestUnknownReferencesInWritePayloads:
    """Body identifiers are foreign keys, checked before the body's shape."""

    def test_an_allegation_against_nobody_names_the_journalist_that_is_missing(
        self, api, desk
    ):
        """The subject of an investigation must exist before the case can open.

        PRD §2.6: "Identifiers supplied inside a request body are held to the
        same standard. Every `newsroom_id`, `lead_journalist_id`,
        `journalist_id`, `story_id`, `review_id` and `reviewer_id` in a write
        payload must resolve to an existing record, and a dangling reference
        produces the 404 belonging to the referenced type rather than a generic
        validation failure." PRD §3.7 names the field: an investigation is opened
        "by naming the subject in `journalist_id`, the `allegation_type` —
        `PLAGIARISM`, `FABRICATION` or `UNDISCLOSED_COI` — a `severity` of
        `MINOR`, `SERIOUS` or `EGREGIOUS` assessed by the desk and fixed at
        opening, and an `allegation_summary` of 1 to 4000 characters."

        Design: Corner/errors/opening_investigation_into_unknown_journalist_returns_journalist_not_found
        """
        response = api.create_investigation(
            F.investigation_payload(
                C.UNKNOWN_JOURNALIST_ID,
                C.ALLEGATION_PLAGIARISM,
                C.SEVERITY_SERIOUS,
                "An allegation against nobody in particular.",
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_JOURNALIST_NOT_FOUND, 404)

        A.assert_total_count(
            api.list_investigations(
                desk.sed_headers, {"status": C.INVESTIGATION_OPENED}
            ),
            0,
        )

    def test_a_booking_for_a_reviewer_who_does_not_exist_never_reaches_the_version_token(
        self, api, desk
    ):
        """A dangling ``reviewer_id`` answers 404, not a stale-view refusal.

        PRD §2.6: "Every `newsroom_id`, `lead_journalist_id`, `journalist_id`,
        `story_id`, `review_id` and `reviewer_id` in a write payload must resolve
        to an existing record, and a dangling reference produces the 404
        belonging to the referenced type rather than a generic validation
        failure", and "Reviewer lookups that fail yield
        `ERR_REVIEWER_NOT_FOUND`." PRD §2.12 fixes the order in which the two
        complaints are heard: step 7 is "Request-body identifier resolution — the
        404 for the referenced type" while step 10 is "Stale-view checks on `POST
        /standards-desk/pre-publication-reviews` and `POST
        /standards-desk/review-assignments` — `ERR_STALE_STORY_VERSION` or
        `ERR_STALE_REVIEWER_VERSION`." PRD §3.1 leaves the real reviewer's ledger
        alone: "On registration the reviewer's `reserved_minutes` is 0 and
        `available_minutes` equals `weekly_capacity_minutes`."

        Design: Corner/errors/booking_unknown_reviewer_returns_reviewer_not_found
        """
        reviewer = W.add_reviewer(
            api, desk, full_name="Lee Park", weekly_capacity_minutes=480
        )
        story = W.open_story(api, desk, "A round the desk will read itself")
        review = W.submit_review(api, desk, story["id"], high_risk_declared=False)

        response = api.create_assignment(
            F.assignment_payload(
                review["id"],
                C.UNKNOWN_REVIEWER_ID,
                "2026-08-04T09:00:00Z",
                "2026-08-04T10:00:00Z",
                reviewer["version"],
            ),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_REVIEWER_NOT_FOUND, 404)

        A.assert_minute_ledger(W.read_reviewer(api, desk, reviewer["id"]), 0, 480)
        A.assert_total_count(
            api.list_assignments(desk.sed_headers, {"review_id": review["id"]}), 0
        )


class TestUnknownRecordsAddressedDirectly:
    """Each record type answers with the 404 that belongs to it."""

    def test_an_unknown_review_round_answers_with_the_review_not_found_code(
        self, api, desk
    ):
        """Not a generic 404, and not an empty success body.

        PRD §2.6: "Addressing a single record by its own identifier produces the
        error for that record type: `ERR_SOURCE_APPROVAL_NOT_FOUND` for an
        anonymous-source approval, `ERR_REVIEW_NOT_FOUND` for a pre-publication
        review, `ERR_ASSIGNMENT_NOT_FOUND` for a review assignment,
        `ERR_CORRECTION_REQUEST_NOT_FOUND` for a correction request,
        `ERR_INVESTIGATION_NOT_FOUND` for a misconduct investigation,
        `ERR_DISCLOSURE_NOT_FOUND` for a conflict disclosure and
        `ERR_ACTIVITY_REQUEST_NOT_FOUND` for an outside-activity request."

        Design: Corner/errors/reading_unknown_review_returns_review_not_found
        """
        response = api.get_review(C.UNKNOWN_REVIEW_ID, desk.sed_headers)

        body = validate_error(response, E.ERR_REVIEW_NOT_FOUND, 404)
        assert isinstance(body["message"], str) and body["message"].strip()

    def test_an_unknown_source_approval_answers_with_the_source_approval_code(
        self, api, desk
    ):
        """The approval record has a 404 of its own.

        PRD §2.6: "Addressing a single record by its own identifier produces the
        error for that record type: `ERR_SOURCE_APPROVAL_NOT_FOUND` for an
        anonymous-source approval, `ERR_REVIEW_NOT_FOUND` for a pre-publication
        review, `ERR_ASSIGNMENT_NOT_FOUND` for a review assignment,
        `ERR_CORRECTION_REQUEST_NOT_FOUND` for a correction request,
        `ERR_INVESTIGATION_NOT_FOUND` for a misconduct investigation,
        `ERR_DISCLOSURE_NOT_FOUND` for a conflict disclosure and
        `ERR_ACTIVITY_REQUEST_NOT_FOUND` for an outside-activity request."

        Design: Corner/errors/reading_unknown_source_approval_returns_source_approval_not_found
        """
        response = api.get_source_approval(
            C.UNKNOWN_SOURCE_APPROVAL_ID, desk.sed_headers
        )

        validate_error(response, E.ERR_SOURCE_APPROVAL_NOT_FOUND, 404)

    def test_cancelling_a_booking_that_does_not_exist_is_a_lookup_failure(
        self, api, desk
    ):
        """Resolution comes before any state complaint about the booking.

        PRD §2.6: "Addressing a single record by its own identifier produces the
        error for that record type: `ERR_SOURCE_APPROVAL_NOT_FOUND` for an
        anonymous-source approval, `ERR_REVIEW_NOT_FOUND` for a pre-publication
        review, `ERR_ASSIGNMENT_NOT_FOUND` for a review assignment,
        `ERR_CORRECTION_REQUEST_NOT_FOUND` for a correction request,
        `ERR_INVESTIGATION_NOT_FOUND` for a misconduct investigation,
        `ERR_DISCLOSURE_NOT_FOUND` for a conflict disclosure and
        `ERR_ACTIVITY_REQUEST_NOT_FOUND` for an outside-activity request." PRD
        §2.12 puts that check first: step 6 is "Path identifier resolution, left
        to right — the 404 for the first unresolved segment", ahead of step 11,
        "Generic state admissibility, for every action endpoint that has no more
        specific state error — `ERR_INVALID_STATE`."

        Design: Corner/errors/cancelling_unknown_assignment_returns_assignment_not_found
        """
        response = api.cancel_assignment(
            C.UNKNOWN_ASSIGNMENT_ID,
            F.cancellation_payload("Cancelling a slot nobody ever booked."),
            desk.sed_headers,
        )

        validate_error(response, E.ERR_ASSIGNMENT_NOT_FOUND, 404)

    def test_an_unknown_investigation_answers_with_the_investigation_code(
        self, api, desk
    ):
        """A case the desk never opened cannot be read.

        PRD §2.6: "Addressing a single record by its own identifier produces the
        error for that record type: `ERR_SOURCE_APPROVAL_NOT_FOUND` for an
        anonymous-source approval, `ERR_REVIEW_NOT_FOUND` for a pre-publication
        review, `ERR_ASSIGNMENT_NOT_FOUND` for a review assignment,
        `ERR_CORRECTION_REQUEST_NOT_FOUND` for a correction request,
        `ERR_INVESTIGATION_NOT_FOUND` for a misconduct investigation,
        `ERR_DISCLOSURE_NOT_FOUND` for a conflict disclosure and
        `ERR_ACTIVITY_REQUEST_NOT_FOUND` for an outside-activity request." PRD
        §3.7 confirms there is a listing behind it: "Investigations can be read
        individually, with their points and disclosure obligation, or listed with
        filters on `journalist_id`, `story_id`, `status` and `allegation_type`."

        Design: Corner/errors/reading_unknown_investigation_returns_investigation_not_found
        """
        response = api.get_investigation(
            C.UNKNOWN_INVESTIGATION_ID, desk.sed_headers
        )

        validate_error(response, E.ERR_INVESTIGATION_NOT_FOUND, 404)

        A.assert_total_count(api.list_investigations(desk.sed_headers), 0)


class TestUnknownRecordsOnAnEmptyDesk:
    """The public editor's identity is opaque, so these need no desk at all."""

    def test_an_unknown_correction_request_answers_before_any_desk_exists(
        self, api, public_editor_headers
    ):
        """Nothing has been registered, and the lookup still names its type.

        PRD §2.6: "Addressing a single record by its own identifier produces the
        error for that record type: `ERR_SOURCE_APPROVAL_NOT_FOUND` for an
        anonymous-source approval, `ERR_REVIEW_NOT_FOUND` for a pre-publication
        review, `ERR_ASSIGNMENT_NOT_FOUND` for a review assignment,
        `ERR_CORRECTION_REQUEST_NOT_FOUND` for a correction request,
        `ERR_INVESTIGATION_NOT_FOUND` for a misconduct investigation,
        `ERR_DISCLOSURE_NOT_FOUND` for a conflict disclosure and
        `ERR_ACTIVITY_REQUEST_NOT_FOUND` for an outside-activity request." PRD
        §2.1 explains why no record is needed to ask: "When `X-User-Role` is
        `PublicEditor`, `X-User-ID` is an opaque operator identifier for the
        reader-advocate desk and is not tied to any persisted entity."

        Design: Corner/errors/reading_unknown_correction_request_returns_correction_request_not_found
        """
        response = api.get_correction_request(
            C.UNKNOWN_CORRECTION_REQUEST_ID, public_editor_headers
        )

        validate_error(response, E.ERR_CORRECTION_REQUEST_NOT_FOUND, 404)

    def test_an_unknown_disclosure_answers_before_any_desk_exists(
        self, api, public_editor_headers
    ):
        """The disclosure code, not the journalist code, on an empty desk.

        PRD §2.6: "Addressing a single record by its own identifier produces the
        error for that record type: `ERR_SOURCE_APPROVAL_NOT_FOUND` for an
        anonymous-source approval, `ERR_REVIEW_NOT_FOUND` for a pre-publication
        review, `ERR_ASSIGNMENT_NOT_FOUND` for a review assignment,
        `ERR_CORRECTION_REQUEST_NOT_FOUND` for a correction request,
        `ERR_INVESTIGATION_NOT_FOUND` for a misconduct investigation,
        `ERR_DISCLOSURE_NOT_FOUND` for a conflict disclosure and
        `ERR_ACTIVITY_REQUEST_NOT_FOUND` for an outside-activity request." PRD
        §2.1 explains why no record is needed to ask: "When `X-User-Role` is
        `PublicEditor`, `X-User-ID` is an opaque operator identifier for the
        reader-advocate desk and is not tied to any persisted entity."

        Design: Corner/errors/reading_unknown_disclosure_returns_disclosure_not_found
        """
        response = api.get_disclosure(
            C.UNKNOWN_DISCLOSURE_ID, public_editor_headers
        )

        validate_error(response, E.ERR_DISCLOSURE_NOT_FOUND, 404)

    def test_an_unknown_activity_request_answers_before_any_desk_exists(
        self, api, public_editor_headers
    ):
        """The outside-activity code has its own slot in the same list.

        PRD §2.6: "Addressing a single record by its own identifier produces the
        error for that record type: `ERR_SOURCE_APPROVAL_NOT_FOUND` for an
        anonymous-source approval, `ERR_REVIEW_NOT_FOUND` for a pre-publication
        review, `ERR_ASSIGNMENT_NOT_FOUND` for a review assignment,
        `ERR_CORRECTION_REQUEST_NOT_FOUND` for a correction request,
        `ERR_INVESTIGATION_NOT_FOUND` for a misconduct investigation,
        `ERR_DISCLOSURE_NOT_FOUND` for a conflict disclosure and
        `ERR_ACTIVITY_REQUEST_NOT_FOUND` for an outside-activity request." PRD
        §2.1 explains why no record is needed to ask: "When `X-User-Role` is
        `PublicEditor`, `X-User-ID` is an opaque operator identifier for the
        reader-advocate desk and is not tied to any persisted entity."

        Design: Corner/errors/reading_unknown_activity_request_returns_activity_request_not_found
        """
        response = api.get_activity_request(
            C.UNKNOWN_ACTIVITY_REQUEST_ID, public_editor_headers
        )

        validate_error(response, E.ERR_ACTIVITY_REQUEST_NOT_FOUND, 404)
