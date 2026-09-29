"""The records the desk is built out of, and how they read back."""

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
from test_helpers import make_executive_editor_headers


class TestNewsroomRegistration:
    """``POST /standards-desk/newsrooms``, the desk's first record."""

    def test_every_declared_dial_is_echoed_with_the_derived_figures_at_zero(
        self, api, bootstrap_exec_headers
    ):
        """A fully specified newsroom returns its policy and an idle posture.

        PRD §3.1: "`correction_response_sla_hours` is the base window, in hours,
        that the desk gives itself to answer a complaint" and
        "`required_module_codes` is the array of standards training modules every
        journalist of the newsroom owes". PRD §3.1 then fixes the opening state:
        "A newly registered newsroom opens with `standards_posture` `OPEN`,
        `open_high_severity_count` 0 and `training_compliance_index` 0.00." PRD
        §2.4 adds that "`version` is an integer that starts at 1 on creation".

        Design: Corner/entities/newsroom_creation_returns_all_declared_fields_with_derived_zeroes
        """
        response = api.create_newsroom(
            F.newsroom_payload(
                name="Harbor Dispatch",
                correction_response_sla_hours=48,
                high_severity_open_threshold=3,
                required_module_codes=[C.MODULE_SOURCING, C.MODULE_CORRECTIONS],
            ),
            bootstrap_exec_headers,
        )

        newsroom = validate_success(response, 201)

        assert newsroom["name"] == "Harbor Dispatch"
        assert newsroom["correction_response_sla_hours"] == 48
        assert newsroom["high_severity_open_threshold"] == 3
        assert newsroom["required_module_codes"] == [
            C.MODULE_SOURCING,
            C.MODULE_CORRECTIONS,
        ]
        A.assert_posture(newsroom, C.POSTURE_OPEN, 0)
        A.assert_decimal_equals(newsroom["training_compliance_index"], 0.00)
        A.assert_versioned_resource(newsroom, version=1)

    def test_omitting_the_optional_dials_applies_the_declared_defaults(
        self, api, bootstrap_exec_headers
    ):
        """Name alone is enough, and the three defaults fill themselves in.

        PRD §3.1: `correction_response_sla_hours` "defaults to 72 and must fall
        between 1 and 336 inclusive", `high_severity_open_threshold` is "the
        number of concurrently open high-severity matters at which the desk
        tightens up, defaulting to 2 and constrained to between 1 and 20
        inclusive", and `required_module_codes` "defaults to a single-element
        array containing `SOURCING`".

        Design: Corner/entities/newsroom_defaults_applied_when_optional_configuration_omitted
        """
        response = api.create_newsroom(
            F.newsroom_payload(name="Riverside Beacon"), bootstrap_exec_headers
        )

        newsroom = validate_success(response, 201)

        assert newsroom["correction_response_sla_hours"] == C.SLA_HOURS_DEFAULT
        assert (
            newsroom["high_severity_open_threshold"]
            == C.HIGH_SEVERITY_OPEN_THRESHOLD_DEFAULT
        )
        assert newsroom["required_module_codes"] == C.REQUIRED_MODULE_CODES_DEFAULT
        assert newsroom["standards_posture"] == C.POSTURE_OPEN


