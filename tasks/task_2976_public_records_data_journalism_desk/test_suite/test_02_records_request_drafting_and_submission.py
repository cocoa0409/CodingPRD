"""Drafting, superseding and submitting a records request (PRD S3.2).

This module covers the request lifecycle from the drafting letter to the
statutory clock starting: the input contract and its schema gate, the declared
defaults of the optional inputs, the system fields the server derives from the
caller, retrieval before and after submission, the filtered listing, the
per-entity not-found codes of PRD S2.5, the self-referential supersede edge and
its ledger refund, the declared initial states, submit idempotency, triggers
absent from the current state, and both optimistic-concurrency rules of PRD S2.8.

The harness restarts the server and wipes the database before every test, so
each test builds all of its own preconditions through the endpoints of PRD S4.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_AGENCY_NOT_FOUND,
    ERR_APPEAL_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_DATASET_NOT_FOUND,
    ERR_DESK_NOT_FOUND,
    ERR_FINDING_NOT_FOUND,
    ERR_INVALID_DATASET_STATE,
    ERR_INVALID_FINDING_STATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_REQUEST_STATE,
    ERR_INVESTIGATION_NOT_FOUND,
    ERR_REQUEST_NOT_FOUND,
    ERR_REVIEWER_NOT_FOUND,
    ERR_RUN_NOT_FOUND,
    ERR_SESSION_NOT_FOUND,
    ERR_STALE_DESK_VERSION,
    ERR_STALE_INVESTIGATION_VERSION,
    ERR_SUBJECT_REQUEST_NOT_FOUND,
    ERR_SUPERSEDE_TARGET_NOT_ACTIVE,
)
from test_helpers.assertions import (
    assert_audit_timestamp_format,
    assert_deadline_stamp,
    assert_field_absent_or_null,
    assert_instant_equals,
    assert_ledger_columns,
    assert_ledger_identity,
    assert_version_is,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated_page,
)
from test_helpers.test_users import (
    COORDINATOR_ALT_ID,
    COORDINATOR_ID,
    coordinator_headers,
    editor_headers,
    legal_headers,
    peer_reviewer_headers,
    reporter_headers,
)

# --------------------------------------------------------------------------
# Module-private setup chains (nothing here belongs in the shared helpers)
# --------------------------------------------------------------------------


def _registry(api, **desk_overrides):
    """The clock, a desk and the standard housing agency of PRD S3.2's example.

    Returns ``(desk, agency)`` as read from their creation responses.
    """
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(
        api,
        fee_budget_total_cents=desk_overrides.pop("fee_budget_total_cents", 500000),
        retention_policy_days=desk_overrides.pop("retention_policy_days", 1095),
        **desk_overrides,
    )
    agency = X.create_agency(api)
    return desk, agency


def _distinct_error_ids(responses):
    """The error ids of a batch of refusals, in call order."""
    return [response.json()["data"]["error_id"] for response in responses]


class TestRecordsRequestRequiredFields:
    """The input contract of PRD S3.2 under the schema gate of PRD S2.11."""

    def test_a_missing_waiver_flag_is_a_schema_violation(self, api):
        """waiver_requested is declared and has no default, so it cannot be omitted.

        PRD S3.2: "a waiver_requested boolean recording whether the letter asks
        for a public-interest fee waiver".

        PRD S2.11: "On every creation or action endpoint, the request body must
        satisfy the endpoint's input contract: every required field present".

        Design: Corner/entities/records_request_creation_rejects_a_missing_required_field
        """
        desk, agency = _registry(api)
        validate_error(
            api.create_records_request(
                F.records_request_payload(
                    desk["id"],
                    agency["id"],
                    desk["version"],
                    subject_summary="No waiver flag supplied",
                    estimated_page_count=10,
                    public_interest_score=10,
                    waiver_requested=F.OMIT,
                ),
                coordinator_headers(),
            ),
            ERR_INVALID_REQUEST,
        )

    def test_a_missing_version_token_is_a_schema_violation_not_a_stale_version(self, api):
        """Omitting the concurrency token is a schema fault, not a stale read.

        PRD S2.8: "Creating a records request requires a non-optional
        expected_desk_version field in the body, carrying the client's last
        observed version of the Desk named by desk_id."

        PRD S2.11: "the rules are evaluated in ascending priority order, and the
        first rule whose condition is violated determines the response".

        Design: Corner/entities/records_request_creation_rejects_a_missing_required_field
        """
        desk, agency = _registry(api)
        # The schema rung is priority 5; the version rung is priority 9.
        validate_error(
            api.create_records_request(
                F.records_request_payload(
                    desk["id"],
                    agency["id"],
                    F.OMIT,
                    subject_summary="No concurrency token supplied",
                    estimated_page_count=10,
                    waiver_requested=False,
                    public_interest_score=10,
                ),
                coordinator_headers(),
            ),
            ERR_INVALID_REQUEST,
        )

    def test_a_whitespace_only_subject_summary_is_blank(self, api):
        """A summary of three spaces carries no records description at all.

        PRD S3.2: "a subject_summary of 1 to 400 non-blank characters describing
        the records sought".

        Design: Corner/entities/records_request_creation_rejects_a_missing_required_field
        """
        desk, agency = _registry(api)
        validate_error(
            api.create_records_request(
                F.records_request_payload(
                    desk["id"],
                    agency["id"],
                    desk["version"],
                    subject_summary="   ",
                    estimated_page_count=10,
                    waiver_requested=False,
                    public_interest_score=10,
                ),
                coordinator_headers(),
            ),
            ERR_INVALID_REQUEST,
        )

    def test_no_rejected_draft_touched_the_parent_desk(self, api):
        """None of the three refused shapes created a row or bumped the desk.

        PRD S3.2: "Upon creation the request lands in DRAFT with
        requester_user_id set from X-User-ID, fee_committed_cents at 0,
        tolled_days_total at 0 and clarification_round_count at 0, and the desk's
        open_request_count and version each increment by 1."

        Design: Corner/entities/records_request_creation_rejects_a_missing_required_field
        """
        desk, agency = _registry(api)
        baseline = desk["version"]

        for payload in (
            F.records_request_payload(
                desk["id"], agency["id"], baseline, waiver_requested=F.OMIT
            ),
            F.records_request_payload(
                desk["id"], agency["id"], F.OMIT, waiver_requested=False
            ),
            F.records_request_payload(
                desk["id"], agency["id"], baseline, subject_summary="   "
            ),
        ):
            validate_error(
                api.create_records_request(payload, coordinator_headers()),
                ERR_INVALID_REQUEST,
            )

        after = X.read_desk(api, desk["id"])
        assert_version_is(after, baseline, "desk after three refused drafts")
        assert after["open_request_count"] == 0
        _rows, meta = validate_paginated_page(
            api.list_records_requests(coordinator_headers(), {"desk_id": desk["id"]})
        )
        assert meta["total_count"] == 0


class TestOptionalInputDefaults:
    """Every optional input falls back to the value PRD S3 declares for it."""

    def test_an_expert_reviewer_defaults_to_two_concurrent_assignments(self, api):
        """Omitting capacity and the conflict list yields 2 and an empty array.

        PRD S3.8: "an optional max_concurrent_assignments between 1 and 10 that
        defaults to 2, and an optional conflict_of_interest_agency_ids array of
        agency references that defaults to empty".

        PRD S3.8: "The reviewer opens with active_assignment_count at 0."

        Design: Corner/entities/optional_inputs_fall_back_to_their_declared_defaults
        """
        X.set_clock(api, C.STD_CLOCK)
        reviewer = validate_created(
            api.create_expert_reviewer(
                F.expert_reviewer_payload(
                    expertise_code="HOUSING",
                    max_concurrent_assignments=F.OMIT,
                ),
                editor_headers(),
            )
        )
        assert reviewer["max_concurrent_assignments"] == (
            C.DEFAULT_MAX_CONCURRENT_ASSIGNMENTS
        )
        assert reviewer["conflict_of_interest_agency_ids"] == []
        assert reviewer["active_assignment_count"] == 0

        stored = validate_ok(
            api.get_expert_reviewer(reviewer["id"], coordinator_headers())
        )
        assert stored["conflict_of_interest_agency_ids"] == []

    def test_a_secure_enclave_defaults_to_a_thirty_minute_buffer(self, api):
        """Omitting the sanitization buffer yields the declared 30 minutes.

        PRD S3.9: "an optional sanitization_buffer_minutes between 0 and 240 that
        defaults to 30 — the mandatory sanitization time after every session".

        PRD S3.9: "The enclave opens with booked_session_count at 0."

        Design: Corner/entities/optional_inputs_fall_back_to_their_declared_defaults
        """
        X.set_clock(api, C.STD_CLOCK)
        enclave = validate_created(
            api.create_secure_enclave(
                F.secure_enclave_payload(
                    name="Reading Room A",
                    max_documents=20,
                    sanitization_buffer_minutes=F.OMIT,
                ),
                legal_headers(),
            )
        )
        assert enclave["sanitization_buffer_minutes"] == (
            C.DEFAULT_SANITIZATION_BUFFER_MINUTES
        )
        assert enclave["max_documents"] == 20
        assert enclave["booked_session_count"] == 0

    def test_a_documented_field_opens_unsuppressed_with_no_known_issues(self, api):
        """Omitting the known-issue list yields an empty array, not null.

        PRD S3.6: "an optional known_issue_codes array drawn from TRUNCATED,
        MIXED_FORMAT, INCONSISTENT_CODING, OUT_OF_RANGE and DUPLICATE_KEYS,
        defaulting to an empty list".

        PRD S3.6: "Each new definition opens with suppression_applied false and
        suppression_method null".

        Design: Corner/entities/optional_inputs_fall_back_to_their_declared_defaults
        """
        desk, agency = _registry(api)
        request = X.draft_request(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Defaults probe",
            estimated_page_count=10,
            waiver_requested=False,
            public_interest_score=10,
        )
        investigation = X.create_investigation(
            api, desk["id"], C.MODE_METHODOLOGY_ONLY, headline="Defaults probe"
        )
        dataset = X.register_dataset(
            api,
            request["id"],
            investigation["id"],
            name=F.unique_dataset_name("defaults-probe"),
            expected_field_count=2,
            sensitivity_tier="PUBLIC",
        )
        field = validate_created(
            api.create_field_definition(
                dataset["id"],
                F.field_definition_payload(
                    "closure_reason",
                    reidentification_risk=2,
                    null_rate_pct=0.0,
                ),
                reporter_headers(),
            )
        )
        assert field["known_issue_codes"] == []
        assert field["suppression_applied"] is False
        assert field["suppression_method"] is None

    def test_an_agency_without_holidays_defaults_to_an_empty_list(self, api):
        """Omitting holiday_dates yields an empty array, not null.

        PRD S2.6: "a list of holiday_dates given as ISO-8601 date strings in
        YYYY-MM-DD form, defaulting to an empty list".

        Design: Corner/entities/optional_inputs_fall_back_to_their_declared_defaults
        """
        X.set_clock(api, C.STD_CLOCK)
        agency = validate_created(
            api.create_agency(
                F.agency_payload(holiday_dates=F.OMIT), coordinator_headers()
            )
        )
        assert agency["holiday_dates"] == []
        stored = validate_ok(api.get_agency(agency["id"], coordinator_headers()))
        assert stored["holiday_dates"] == []

    def test_a_dataset_stays_incomplete_below_its_expected_field_count(self, api):
        """One documented column of an expected two leaves documentation open.

        PRD S3.6: "Each new definition opens with suppression_applied false and
        suppression_method null, increments the dataset's field_definition_count
        by 1, adds the number of entries in its known_issue_codes to the
        dataset's known_issue_count, and sets documentation_status to COMPLETE
        once field_definition_count has reached expected_field_count (which is
        always at least 1) and INCOMPLETE otherwise."

        Design: Corner/entities/optional_inputs_fall_back_to_their_declared_defaults
        """
        desk, agency = _registry(api)
        request = X.draft_request(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Defaults probe",
            estimated_page_count=10,
            waiver_requested=False,
            public_interest_score=10,
        )
        investigation = X.create_investigation(
            api, desk["id"], C.MODE_METHODOLOGY_ONLY, headline="Defaults probe"
        )
        dataset = X.register_dataset(
            api,
            request["id"],
            investigation["id"],
            name=F.unique_dataset_name("defaults-probe"),
            expected_field_count=2,
            sensitivity_tier="PUBLIC",
        )
        X.document_field(
            api, dataset["id"], "closure_reason", reidentification_risk=2, null_rate_pct=0.0
        )
        stored = validate_ok(api.get_dataset(dataset["id"], reporter_headers()))
        assert stored["known_issue_count"] == 0
        assert stored["field_definition_count"] == 1
        assert stored["documentation_status"] == C.DOC_STATUS_INCOMPLETE


class TestCallerDerivedSystemFields:
    """The server mints the identity and audit fields; the client never does."""

    def test_the_requester_is_taken_from_the_calling_identity(self, api):
        """A draft filed by coord-001 records coord-001 as its requester.

        PRD S3.2: "Upon creation the request lands in DRAFT with
        requester_user_id set from X-User-ID, fee_committed_cents at 0,
        tolled_days_total at 0 and clarification_round_count at 0, and the desk's
        open_request_count and version each increment by 1."

        PRD S2.4: "Every resource carries a server-minted id: a UUID string with
        no type prefix."

        Design: Corner/entities/records_request_system_fields_are_generated_from_the_caller_identity
        """
        desk, agency = _registry(api)
        request = validate_created(
            api.create_records_request(
                F.records_request_payload(
                    desk["id"],
                    agency["id"],
                    desk["version"],
                    subject_summary="Filed by coordinator one",
                    estimated_page_count=10,
                    waiver_requested=False,
                    public_interest_score=10,
                ),
                coordinator_headers(COORDINATOR_ID),
            )
        )
        assert request["requester_user_id"] == COORDINATOR_ID
        assert isinstance(request["id"], str) and request["id"] != ""
        assert_audit_timestamp_format(request["created_at"], "request.created_at")
        assert_audit_timestamp_format(request["updated_at"], "request.updated_at")
        assert_version_is(request, 1, "freshly drafted request")

    def test_two_callers_produce_two_distinct_requesters(self, api):
        """The field tracks the caller, not the desk, so it differs per caller.

        PRD S3.2: "Upon creation the request lands in DRAFT with
        requester_user_id set from X-User-ID, fee_committed_cents at 0,
        tolled_days_total at 0 and clarification_round_count at 0, and the desk's
        open_request_count and version each increment by 1."

        Design: Corner/entities/records_request_system_fields_are_generated_from_the_caller_identity
        """
        desk, agency = _registry(api)
        first = validate_created(
            api.create_records_request(
                F.records_request_payload(
                    desk["id"],
                    agency["id"],
                    desk["version"],
                    subject_summary="Filed by coordinator one",
                    estimated_page_count=10,
                    waiver_requested=False,
                    public_interest_score=10,
                ),
                coordinator_headers(COORDINATOR_ID),
            )
        )
        second = validate_created(
            api.create_records_request(
                F.records_request_payload(
                    desk["id"],
                    agency["id"],
                    X.desk_version(api, desk["id"]),
                    subject_summary="Filed by coordinator two",
                    estimated_page_count=10,
                    waiver_requested=False,
                    public_interest_score=10,
                ),
                coordinator_headers(COORDINATOR_ALT_ID),
            )
        )
        assert second["requester_user_id"] == COORDINATOR_ALT_ID
        assert first["requester_user_id"] != second["requester_user_id"]
        assert first["id"] != second["id"]

    def test_a_requester_supplied_in_the_body_cannot_override_the_caller(self, api):
        """requester_user_id is no declared input, so the body cannot set it.

        PRD S2.11: "Unknown fields are ignored rather than rejected."

        PRD S3.2: "Upon creation the request lands in DRAFT with
        requester_user_id set from X-User-ID, fee_committed_cents at 0,
        tolled_days_total at 0 and clarification_round_count at 0, and the desk's
        open_request_count and version each increment by 1."

        Design: Corner/entities/records_request_system_fields_are_generated_from_the_caller_identity
        """
        desk, agency = _registry(api)
        request = validate_created(
            api.create_records_request(
                F.records_request_payload(
                    desk["id"],
                    agency["id"],
                    desk["version"],
                    subject_summary="Filed by coordinator one",
                    estimated_page_count=10,
                    waiver_requested=False,
                    public_interest_score=10,
                    requester_user_id=COORDINATOR_ALT_ID,
                ),
                coordinator_headers(COORDINATOR_ID),
            )
        )
        assert request["requester_user_id"] == COORDINATOR_ID

    def test_each_draft_bumps_the_desk_counter_and_version(self, api):
        """Two drafts leave the desk at two open requests and one more version.

        PRD S3.2: "Upon creation the request lands in DRAFT with
        requester_user_id set from X-User-ID, fee_committed_cents at 0,
        tolled_days_total at 0 and clarification_round_count at 0, and the desk's
        open_request_count and version each increment by 1."

        Design: Corner/entities/records_request_system_fields_are_generated_from_the_caller_identity
        """
        desk, agency = _registry(api)
        X.draft_request(
            api,
            desk["id"],
            agency["id"],
            coordinator_headers(COORDINATOR_ID),
            subject_summary="Filed by coordinator one",
            estimated_page_count=10,
            waiver_requested=False,
            public_interest_score=10,
        )
        desk_v2 = X.desk_version(api, desk["id"])
        X.draft_request(
            api,
            desk["id"],
            agency["id"],
            coordinator_headers(COORDINATOR_ALT_ID),
            subject_summary="Filed by coordinator two",
            estimated_page_count=10,
            waiver_requested=False,
            public_interest_score=10,
        )
        after = X.read_desk(api, desk["id"])
        assert after["open_request_count"] == 2
        assert_version_is(after, desk_v2 + 1, "desk after the second draft")


class TestRecordsRequestRetrieval:
    """Reading a request before and after the statutory clock starts."""

    def _drafted(self, api):
        desk, agency = _registry(api)
        request = X.draft_request(
            api,
            desk["id"],
            agency["id"],
            coordinator_headers(COORDINATOR_ID),
            subject_summary="Inspection narratives 2025",
            requested_format=C.FORMAT_CSV,
            estimated_page_count=240,
            waiver_requested=True,
            public_interest_score=72,
        )
        return desk, agency, request

    def test_the_read_echoes_every_stored_input(self, api):
        """A GET returns the letter exactly as it was drafted.

        PRD S3.2: "a subject_summary of 1 to 400 non-blank characters describing
        the records sought".

        PRD S3.2: "a waiver_requested boolean recording whether the letter asks
        for a public-interest fee waiver".

        Design: Corner/entities/records_request_retrieval_returns_the_stored_row_and_then_the_stamped_deadlines
        """
        desk, agency, request = self._drafted(api)
        stored = validate_ok(
            api.get_records_request(request["id"], reporter_headers())
        )
        assert stored["id"] == request["id"]
        assert stored["desk_id"] == desk["id"]
        assert stored["agency_id"] == agency["id"]
        assert stored["subject_summary"] == "Inspection narratives 2025"
        assert stored["requested_format"] == C.FORMAT_CSV
        assert stored["estimated_page_count"] == 240
        assert stored["waiver_requested"] is True
        assert stored["public_interest_score"] == 72

    def test_a_draft_carries_no_deadlines_and_no_fee_figures_yet(self, api):
        """Everything the later hops derive is still null or zero in DRAFT.

        PRD S3.2: "Upon creation the request lands in DRAFT with
        requester_user_id set from X-User-ID, fee_committed_cents at 0,
        tolled_days_total at 0 and clarification_round_count at 0, and the desk's
        open_request_count and version each increment by 1."

        Design: Corner/entities/records_request_retrieval_returns_the_stored_row_and_then_the_stamped_deadlines
        """
        _desk, _agency, request = self._drafted(api)
        stored = validate_ok(
            api.get_records_request(request["id"], reporter_headers())
        )
        assert stored["status"] == C.REQ_DRAFT
        for field in (
            "submitted_at",
            "due_at_strict",
            "due_at_tolled",
            "search_hours",
            "billed_page_count",
            "gross_fee_cents",
            "net_fee_cents",
            "fee_determined_at",
            "denial_reason_code",
            "supersedes_request_id",
        ):
            assert_field_absent_or_null(stored, field, "drafted request")
        assert stored["tolled_days_total"] == 0
        assert stored["clarification_round_count"] == 0
        assert stored["fee_committed_cents"] == 0
        assert_version_is(stored, 1, "drafted request")

    def test_the_post_submit_read_shows_the_stamped_deadlines(self, api):
        """A fresh read by another role returns the stamped statutory clock.

        PRD S3.2: "due_at_strict is the **unforgiving** statutory deadline: take
        the UTC calendar date of submitted_at, advance it by
        initial_response_days on the agency's basis, and stamp the result at
        23:59:59.000Z."

        PRD S3.2: "At submission tolled_days_total is zero, so the two variants
        coincide."

        Design: Corner/entities/records_request_retrieval_returns_the_stored_row_and_then_the_stamped_deadlines
        """
        _desk, _agency, request = self._drafted(api)
        validate_ok(
            api.submit_records_request(
                request["id"], coordinator_headers(COORDINATOR_ID)
            )
        )
        stored = validate_ok(api.get_records_request(request["id"], legal_headers()))
        assert stored["status"] == C.REQ_AWAITING_AGENCY_RESPONSE
        assert_instant_equals(stored["submitted_at"], C.STD_CLOCK, "submitted_at")
        assert_deadline_stamp(stored["due_at_strict"], "2026-08-17", "due_at_strict")
        assert_deadline_stamp(stored["due_at_tolled"], "2026-08-17", "due_at_tolled")
        assert_version_is(stored, 2, "submitted request")


class TestRecordsRequestListing:
    """The list endpoint's status filter and its window (PRD S2.3)."""

    def _three_requests(self, api):
        """Three drafts on one desk, the first of which is submitted."""
        desk, agency = _registry(api)
        rows = []
        for index, summary in enumerate(
            ("Request one", "Request two", "Request three"), start=1
        ):
            rows.append(
                X.draft_request(
                    api,
                    desk["id"],
                    agency["id"],
                    coordinator_headers(),
                    subject_summary=summary,
                    estimated_page_count=10 * index,
                    waiver_requested=False,
                    public_interest_score=10 * index,
                )
            )
        validate_ok(api.submit_records_request(rows[0]["id"], coordinator_headers()))
        return desk, rows

    def test_the_unfiltered_listing_fits_inside_the_default_window(self, api):
        """Three rows and a default limit of ten leave nothing beyond the page.

        PRD S2.3: "limit defaults to 10 when omitted, must be at least 1, and
        must not exceed 100".

        PRD S2.3: "The meta block of every list response carries limit, offset,
        total_count (the number of rows matching the filters before the window is
        applied) and has_more (true when more rows remain beyond the current
        window)."

        Design: Corner/entities/records_request_listing_filters_by_status_and_paginates
        """
        desk, _rows = self._three_requests(api)
        page, meta = validate_paginated_page(
            api.list_records_requests(editor_headers(), {"desk_id": desk["id"]})
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == C.DEFAULT_LIMIT
        assert len(page) == 3

    def test_the_draft_filter_windows_two_rows_one_at_a_time(self, api):
        """Two drafts remain, and a limit of one walks them without overlap.

        PRD S2.3: "The meta block of every list response carries limit, offset,
        total_count (the number of rows matching the filters before the window is
        applied) and has_more (true when more rows remain beyond the current
        window)."

        PRD S2.3: "Filter parameters, where an endpoint offers them, narrow the
        matched set before total_count is computed."

        Design: Corner/entities/records_request_listing_filters_by_status_and_paginates
        """
        desk, rows = self._three_requests(api)
        first_page, first_meta = validate_paginated_page(
            api.list_records_requests(
                editor_headers(),
                {
                    "desk_id": desk["id"],
                    "status": C.REQ_DRAFT,
                    "limit": 1,
                    "offset": 0,
                },
            )
        )
        assert first_meta["total_count"] == 2
        assert first_meta["has_more"] is True
        assert len(first_page) == 1
        assert first_page[0]["status"] == C.REQ_DRAFT

        second_page, second_meta = validate_paginated_page(
            api.list_records_requests(
                editor_headers(),
                {
                    "desk_id": desk["id"],
                    "status": C.REQ_DRAFT,
                    "limit": 1,
                    "offset": 1,
                },
            )
        )
        assert second_meta["total_count"] == 2
        assert second_meta["has_more"] is False
        assert len(second_page) == 1
        assert second_page[0]["status"] == C.REQ_DRAFT
        assert second_page[0]["id"] != first_page[0]["id"]

        assert {first_page[0]["id"], second_page[0]["id"]} == {
            rows[1]["id"],
            rows[2]["id"],
        }

    def test_the_submitted_filter_returns_only_the_submitted_row(self, api):
        """Filtering on the post-submit status isolates the one row in it.

        PRD S2.3: "Filter parameters, where an endpoint offers them, narrow the
        matched set before total_count is computed."

        Design: Corner/entities/records_request_listing_filters_by_status_and_paginates
        """
        desk, rows = self._three_requests(api)
        page, meta = validate_paginated_page(
            api.list_records_requests(
                editor_headers(),
                {
                    "desk_id": desk["id"],
                    "status": C.REQ_AWAITING_AGENCY_RESPONSE,
                },
            )
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(page) == 1
        assert page[0]["id"] == rows[0]["id"]


class TestPerEntityNotFoundCodes:
    """Every path-addressed entity answers with its own 404 code (PRD S2.5)."""

    def _probe(self, api, getter, headers):
        """One GET against the unresolvable id, returning the raw response."""
        return getter(C.UNRESOLVABLE_ID, headers)

    def test_the_first_six_entities_report_their_own_code(self, api):
        """Desk, agency, request, appeal, dataset and investigation each differ.

        PRD S2.5: "Each entity has its own not-found code, all at HTTP 404:
        ERR_DESK_NOT_FOUND, ERR_AGENCY_NOT_FOUND, ERR_REQUEST_NOT_FOUND ...,
        ERR_APPEAL_NOT_FOUND, ERR_DATASET_NOT_FOUND ..., ERR_FIELD_NOT_FOUND
        ..., ERR_INVESTIGATION_NOT_FOUND, ERR_RUN_NOT_FOUND,
        ERR_FINDING_NOT_FOUND, ERR_REVIEWER_NOT_FOUND, ERR_ASSIGNMENT_NOT_FOUND,
        ERR_SUBJECT_REQUEST_NOT_FOUND, ERR_ENCLAVE_NOT_FOUND ... and
        ERR_SESSION_NOT_FOUND."

        Design: Corner/entities/every_path_addressed_entity_reports_its_own_not_found_error
        """
        X.set_clock(api, C.STD_CLOCK)
        for getter, headers, expected in (
            (api.get_desk, editor_headers(), ERR_DESK_NOT_FOUND),
            (api.get_agency, coordinator_headers(), ERR_AGENCY_NOT_FOUND),
            (api.get_records_request, coordinator_headers(), ERR_REQUEST_NOT_FOUND),
            (api.get_appeal, legal_headers(), ERR_APPEAL_NOT_FOUND),
            (api.get_dataset, reporter_headers(), ERR_DATASET_NOT_FOUND),
            (api.get_investigation, editor_headers(), ERR_INVESTIGATION_NOT_FOUND),
        ):
            response = self._probe(api, getter, headers)
            error = validate_error(response, expected)
            assert error["message"].strip() != ""

    def test_the_second_six_entities_report_their_own_code(self, api):
        """Run, finding, reviewer, assignment, subject record and session differ.

        PRD S2.5: "Each entity has its own not-found code, all at HTTP 404:
        ERR_DESK_NOT_FOUND, ERR_AGENCY_NOT_FOUND, ERR_REQUEST_NOT_FOUND ...,
        ERR_APPEAL_NOT_FOUND, ERR_DATASET_NOT_FOUND ..., ERR_FIELD_NOT_FOUND
        ..., ERR_INVESTIGATION_NOT_FOUND, ERR_RUN_NOT_FOUND,
        ERR_FINDING_NOT_FOUND, ERR_REVIEWER_NOT_FOUND, ERR_ASSIGNMENT_NOT_FOUND,
        ERR_SUBJECT_REQUEST_NOT_FOUND, ERR_ENCLAVE_NOT_FOUND ... and
        ERR_SESSION_NOT_FOUND."

        Design: Corner/entities/every_path_addressed_entity_reports_its_own_not_found_error
        """
        X.set_clock(api, C.STD_CLOCK)
        for getter, headers, expected in (
            (api.get_analysis_run, peer_reviewer_headers(), ERR_RUN_NOT_FOUND),
            (api.get_finding, reporter_headers(), ERR_FINDING_NOT_FOUND),
            (api.get_expert_reviewer, editor_headers(), ERR_REVIEWER_NOT_FOUND),
            (api.get_review_assignment, editor_headers(), ERR_ASSIGNMENT_NOT_FOUND),
            (
                api.get_subject_response_request,
                coordinator_headers(),
                ERR_SUBJECT_REQUEST_NOT_FOUND,
            ),
            (api.get_enclave_session, legal_headers(), ERR_SESSION_NOT_FOUND),
        ):
            response = self._probe(api, getter, headers)
            error = validate_error(response, expected)
            assert error["message"].strip() != ""

    def test_the_twelve_codes_are_pairwise_distinct(self, api):
        """No two path-addressed entities share a not-found code.

        PRD S2.5: "Each entity has its own not-found code, all at HTTP 404".

        PRD S2.2: "The error_id is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/every_path_addressed_entity_reports_its_own_not_found_error
        """
        X.set_clock(api, C.STD_CLOCK)
        responses = [
            self._probe(api, api.get_desk, editor_headers()),
            self._probe(api, api.get_agency, coordinator_headers()),
            self._probe(api, api.get_records_request, coordinator_headers()),
            self._probe(api, api.get_appeal, legal_headers()),
            self._probe(api, api.get_dataset, reporter_headers()),
            self._probe(api, api.get_investigation, editor_headers()),
            self._probe(api, api.get_analysis_run, peer_reviewer_headers()),
            self._probe(api, api.get_finding, reporter_headers()),
            self._probe(api, api.get_expert_reviewer, editor_headers()),
            self._probe(api, api.get_review_assignment, editor_headers()),
            self._probe(
                api, api.get_subject_response_request, coordinator_headers()
            ),
            self._probe(api, api.get_enclave_session, legal_headers()),
        ]
        for response in responses:
            assert response.status_code == 404, (
                f"expected HTTP 404, got {response.status_code}: "
                f"{response.text[:200]}"
            )
            assert response.json()["response_type"] == "error"
        codes = _distinct_error_ids(responses)
        assert len(set(codes)) == len(codes) == 12, codes


def _supersede_setup(api):
    """A desk whose only request is submitted with a 6000-cent fee committed.

    The fee is 1.0 search hour at 3500 cents plus 100 pages at 25 cents, with no
    waiver, so the desk's committed column stands at 6000 of 500000.
    """
    desk, agency = _registry(api)
    request_a = X.fee_determined_request(
        api,
        desk["id"],
        agency["id"],
        search_hours=1.0,
        billed_page_count=100,
        request_overrides={
            "subject_summary": "All inspection narratives 2020-2025",
            "estimated_page_count": 100,
            "waiver_requested": False,
            "public_interest_score": 40,
        },
    )
    before = X.read_desk(api, desk["id"])
    assert_ledger_columns(before, 500000, 494000, 6000, 0)
    assert before["open_request_count"] == 1
    return desk, agency, request_a, before["version"]


class TestSelfReferentialSupersede:
    """The self-reference that withdraws its own target (PRD S3.2)."""

    def _supersede(self, api, desk_id, agency_id, target_id, summary):
        return api.create_records_request(
            F.records_request_payload(
                desk_id,
                agency_id,
                X.desk_version(api, desk_id),
                subject_summary=summary,
                estimated_page_count=40,
                waiver_requested=False,
                public_interest_score=40,
                supersedes_request_id=target_id,
            ),
            coordinator_headers(),
        )

    def test_the_new_request_supersedes_and_withdraws_its_target(self, api):
        """The replacement opens in DRAFT and the target lands in WITHDRAWN.

        PRD S3.2: "When the target is live, creating the new request drives the
        old one to WITHDRAWN, returns its fee_committed_cents from the desk's
        committed column to the available column, zeroes that field, and
        decrements open_request_count by 1 — all of which is precisely why this
        create is version-guarded."

        Design: Corner/entities/self_referential_supersede_withdraws_the_target_and_refunds_its_commitment
        """
        desk, agency, request_a, _desk_v2 = _supersede_setup(api)
        request_b = validate_created(
            self._supersede(
                api,
                desk["id"],
                agency["id"],
                request_a["id"],
                "Narrowed: inspection narratives 2024-2025 only",
            )
        )
        assert request_b["status"] == C.REQ_DRAFT
        assert request_b["supersedes_request_id"] == request_a["id"]
        assert request_b["fee_committed_cents"] == 0

        target = validate_ok(
            api.get_records_request(request_a["id"], coordinator_headers())
        )
        assert target["status"] == C.REQ_WITHDRAWN
        assert target["fee_committed_cents"] == 0

    def test_the_targets_commitment_returns_to_the_available_column(self, api):
        """The 6000 committed on the target goes back to available, not to spent.

        PRD S3.2: "When the target is live, creating the new request drives the
        old one to WITHDRAWN, returns its fee_committed_cents from the desk's
        committed column to the available column, zeroes that field, and
        decrements open_request_count by 1 — all of which is precisely why this
        create is version-guarded."

        PRD S2.7: "The governing invariant is a conserved quantity that must hold
        after every single mutation, with no drift: the total equals the sum of
        the available, committed and spent columns."

        Design: Corner/entities/self_referential_supersede_withdraws_the_target_and_refunds_its_commitment
        """
        desk, agency, request_a, desk_v2 = _supersede_setup(api)
        validate_created(
            self._supersede(
                api,
                desk["id"],
                agency["id"],
                request_a["id"],
                "Narrowed: inspection narratives 2024-2025 only",
            )
        )
        after = X.read_desk(api, desk["id"])
        assert_ledger_columns(after, 500000, 500000, 0, 0)
        assert_ledger_identity(after)
        assert after["open_request_count"] == 1
        assert_version_is(after, desk_v2 + 1, "desk after the supersede")

    def test_a_withdrawn_target_can_no_longer_be_superseded(self, api):
        """The second attempt on the same target finds it no longer live.

        PRD S3.2: "The target must belong to the same desk and must be live,
        meaning its status is DRAFT, AWAITING_AGENCY_RESPONSE or
        CLARIFICATION_REQUESTED; a target in any other status is refused with
        ERR_SUPERSEDE_TARGET_NOT_ACTIVE."

        Design: Corner/entities/self_referential_supersede_withdraws_the_target_and_refunds_its_commitment
        """
        desk, agency, request_a, _desk_v2 = _supersede_setup(api)
        validate_created(
            self._supersede(
                api,
                desk["id"],
                agency["id"],
                request_a["id"],
                "Narrowed: inspection narratives 2024-2025 only",
            )
        )
        validate_error(
            self._supersede(
                api,
                desk["id"],
                agency["id"],
                request_a["id"],
                "Second attempt at superseding the same target",
            ),
            ERR_SUPERSEDE_TARGET_NOT_ACTIVE,
        )
        after = X.read_desk(api, desk["id"])
        assert after["open_request_count"] == 1
        _rows, meta = validate_paginated_page(
            api.list_records_requests(editor_headers(), {"desk_id": desk["id"]})
        )
        assert meta["total_count"] == 2

    def test_the_supersede_edge_is_reverse_reachable(self, api):
        """Filtering on the target returns exactly the request that replaced it.

        PRD S4: "List records requests, filterable by desk_id, agency_id,
        supersedes_request_id and status."

        Design: Corner/entities/self_referential_supersede_withdraws_the_target_and_refunds_its_commitment
        """
        desk, agency, request_a, _desk_v2 = _supersede_setup(api)
        request_b = validate_created(
            self._supersede(
                api,
                desk["id"],
                agency["id"],
                request_a["id"],
                "Narrowed: inspection narratives 2024-2025 only",
            )
        )
        rows, meta = validate_paginated_page(
            api.list_records_requests(
                editor_headers(), {"supersedes_request_id": request_a["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == request_b["id"]


class TestDeclaredInitialStates:
    """Each machine opens on the value its own subsection declares."""

    def _probe_desk(self, api):
        return _registry(api, retention_policy_days=365)

    def test_a_records_request_opens_in_draft(self, api):
        """The drafting letter starts before submission, in DRAFT.

        PRD S3.2: "Upon creation the request lands in DRAFT with
        requester_user_id set from X-User-ID, fee_committed_cents at 0,
        tolled_days_total at 0 and clarification_round_count at 0, and the desk's
        open_request_count and version each increment by 1."

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
        """
        desk, agency = self._probe_desk(api)
        request = X.draft_request(
            api,
            desk["id"],
            agency["id"],
            coordinator_headers(),
            subject_summary="Initial state probe",
            estimated_page_count=10,
            waiver_requested=False,
            public_interest_score=10,
        )
        assert request["status"] == C.REQ_DRAFT

    def test_an_investigation_opens_in_drafting_and_not_ready(self, api):
        """Status and readiness are two dimensions, each at its own opening value.

        PRD S3.7: "A new investigation opens in DRAFTING with analysis_readiness
        at NOT_READY, finding_count, unverified_finding_count,
        doc_matched_finding_count, sme_confirmed_finding_count and
        sme_disputed_finding_count all at 0, and version at 1."

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
        """
        desk, _agency = self._probe_desk(api)
        investigation = X.create_investigation(
            api,
            desk["id"],
            C.MODE_METHODOLOGY_ONLY,
            headline="Initial state probe",
        )
        assert investigation["status"] == C.INV_DRAFTING
        assert investigation["analysis_readiness"] == C.READINESS_NOT_READY
        assert_version_is(investigation, 1, "new investigation")

    def test_a_dataset_opens_raw_with_nothing_delivered(self, api):
        """Registration precedes delivery, so the delivery fields are still unset.

        PRD S3.6: "A fresh dataset opens in RAW with format_negotiation_status at
        REQUESTED, documentation_status at INCOMPLETE, record_count at 0,
        field_definition_count at 0, known_issue_count at 0 and
        allocated_cost_cents at 0."

        PRD S3.6: "Delivery is the moment the data actually arrives. It records
        the delivered_format the agency really sent and the record_count of rows
        received, and it drives RAW → CLEANING."

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
        """
        desk, agency = self._probe_desk(api)
        request = X.draft_request(
            api,
            desk["id"],
            agency["id"],
            coordinator_headers(),
            subject_summary="Initial state probe",
            estimated_page_count=10,
            waiver_requested=False,
            public_interest_score=10,
        )
        investigation = X.create_investigation(
            api,
            desk["id"],
            C.MODE_METHODOLOGY_ONLY,
            headline="Initial state probe",
        )
        dataset = X.register_dataset(
            api,
            request["id"],
            investigation["id"],
            name=F.unique_dataset_name("initial-state-probe"),
            expected_field_count=1,
            sensitivity_tier="PUBLIC",
        )
        assert dataset["status"] == C.DS_RAW
        assert dataset["format_negotiation_status"] == C.FORMAT_NEG_REQUESTED
        assert dataset["documentation_status"] == C.DOC_STATUS_INCOMPLETE
        assert dataset["record_count"] == 0
        assert_field_absent_or_null(dataset, "delivered_format", "fresh dataset")
        assert_field_absent_or_null(dataset, "retention_expires_at", "fresh dataset")

    def test_a_right_of_reply_record_opens_in_draft_with_no_attempts(self, api):
        """Nobody has been contacted yet, so the attempt log is empty.

        PRD S3.9: "It opens in DRAFT with attempt_count at 0 and an empty
        documented_attempts log, and it stays in DRAFT until the investigation's
        findings are locked, which moves it to NOTICE_ELIGIBLE."

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
        """
        desk, _agency = self._probe_desk(api)
        investigation = X.create_investigation(
            api,
            desk["id"],
            C.MODE_METHODOLOGY_ONLY,
            headline="Initial state probe",
        )
        record = X.create_subject_record(
            api,
            investigation["id"],
            subject_name="Housing Authority Director",
            contact_channel="EMAIL",
        )
        assert record["status"] == C.SUBJ_DRAFT
        assert record["attempt_count"] == 0
        assert record["documented_attempts"] == []
        assert_field_absent_or_null(record, "notice_sent_at", "new subject record")
        assert_field_absent_or_null(
            record, "response_deadline_at", "new subject record"
        )

    def test_an_analysis_run_opens_on_both_of_its_dimensions(self, api):
        """Review and allocation are independent, and both open at their own value.

        PRD S3.7: "A run opens with code_review_status at PENDING_REVIEW,
        cost_allocation_status at NOT_ALLOCATED, review_cycle_count at 0,
        allocated_total_cents at 0, authored_by_user_id set from X-User-ID,
        peer_review_note and reviewed_by_user_id null."

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
        """
        desk, _agency = self._probe_desk(api)
        investigation = X.create_investigation(
            api,
            desk["id"],
            C.MODE_METHODOLOGY_ONLY,
            headline="Initial state probe",
        )
        run = X.create_run(
            api, investigation["id"], compute_cost_cents=0, labor_hours=0.0
        )
        assert run["code_review_status"] == C.REVIEW_PENDING
        assert run["cost_allocation_status"] == C.ALLOC_NOT_ALLOCATED
        assert run["review_cycle_count"] == 0
        assert run["allocated_total_cents"] == 0


class TestSubmitIsNotIdempotent:
    """Submission is a one-shot transition out of DRAFT (PRD S3.2)."""

    def _drafted(self, api):
        desk, agency = _registry(api, retention_policy_days=365)
        request = X.draft_request(
            api,
            desk["id"],
            agency["id"],
            coordinator_headers(),
            subject_summary="Idempotency probe",
            estimated_page_count=10,
            waiver_requested=False,
            public_interest_score=10,
        )
        return desk, agency, request

    def test_the_first_submit_starts_the_statutory_clock(self, api):
        """The one accepted submit stamps the instant and both deadlines.

        PRD S3.2: "The transition DRAFT → AWAITING_AGENCY_RESPONSE stamps
        submitted_at from the logical clock and computes both deadline variants
        using the day arithmetic of §2.6."

        Design: Corner/state_machines/submitting_the_same_request_twice_is_rejected_on_the_second_call
        """
        _desk, _agency, request = self._drafted(api)
        submitted = validate_ok(
            api.submit_records_request(request["id"], coordinator_headers())
        )
        assert submitted["status"] == C.REQ_AWAITING_AGENCY_RESPONSE
        assert_instant_equals(submitted["submitted_at"], C.STD_CLOCK, "submitted_at")
        assert_deadline_stamp(
            submitted["due_at_strict"], "2026-08-17", "due_at_strict"
        )
        assert_version_is(submitted, 2, "submitted request")

    def test_the_second_submit_is_refused_on_state(self, api):
        """A request already out of DRAFT has no submit transition left.

        PRD S3.2: "Submitting is only declared from DRAFT; attempting it from
        anywhere else is ERR_INVALID_REQUEST_STATE."

        Design: Corner/state_machines/submitting_the_same_request_twice_is_rejected_on_the_second_call
        """
        _desk, _agency, request = self._drafted(api)
        validate_ok(api.submit_records_request(request["id"], coordinator_headers()))
        X.set_clock(api, "2026-08-05T09:00:00Z")
        validate_error(
            api.submit_records_request(request["id"], coordinator_headers()),
            ERR_INVALID_REQUEST_STATE,
        )

    def test_the_refused_submit_moves_neither_stamp_nor_version(self, api):
        """The later clock does not re-stamp anything, because nothing was written.

        PRD S3.2: "It is written once at submission and is never revised
        afterwards, no matter how many clarification rounds or granted appeals
        intervene".

        PRD S2.4: "version, an integer that starts at 1 on creation and increases
        by exactly 1 on every mutation of the row".

        Design: Corner/state_machines/submitting_the_same_request_twice_is_rejected_on_the_second_call
        """
        _desk, _agency, request = self._drafted(api)
        validate_ok(api.submit_records_request(request["id"], coordinator_headers()))
        X.set_clock(api, "2026-08-05T09:00:00Z")
        validate_error(
            api.submit_records_request(request["id"], coordinator_headers()),
            ERR_INVALID_REQUEST_STATE,
        )
        stored = validate_ok(
            api.get_records_request(request["id"], coordinator_headers())
        )
        assert_instant_equals(stored["submitted_at"], C.STD_CLOCK, "submitted_at")
        assert_deadline_stamp(stored["due_at_strict"], "2026-08-17", "due_at_strict")
        assert_version_is(stored, 2, "request after the refused resubmit")


def _invalid_transition_setup(api):
    """A released request with a CLEANING dataset, a submitted request, and a
    finding that has already been document-matched once."""
    desk, agency = _registry(api, retention_policy_days=365)
    request_a = X.released_request(
        api,
        desk["id"],
        agency["id"],
        subject_summary="Invalid transition probe A",
        estimated_page_count=10,
        waiver_requested=False,
        public_interest_score=10,
    )
    request_b = X.submitted_request(
        api,
        desk["id"],
        agency["id"],
        subject_summary="Invalid transition probe B",
        estimated_page_count=10,
        waiver_requested=False,
        public_interest_score=10,
    )
    investigation = X.create_investigation(
        api,
        desk["id"],
        C.MODE_METHODOLOGY_ONLY,
        headline="Invalid transition probe",
    )
    dataset = X.delivered_dataset(
        api,
        request_a["id"],
        investigation["id"],
        record_count=100,
        delivered_format=C.FORMAT_CSV,
        name=F.unique_dataset_name("invalid-transition-probe"),
        expected_field_count=1,
        sensitivity_tier="PUBLIC",
    )
    run = X.create_run(
        api, investigation["id"], compute_cost_cents=1000, labor_hours=1.0
    )
    finding = X.create_finding(
        api,
        investigation["id"],
        run["id"],
        claim_text="Already document-matched.",
    )
    validate_ok(
        api.match_document(
            finding["id"],
            F.document_match_payload(3, source_document_ref="BOX-1/DOC-0001"),
            reporter_headers(),
        )
    )
    return {
        "desk": desk,
        "request_a": request_a,
        "request_b": request_b,
        "investigation": investigation,
        "dataset": dataset,
        "run": run,
        "finding": finding,
    }


class TestTriggersAbsentFromTheCurrentState:
    """A transition that the current state does not declare is refused."""

    def test_a_second_document_match_is_refused_and_changes_nothing(self, api):
        """The finding has left UNVERIFIED, so it can no longer be matched.

        PRD S3.8: "It is only declared from UNVERIFIED; a second match, or a
        match on an already-expert-reviewed finding, is
        ERR_INVALID_FINDING_STATE."

        Design: Corner/state_machines/triggers_absent_from_the_current_state_are_rejected
        """
        world = _invalid_transition_setup(api)
        validate_error(
            api.match_document(
                world["finding"]["id"],
                F.document_match_payload(4, source_document_ref="BOX-1/DOC-0002"),
                reporter_headers(),
            ),
            ERR_INVALID_FINDING_STATE,
        )
        stored = validate_ok(
            api.get_finding(world["finding"]["id"], reporter_headers())
        )
        assert stored["matched_page"] == 3
        assert stored["source_document_ref"] == "BOX-1/DOC-0001"

    def test_neither_requalification_nor_quarantine_is_declared_from_cleaning(
        self, api
    ):
        """A CLEANING dataset is neither quarantined nor awaiting remediation.

        PRD S3.6: "Quarantine records a quarantine_reason_code of
        SOURCE_INTEGRITY, MISMATCHED_TOTALS, UNRESOLVED_NULLS or LEGAL_HOLD and
        is only declared from CLEAN_LOCKED."

        PRD S3.6: "Requalification accepts remediation_notes, drives QUARANTINED
        → CLEANING, and clears quarantine_reason_code back to null, so a
        remediated dataset can be documented further, locked again, and made
        allocable again — the dataset lifecycle is a genuine cycle."

        Design: Corner/state_machines/triggers_absent_from_the_current_state_are_rejected
        """
        world = _invalid_transition_setup(api)
        dataset_id = world["dataset"]["id"]
        validate_error(
            api.requalify_dataset(
                dataset_id,
                F.requalification_payload(
                    remediation_notes="Dataset is CLEANING, not QUARANTINED."
                ),
                reporter_headers(),
            ),
            ERR_INVALID_DATASET_STATE,
        )
        assert X.read_dataset(api, dataset_id)["status"] == C.DS_CLEANING

        validate_error(
            api.quarantine_dataset(
                dataset_id,
                F.quarantine_payload("MISMATCHED_TOTALS"),
                editor_headers(),
            ),
            ERR_INVALID_DATASET_STATE,
        )
        assert X.read_dataset(api, dataset_id)["status"] == C.DS_CLEANING

    def test_answering_a_clarification_that_was_never_asked_is_refused(self, api):
        """No round is open, so there is nothing to close and nothing to toll.

        PRD S3.4: "Answering the agency, with an answer_text payload, closes the
        round and returns the request CLARIFICATION_REQUESTED →
        AWAITING_AGENCY_RESPONSE."

        PRD S2.11: "The target entity must be in a state from which the requested
        transition is declared."

        Design: Corner/state_machines/triggers_absent_from_the_current_state_are_rejected
        """
        world = _invalid_transition_setup(api)
        validate_error(
            api.respond_clarification(
                world["request_b"]["id"],
                F.clarification_response_payload(
                    answer_text="No clarification round is open."
                ),
                coordinator_headers(),
            ),
            ERR_INVALID_REQUEST_STATE,
        )
        stored = validate_ok(
            api.get_records_request(
                world["request_b"]["id"], coordinator_headers()
            )
        )
        assert stored["tolled_days_total"] == 0
        assert_deadline_stamp(stored["due_at_tolled"], "2026-08-17", "due_at_tolled")

    def test_each_machine_reports_its_own_state_code(self, api):
        """Three refusals, three different codes, and no state moved at all.

        PRD S2.11: "The code returned depends on the entity:
        ERR_INVALID_REQUEST_STATE, ERR_INVALID_APPEAL_STATE,
        ERR_INVALID_DATASET_STATE, ERR_INVALID_INVESTIGATION_STATE,
        ERR_INVALID_RUN_STATE, ERR_INVALID_FINDING_STATE,
        ERR_INVALID_SUBJECT_STATE or ERR_INVALID_SESSION_STATE."

        Design: Corner/state_machines/triggers_absent_from_the_current_state_are_rejected
        """
        world = _invalid_transition_setup(api)
        responses = [
            api.match_document(
                world["finding"]["id"],
                F.document_match_payload(4, source_document_ref="BOX-1/DOC-0002"),
                reporter_headers(),
            ),
            api.requalify_dataset(
                world["dataset"]["id"],
                F.requalification_payload(
                    remediation_notes="Dataset is CLEANING, not QUARANTINED."
                ),
                reporter_headers(),
            ),
            api.respond_clarification(
                world["request_b"]["id"],
                F.clarification_response_payload(
                    answer_text="No clarification round is open."
                ),
                coordinator_headers(),
            ),
        ]
        codes = _distinct_error_ids(responses)
        assert len(set(codes)) == len(codes) == 3, codes

        investigation = X.read_investigation(api, world["investigation"]["id"])
        assert investigation["doc_matched_finding_count"] == 1
        assert investigation["status"] == C.INV_ANALYSIS


_OCC_REQUEST_BODY = {
    "subject_summary": "Stale desk view",
    "estimated_page_count": 10,
    "waiver_requested": False,
    "public_interest_score": 10,
}
_OCC_RUN_ONE = {
    "code_repo_ref": "git@desk/occ",
    "code_commit_sha": "3" * 40,
    "container_digest": "sha256:" + "3" * 64,
}
_OCC_RUN_TWO = {
    "code_repo_ref": "git@desk/occ",
    "code_commit_sha": "4" * 40,
    "container_digest": "sha256:" + "4" * 64,
}


def _occ_setup(api):
    """A desk and an investigation whose versions can both be made stale."""
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(
        api, fee_budget_total_cents=500000, retention_policy_days=1095
    )
    agency = X.create_agency(
        api,
        tolling_allowed=False,
        appeal_venue=C.VENUE_INTERNAL,
        appeal_decision_days=15,
    )
    seed = X.released_request(
        api,
        desk["id"],
        agency["id"],
        subject_summary="OCC seed request",
        estimated_page_count=10,
        waiver_requested=False,
        public_interest_score=10,
    )
    investigation = X.create_investigation(
        api, desk["id"], C.MODE_METHODOLOGY_ONLY, headline="OCC probe"
    )
    X.clean_locked_dataset(
        api,
        seed["id"],
        investigation["id"],
        record_count=250,
        field_specs=[
            {
                "field_name": "row_id",
                "null_rate_pct": 0.0,
                "reidentification_risk": 1,
                "is_source_identifying": False,
            }
        ],
        name=F.unique_dataset_name("occ-probe-set"),
        sensitivity_tier="PUBLIC",
    )
    return desk, agency, investigation


class TestBothOptimisticConcurrencyRules:
    """The desk rule and the investigation rule, each with its own code."""

    def test_a_budget_adjustment_makes_the_clients_desk_view_stale(self, api):
        """The adjustment bumps the desk version the drafting client had read.

        PRD S3.1: "the delta is added to fee_budget_total_cents and to
        fee_budget_available_cents alike, which is what keeps the conserved
        identity of §2.7 intact".

        PRD S2.8: "If that value does not equal the desk's current version, the
        create is rejected with ERR_STALE_DESK_VERSION (HTTP 412) and nothing is
        written."

        Design: Corner/cross-cutting complexity layers/both_occ_rules_reject_a_stale_parent_version_and_accept_a_fresh_one
        """
        desk, agency, _investigation = _occ_setup(api)
        desk_v1 = X.desk_version(api, desk["id"])
        adjusted = validate_ok(
            api.create_budget_adjustment(
                desk["id"],
                F.budget_adjustment_payload(
                    25000, reason="Reserve for the litigation track."
                ),
                editor_headers(),
            )
        )
        assert adjusted["version"] != desk_v1
        validate_error(
            api.create_records_request(
                F.records_request_payload(
                    desk["id"], agency["id"], desk_v1, **_OCC_REQUEST_BODY
                ),
                coordinator_headers(),
            ),
            ERR_STALE_DESK_VERSION,
        )

    def test_the_same_body_is_accepted_once_the_desk_version_is_refreshed(self, api):
        """Only the version token was wrong, and nothing was written meanwhile.

        PRD S2.8: "A fresh expected_desk_version is obtained by reading the
        desk."

        PRD S2.8: "If that value does not equal the desk's current version, the
        create is rejected with ERR_STALE_DESK_VERSION (HTTP 412) and nothing is
        written."

        Design: Corner/cross-cutting complexity layers/both_occ_rules_reject_a_stale_parent_version_and_accept_a_fresh_one
        """
        desk, agency, _investigation = _occ_setup(api)
        desk_v1 = X.desk_version(api, desk["id"])
        validate_ok(
            api.create_budget_adjustment(
                desk["id"],
                F.budget_adjustment_payload(
                    25000, reason="Reserve for the litigation track."
                ),
                editor_headers(),
            )
        )
        validate_error(
            api.create_records_request(
                F.records_request_payload(
                    desk["id"], agency["id"], desk_v1, **_OCC_REQUEST_BODY
                ),
                coordinator_headers(),
            ),
            ERR_STALE_DESK_VERSION,
        )
        _rows, meta = validate_paginated_page(
            api.list_records_requests(editor_headers(), {"desk_id": desk["id"]})
        )
        assert meta["total_count"] == 1

        created = validate_created(
            api.create_records_request(
                F.records_request_payload(
                    desk["id"],
                    agency["id"],
                    X.desk_version(api, desk["id"]),
                    **_OCC_REQUEST_BODY,
                ),
                coordinator_headers(),
            )
        )
        assert created["subject_summary"] == _OCC_REQUEST_BODY["subject_summary"]

    def test_a_stale_investigation_view_has_its_own_distinct_code(self, api):
        """Creating a run bumps the investigation, so the next create must reread.

        PRD S2.8: "If that value does not equal the investigation's current
        version, the create is rejected with ERR_STALE_INVESTIGATION_VERSION
        (HTTP 412) and nothing is written."

        PRD S3.7: "Each run receives a run_sequence equal to 1 plus the count of
        runs that already exist for the same investigation, and the run with the
        highest run_sequence is by definition the investigation's **current
        run**."

        Design: Corner/cross-cutting complexity layers/both_occ_rules_reject_a_stale_parent_version_and_accept_a_fresh_one
        """
        _desk, _agency, investigation = _occ_setup(api)
        inv_v1 = X.investigation_version(api, investigation["id"])
        first = validate_created(
            api.create_analysis_run(
                F.analysis_run_payload(
                    investigation["id"],
                    inv_v1,
                    compute_cost_cents=5000,
                    labor_hours=1.0,
                    **_OCC_RUN_ONE,
                ),
                reporter_headers(),
            )
        )
        assert first["run_sequence"] == 1

        validate_error(
            api.create_analysis_run(
                F.analysis_run_payload(
                    investigation["id"],
                    inv_v1,
                    compute_cost_cents=5000,
                    labor_hours=1.0,
                    **_OCC_RUN_TWO,
                ),
                reporter_headers(),
            ),
            ERR_STALE_INVESTIGATION_VERSION,
        )
        assert ERR_STALE_INVESTIGATION_VERSION != ERR_STALE_DESK_VERSION
        _rows, meta = validate_paginated_page(
            api.list_analysis_runs(
                reporter_headers(), {"investigation_id": investigation["id"]}
            )
        )
        assert meta["total_count"] == 1

    def test_the_second_run_is_accepted_on_the_refreshed_investigation(self, api):
        """The refreshed version admits the run and it becomes sequence two.

        PRD S2.8: "A fresh expected_investigation_version is obtained by reading
        the investigation."

        PRD S3.7: "Each run receives a run_sequence equal to 1 plus the count of
        runs that already exist for the same investigation, and the run with the
        highest run_sequence is by definition the investigation's **current
        run**."

        Design: Corner/cross-cutting complexity layers/both_occ_rules_reject_a_stale_parent_version_and_accept_a_fresh_one
        """
        _desk, _agency, investigation = _occ_setup(api)
        inv_v1 = X.investigation_version(api, investigation["id"])
        validate_created(
            api.create_analysis_run(
                F.analysis_run_payload(
                    investigation["id"],
                    inv_v1,
                    compute_cost_cents=5000,
                    labor_hours=1.0,
                    **_OCC_RUN_ONE,
                ),
                reporter_headers(),
            )
        )
        inv_v2 = X.investigation_version(api, investigation["id"])
        assert inv_v2 != inv_v1
        second = validate_created(
            api.create_analysis_run(
                F.analysis_run_payload(
                    investigation["id"],
                    inv_v2,
                    compute_cost_cents=5000,
                    labor_hours=1.0,
                    **_OCC_RUN_TWO,
                ),
                reporter_headers(),
            )
        )
        assert second["run_sequence"] == 2