class TestStoryRecord:
    """``Story``, the record every other workflow hangs off."""

    def test_a_retrieved_story_carries_its_declared_counts_and_its_risk_figures(
        self, api, desk
    ):
        """One defamatory assertion, two private subjects and a document: 12.00.

        PRD §3.2: the estimate's declared-exposure terms are "three points for
        every potentially defamatory assertion counted in
        `defamation_claim_count` plus two points for every identifiable private
        individual counted in `privacy_subject_count`" and "a flat five-point
        documentation penalty applied when `unverified_document_count` is greater
        than zero". PRD §3.2 bands from the estimate alone: `risk_tier` "is
        `HIGH` when `risk_index_estimate` is 40.00 or greater, `ELEVATED` when it
        is 20.00 or greater but below 40.00, and `STANDARD` otherwise", and
        `risk_index_actual` "stays null until the story is published".

        Design: Corner/entities/story_retrieval_returns_stored_and_derived_fields
        """
        story = W.open_story(
            api,
            desk,
            "Three unverified permits",
            defamation_claim_count=1,
            privacy_subject_count=2,
            unverified_document_count=1,
        )

        reread = get_success_data(
            api.get_story(story["id"], desk.reporter_headers)
        )

        assert reread["id"] == story["id"]
        assert reread["headline"] == "Three unverified permits"
        assert reread["defamation_claim_count"] == 1
        assert reread["privacy_subject_count"] == 2
        assert reread["unverified_document_count"] == 1
        A.assert_risk_figures(reread, estimate=12.00, tier=C.TIER_STANDARD)
        assert reread["risk_index_actual"] is None
        A.assert_story_dimensions(reread, C.PUB_DRAFT, C.STD_CLEAN)

    def test_the_lifecycle_fields_are_server_assigned_and_take_no_client_value(
        self, api, desk
    ):
        """Creation always yields the same opening state, whatever is sent.

        PRD §3.2: "The story opens with `publication_status` `DRAFT` and
        `standards_status` `CLEAN`, with all four of its derived counters —
        `approved_anonymous_source_count`, `revoked_anonymous_source_count`,
        `severe_correction_count` and `open_correction_request_count` — at 0,
        with `risk_index_estimate` at 0.00, `risk_tier` at `STANDARD`, and with
        `risk_index_actual`, `published_at`, `unpublished_at` and
        `editors_note_text` all null." PRD §2.4 adds that every resource "carries
        a `created_at` timestamp, formatted as an ISO 8601 UTC instant with
        exactly three fractional-second digits".

        Design: Corner/entities/story_system_fields_are_server_assigned_and_ignore_client_values
        """
        response = api.create_story(
            F.story_payload(
                desk.newsroom_id, desk.reporter_id, "A brand new draft"
            ),
            desk.reporter_headers,
        )

        story = validate_success(response, 201)

        A.assert_story_dimensions(story, C.PUB_DRAFT, C.STD_CLEAN)
        assert story["published_at"] is None
        assert story["unpublished_at"] is None
        assert story["editors_note_text"] is None
        A.assert_versioned_resource(story, version=1)

    def test_a_story_named_against_an_unknown_newsroom_is_refused_as_a_dangling_reference(
        self, api, desk
    ):
        """The body's ``newsroom_id`` is a validated foreign key.

        PRD §2.6: "Identifiers supplied inside a request body are held to the
        same standard. Every `newsroom_id`, `lead_journalist_id`,
        `journalist_id`, `story_id`, `review_id` and `reviewer_id` in a write
        payload must resolve to an existing record, and a dangling reference
        produces the 404 belonging to the referenced type rather than a generic
        validation failure."

        Design: Corner/entities/story_with_unknown_newsroom_id_returns_newsroom_not_found
        """
        response = api.create_story(
            F.story_payload(
                C.UNKNOWN_NEWSROOM_ID,
                desk.reporter_id,
                "Story against a phantom newsroom",
            ),
            desk.reporter_headers,
        )

        validate_error(response, E.ERR_NEWSROOM_NOT_FOUND, 404)

        A.assert_total_count(
            api.list_stories(
                desk.reporter_headers, {"newsroom_id": desk.newsroom_id}
            ),
            0,
        )

    def test_reading_a_story_that_was_never_created_is_a_refusal_not_an_empty_body(
        self, api
    ):
        """A well-formed but unknown identifier answers 404.

        PRD §2.6: "Identifiers in a URL path are resolved strictly left to right,
        and the first one that fails to resolve determines the error", and "the
        same discipline applies beneath a journalist
        (`ERR_JOURNALIST_NOT_FOUND`) and beneath a story
        (`ERR_STORY_NOT_FOUND`)."

        Design: Corner/entities/story_get_with_unknown_id_returns_story_not_found
        """
        newsroom = W.bootstrap_newsroom(api)
        exec_editor = W.bootstrap_executive_editor(api, newsroom["id"])

        response = api.get_story(
            C.UNKNOWN_STORY_ID,
            make_executive_editor_headers(exec_editor["id"]),
        )

        body = validate_error(response, E.ERR_STORY_NOT_FOUND, 404)
        assert isinstance(body["message"], str) and body["message"].strip()
        assert response.json()["response_type"] == "error"
        A.assert_total_count(
            api.list_stories(
                make_executive_editor_headers(exec_editor["id"]),
                {"newsroom_id": newsroom["id"]},
            ),
            0,
        )


class TestJournalistListing:
    """``GET /standards-desk/newsrooms/{id}/journalists`` and its paging."""

    def test_the_window_reports_the_full_filtered_size_and_whether_more_remain(
        self, api, desk
    ):
        """Three journalists, read two at a time, then narrowed by title.

        PRD §2.3: "The `limit` parameter caps the number of records returned; it
        defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100.
        The `offset` parameter is the number of records to skip and defaults to
        0." PRD §2.3 also states that "List responses populate `limit`, `offset`,
        `total_count` and `has_more` in the `meta` object of the envelope, where
        `total_count` is the size of the full filtered set before paging and
        `has_more` indicates whether records remain beyond the current window."
        PRD §3.1 supplies the filter: "A journalist listing for a newsroom may be
        narrowed by `role_title` or by `employment_status`".

        Design: Corner/entities/journalist_listing_paginates_with_total_count_and_has_more
        """
        first_page = A.assert_page(
            api.list_journalists(
                desk.newsroom_id, desk.exec_headers, {"limit": 2, "offset": 0}
            ),
            total_count=3,
            has_more=True,
            row_count=2,
        )
        A.assert_created_at_ascending(first_page)

        A.assert_page(
            api.list_journalists(
                desk.newsroom_id, desk.exec_headers, {"limit": 2, "offset": 2}
            ),
            total_count=3,
            has_more=False,
            row_count=1,
        )

        reporters = A.assert_page(
            api.list_journalists(
                desk.newsroom_id,
                desk.exec_headers,
                {"role_title": C.TITLE_REPORTER},
            ),
            total_count=1,
            has_more=False,
            row_count=1,
        )
        assert reporters[0]["id"] == desk.reporter_id


class TestReviewerRegistration:
    """``Reviewer``, whose minute ledger is derived and never accepted."""

    def test_the_ledger_opens_from_capacity_alone(self, api, desk):
        """Four hours of capacity means four hours available and none committed.

        PRD §3.1: "Registering one takes the `newsroom_id` they serve, a
        `full_name` of 1 to 120 characters, a `discipline` of either `LEGAL` or
        `STANDARDS`, and a `weekly_capacity_minutes` figure that defaults to 600
        and must be at least 60 and at most 4800." PRD §3.1 then derives the
        ledger: "On registration the reviewer's `reserved_minutes` is 0 and
        `available_minutes` equals `weekly_capacity_minutes`."

        Design: Corner/entities/reviewer_available_minutes_computed_at_registration
        """
        response = api.create_reviewer(
            F.reviewer_payload(
                desk.newsroom_id,
                "Kai Brandt",
                C.DISCIPLINE_STANDARDS,
                weekly_capacity_minutes=240,
            ),
            desk.exec_headers,
        )

        reviewer = validate_success(response, 201)

        assert reviewer["weekly_capacity_minutes"] == 240
        assert reviewer["discipline"] == C.DISCIPLINE_STANDARDS
        A.assert_minute_ledger(reviewer, 0, 240)
        A.assert_minutes_conserved(reviewer)

    def test_a_capacity_under_the_floor_and_an_unrecognised_discipline_are_both_refused(
        self, api, desk
    ):
        """Thirty minutes is below the declared minimum, and no row is written.

        PRD §3.1: `weekly_capacity_minutes` "must be at least 60 and at most
        4800", and the `discipline` is "either `LEGAL` or `STANDARDS`". PRD §2.12
        step 8 covers both: "Body shape: required fields present, enum members
        recognised, integers inside their declared ranges, strings inside their
        declared lengths, arrays non-empty where required, and unknown fields
        rejected outright — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/reviewer_capacity_below_declared_minimum_returns_invalid_request
        """
        below_floor = api.create_reviewer(
            F.reviewer_payload(
                desk.newsroom_id,
                "Kai Brandt",
                C.DISCIPLINE_LEGAL,
                weekly_capacity_minutes=30,
            ),
            desk.exec_headers,
        )
        validate_error(below_floor, E.ERR_INVALID_REQUEST, 400)

        unknown_discipline = api.create_reviewer(
            F.reviewer_payload(
                desk.newsroom_id,
                "Kai Brandt",
                "EDITORIAL",
                weekly_capacity_minutes=240,
            ),
            desk.exec_headers,
        )
        validate_error(unknown_discipline, E.ERR_INVALID_REQUEST, 400)

        A.assert_total_count(
            api.list_reviewers(desk.newsroom_id, desk.exec_headers), 0
        )


class TestCorrectionRequestRequiredFields:
    """Correction intake, and what happens when the complaint is missing."""

    def test_intake_without_the_complaint_itself_is_refused_and_persists_nothing(
        self, api, desk
    ):
        """No ``claim_text`` means no record, and the story's counter stays at 0.

        PRD §3.6: a correction request is opened "by naming the `story_id`, a
        `submitter_type` of `READER`, `SUBJECT` or `INTERNAL`, a
        `submitter_email` containing an `@` character as the reply-to address for
        the response obligation, the complaint itself as `claim_text` of 1 to
        4000 characters". PRD §3.6 also notes what a successful intake would have
        moved: "Intake also increments the story's
        `open_correction_request_count` and advances the story's `version` by
        one."

        Design: Corner/entities/correction_request_without_claim_text_returns_invalid_request
        """
        story = W.open_story(api, desk, "A story readers will dispute")

        response = api.create_correction_request(
            {
                "story_id": story["id"],
                "submitter_type": C.SUBMITTER_READER,
                "submitter_email": "reader@example.test",
                "claimed_error_category": C.CATEGORY_FACTUAL,
                "reader_reported_reach": 500,
                "subject_named": False,
            },
            desk.public_editor_headers,
        )

        validate_error(response, E.ERR_INVALID_REQUEST, 400)

        untouched = W.read_story(api, desk, story["id"])
        A.assert_story_counters(untouched, open_corrections=0)
        A.assert_story_dimensions(untouched, C.PUB_DRAFT, C.STD_CLEAN)


class TestTrainingRecordImmutability:
    """``TrainingRecord``, an append-only historical fact."""

    def test_a_filed_module_carries_no_version_and_no_updated_at(self, api, desk):
        """The record is narrower than a mutable resource, by design.

        PRD §2.4: "A `TrainingRecord` and a `StandardsAuditEvent` carry only `id`
        and `created_at`: both `updated_at` and `version` are absent from their
        representations, because neither record is ever modified after it is
        written." PRD §3.8 stamps the filing itself: "The server stamps
        `completed_at` from the logical clock; the record is append-only and is
        never updated afterwards." PRD §2.5 fixes that instant: "Before any
        caller sets it, the logical clock reads exactly
        `2026-08-01T00:00:00Z`".

        Design: Corner/entities/training_record_is_immutable_with_no_version_field
        """
        response = api.create_training_record(
            F.training_record_payload(
                desk.reporter_id, C.MODULE_CORRECTIONS, "CS-2026-014"
            ),
            desk.reporter_headers,
        )

        record = validate_success(response, 201)

        assert record["module_code"] == C.MODULE_CORRECTIONS
        assert record["case_study_reference"] == "CS-2026-014"
        A.assert_instant_equals(record["completed_at"], C.CLOCK_EPOCH)
        A.assert_append_only_resource(record)

        rows = A.assert_total_count(
            api.list_journalist_training_records(
                desk.reporter_id, desk.reporter_headers
            ),
            1,
        )
        assert rows[0]["id"] == record["id"]
