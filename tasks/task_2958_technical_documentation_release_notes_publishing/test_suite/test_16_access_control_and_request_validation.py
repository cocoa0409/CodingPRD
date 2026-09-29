"""Authentication, role boundaries, per-resource reporting, and request validity.

Every endpoint in this domain is wrapped by the same four outermost checks, and
which one a caller trips is specified behaviour rather than an implementation
accident.  This module covers the identity headers and the order in which their
failures are reported, the role boundaries that separate the six capacities from
one another, the family of resource-specific not-found codes, the request-level
rejections for the logical clock and pagination and date windows, and the five
differently scoped uniqueness keys.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    UNRESOLVABLE_ENTITY_USER_ID,
    assign_plan_item_payload,
    assigned_plan_item_context,
    create_change_record_payload,
    create_clock_payload,
    create_locale_profile,
    create_locale_profile_payload,
    create_localization_job_payload,
    create_plan_item_payload,
    create_release_train,
    create_release_train_payload,
    create_reviewer_payload,
    create_terminology_term,
    create_terminology_term_payload,
    create_topic_payload,
    create_writer,
    create_writer_payload,
    feedback_context,
    instants_equal,
    make_headers_empty_role,
    make_headers_empty_user_id,
    make_headers_missing_role,
    make_headers_missing_user_id,
    plan_item_context,
    read_locale_profile,
    read_plan_item,
    read_release_train,
    set_clock,
    topic_context,
    validate_error,
    validate_list,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"


class TestPlanningIsExclusiveToTheDocsLead:
    """A Writer holds real write authority over content, which is precisely why the
    denial has to be scoped to the planning operations rather than to writing."""

    def test_a_writer_cannot_create_a_planned_deliverable(
        self, api, docs_lead_headers, writer_headers_for
    ):
        """Creating a plan item is a DocsLead operation and a Writer is refused it.

        PRD §2.1: "A value of `X-User-Role` that is not one of these six is
        rejected, as is a recognized role that does not appear in the
        authorized-role list for the endpoint being called; both cases return
        `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §2.1: "Section 4 lists the authorized roles for every endpoint, and
        that list is exhaustive — a role absent from an endpoint's row has no
        access to it under any circumstances."

        PRD §3.2: "A `DocsLead` creates it against a `release_train_id` with a
        `feature_key` of 1 to 60 characters that must be unique within that
        train, an `ia_placement` of `NEW_TOPIC`, `EXISTING_TOPIC_UPDATE`, or
        `CONCEPT_HUB` recording the information-architecture decision, an
        `audience_tier` of `CRITICAL`, `STANDARD`, or `INTERNAL`, a
        `planned_page_count` between 1 and 500 inclusive, and
        `complexity_points` between 0 and 100 inclusive as the estimator's
        judgement of difficulty."

        Design: Corner/rbac/writer_cannot_plan_or_assign_work_unauthorized
        """
        set_clock(CLOCK)
        bundle = plan_item_context()

        response = api.create_plan_item(
            create_plan_item_payload(bundle["train_id"]), writer_headers_for(bundle["writer_id"])
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED, 403)

        _, meta = validate_list(
            api.list_plan_items(docs_lead_headers, params={"release_train_id": bundle["train_id"]})
        )
        assert meta["total_count"] == 1

    def test_a_writer_cannot_assign_work_even_to_themselves(
        self, api, docs_lead_headers, writer_headers_for
    ):
        """The assignment endpoint belongs to the DocsLead, so a writer cannot take
        a deliverable off the board on their own authority.

        PRD §2.1: "A value of `X-User-Role` that is not one of these six is
        rejected, as is a recognized role that does not appear in the
        authorized-role list for the endpoint being called; both cases return
        `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §3.2: "The `DocsLead` supplies a `writer_id` together with
        `window_start_date` and `window_end_date` describing the half-open
        authoring window the deliverable will occupy on that writer's calendar."

        Design: Corner/rbac/writer_cannot_plan_or_assign_work_unauthorized
        """
        set_clock(CLOCK)
        bundle = plan_item_context()

        response = api.assign_plan_item(
            bundle["plan_item_id"],
            assign_plan_item_payload(
                bundle["writer_id"],
                window_start_date="2026-08-03",
                window_end_date="2026-08-17",
            ),
            writer_headers_for(bundle["writer_id"]),
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED, 403)

        unchanged = read_plan_item(bundle["plan_item_id"])
        assert unchanged["status"] == "DRAFTED"
        assert unchanged["assigned_writer_id"] is None

    def test_a_writer_cannot_move_the_logical_clock(
        self, api, docs_lead_headers, writer_headers_for
    ):
        """Only the DocsLead may advance the clock, and a refused attempt leaves the
        clock where it was, as the next creation's stamp shows.

        PRD §2.4: "A `DocsLead` — the only role with this capability — may move
        the clock forward by supplying a `current_utc` instant to an
        administrative clock-setting capability, which responds with HTTP 200."

        PRD §2.1: "A value of `X-User-Role` that is not one of these six is
        rejected, as is a recognized role that does not appear in the
        authorized-role list for the endpoint being called; both cases return
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/writer_cannot_plan_or_assign_work_unauthorized
        """
        set_clock(CLOCK)
        bundle = plan_item_context()

        response = api.set_clock(
            create_clock_payload("2026-08-02T00:00:00Z"), writer_headers_for(bundle["writer_id"])
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED, 403)

        later = validate_success(
            api.create_release_train(create_release_train_payload(), docs_lead_headers), 201
        )
        assert instants_equal(later["created_at"], CLOCK)

    def test_a_writer_may_still_submit_a_change_record_for_the_release(
        self, api, docs_lead_headers, writer_headers_for
    ):
        """The change-record write is shared with the Writer, so the planning
        denials above are a scoped rule and not a blanket one.

        PRD §3.7: "Either a `DocsLead` or a `Writer` may submit one against a
        `release_train_id`, supplying an `internal_summary` of 1 to 300
        characters copied from the change-management system, a `severity` of
        `BREAKING`, `SECURITY`, `MAJOR`, `MINOR`, or `PATCH`, a `category` of
        `FEATURE`, `FIX`, `PERFORMANCE`, `SECURITY_PATCH`, or `DEPRECATION`, and
        an `affected_component` key of 1 to 60 characters."

        PRD §3.7: "The record opens in state `SUBMITTED` with
        `submitted_by_user_id` taken from the submitter's `X-User-ID`,
        `customer_facing_text` null, `terminology_blocker_count` 0,
        `rework_count` 0, and `exclusion_reason` null."

        Design: Corner/rbac/writer_cannot_plan_or_assign_work_unauthorized
        """
        set_clock(CLOCK)
        bundle = plan_item_context()

        record = validate_success(
            api.create_change_record(
                create_change_record_payload(
                    bundle["train_id"], internal_summary="Writer-submitted change", category="FIX"
                ),
                writer_headers_for(bundle["writer_id"]),
            ),
            201,
        )

        assert record["state"] == "SUBMITTED"
        assert record["submitted_by_user_id"] == bundle["writer_id"]
        assert record["category"] == "FIX"
        assert record["customer_facing_text"] is None


class TestPeerRolesCannotCrossTheirBoundaries:
    """Four denials that each sit one step away from something the role really can
    do, so a coarse rule would pass the wrong test."""

    def test_a_reader_may_read_one_page_but_not_the_page_collection(
        self, api, reader_headers
    ):
        """The single-topic read is the Reader's only read, and the collection is
        outside it.

        PRD §2.1: "`Reader` is deliberately the weakest role in the system: it
        may read a single topic and leave one page rating per reading session,
        and nothing else."

        PRD §2.1: "Section 4 lists the authorized roles for every endpoint, and
        that list is exhaustive — a role absent from an endpoint's row has no
        access to it under any circumstances."

        Design: Corner/rbac/reader_and_coordinator_and_analyst_cannot_cross_role_boundaries_unauthorized
        """
        set_clock(CLOCK)
        bundle = feedback_context()

        validate_error(api.list_topics(reader_headers), ApiErrorId.UNAUTHORIZED, 403)

        page = validate_success(api.get_topic(bundle["topic_id"], reader_headers))
        assert page["id"] == bundle["topic_id"]
        assert page["publication_state"] == "PUBLISHED"

    def test_a_localization_coordinator_cannot_read_reader_signals(
        self, api, localization_coordinator_headers, support_analyst_headers
    ):
        """Both reader-signal reads are reserved to the DocsLead and the
        SupportAnalyst, and the analyst's identical reads succeed.

        PRD §3.10: "A `DocsLead` or a `SupportAnalyst` — and nobody else — may
        list a page's feedback, filtered by `outcome`, in `created_at` ascending
        order; rows that have aged out of the metrics window are still returned
        there even though they no longer influence any figure."

        PRD §3.10: "**Deflection metrics** are computed over a trailing 30-day
        window ending at the logical clock, and are available to a `DocsLead` or
        `SupportAnalyst` as a computed read on the topic."

        Design: Corner/rbac/reader_and_coordinator_and_analyst_cannot_cross_role_boundaries_unauthorized
        """
        set_clock(CLOCK)
        bundle = feedback_context(rows=({"rating": 5},))

        validate_error(
            api.list_topic_feedback(bundle["topic_id"], localization_coordinator_headers),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.get_deflection_summary(bundle["topic_id"], localization_coordinator_headers),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

        rows, meta = validate_list(
            api.list_topic_feedback(bundle["topic_id"], support_analyst_headers)
        )
        assert meta["total_count"] == 1
        assert rows[0]["rating"] == 5
        summary = validate_success(
            api.get_deflection_summary(bundle["topic_id"], support_analyst_headers)
        )
        assert summary["sample_count"] == 1
        assert summary["mean_rating"] == pytest.approx(5.00, abs=0.01)

    def test_a_support_analyst_writes_nothing_at_all(
        self, api, docs_lead_headers, support_analyst_headers
    ):
        """The analyst identity exists purely for reading, so even the write the
        Writer shares with the DocsLead is closed to it.

        PRD §2.1: "The same holds for `LocalizationCoordinator`, whose
        `X-User-ID` is an opaque coordinator identifier that the server neither
        persists nor resolves; for `SupportAnalyst`, an opaque analyst
        identifier used purely for read authorization; and for `Reader`, an
        opaque anonymous reader identifier that is likewise never resolved to a
        record."

        PRD §3.7: "Either a `DocsLead` or a `Writer` may submit one against a
        `release_train_id`, supplying an `internal_summary` of 1 to 300
        characters copied from the change-management system, a `severity` of
        `BREAKING`, `SECURITY`, `MAJOR`, `MINOR`, or `PATCH`, a `category` of
        `FEATURE`, `FIX`, `PERFORMANCE`, `SECURITY_PATCH`, or `DEPRECATION`, and
        an `affected_component` key of 1 to 60 characters."

        Design: Corner/rbac/reader_and_coordinator_and_analyst_cannot_cross_role_boundaries_unauthorized
        """
        set_clock(CLOCK)
        train = create_release_train()

        response = api.create_change_record(
            create_change_record_payload(
                train["id"], internal_summary="Analyst-submitted change", category="FIX"
            ),
            support_analyst_headers,
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED, 403)

        _, meta = validate_list(api.list_change_records(docs_lead_headers))
        assert meta["total_count"] == 0

    def test_a_docs_lead_cannot_enter_the_localization_pipeline(self, api, docs_lead_headers):
        """The DocsLead is not a superuser: queueing a translation belongs to the
        LocalizationCoordinator alone, and the locale's ledger stays untouched.

        PRD §3.8: "A manual **translation job** is queued by a
        `LocalizationCoordinator` against a `topic_id` and a
        `locale_profile_id` over a closed calendar window given by
        `window_start_date` and `window_end_date`."

        PRD §2.1: "Section 4 lists the authorized roles for every endpoint, and
        that list is exhaustive — a role absent from an endpoint's row has no
        access to it under any circumstances."

        Design: Corner/rbac/reader_and_coordinator_and_analyst_cannot_cross_role_boundaries_unauthorized
        """
        set_clock(CLOCK)
        bundle = feedback_context()

        response = api.create_localization_job(
            create_localization_job_payload(bundle["topic_id"], bundle["locale_id"]),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED, 403)

        locale = read_locale_profile(bundle["locale_id"])
        assert locale["open_job_count"] == 0
        assert locale["committed_source_words"] == 0


class TestIdentityHeadersAreCheckedFirst:
    """Three distinct failure modes of the identity headers, each reported at its
    own band of the precedence order."""

    @pytest.mark.parametrize(
        "headers",
        [
            make_headers_missing_user_id(),
            make_headers_missing_role(),
            make_headers_empty_user_id(),
            make_headers_empty_role(),
        ],
        ids=["no-user-id", "no-role", "blank-user-id", "blank-role"],
    )
    def test_an_absent_or_blank_identity_header_is_unauthenticated(self, api, headers):
        """Absence and the empty string are treated identically on both headers.

        PRD §2.1: "If either header is absent, or is present but sent as an empty
        string, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a
        header consisting only of whitespace is treated as a value, not as
        absence, and will fail later checks instead."

        PRD §2.5: "**Authentication.** Both headers present and non-empty —
        otherwise `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_x_user_id_header_returns_unauthenticated_before_any_other_check
        """
        set_clock(CLOCK)

        response = api.list_release_trains(headers)
        validate_error(response, ApiErrorId.UNAUTHENTICATED, 401)

    def test_a_blank_user_id_is_reported_before_a_role_the_endpoint_does_not_admit(
        self, api, docs_lead_headers
    ):
        """A call that is unauthenticated, unauthorised and malformed all at once
        still reports the authentication failure.

        PRD §2.5: "Checks are evaluated in the following order, and the first
        check that fails determines the response; no later check is evaluated
        once an earlier one has failed."

        PRD §2.1: "If either header is absent, or is present but sent as an empty
        string, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a
        header consisting only of whitespace is treated as a value, not as
        absence, and will fail later checks instead."

        Design: Corner/rbac/missing_x_user_id_header_returns_unauthenticated_before_any_other_check
        """
        set_clock(CLOCK)

        response = api.create_plan_item(
            {"feature_key": "feature-broken"}, make_headers_empty_user_id("Writer")
        )
        validate_error(response, ApiErrorId.UNAUTHENTICATED, 401)

        _, meta = validate_list(api.list_plan_items(docs_lead_headers))
        assert meta["total_count"] == 0

    def test_an_unresolvable_writer_identity_is_a_role_identity_mismatch(
        self, api, docs_lead_headers, writer_headers_for
    ):
        """A well-formed but unknown writer id fails identity resolution rather than
        an ownership check that would presuppose a real writer.

        PRD §2.1: "For both of these roles, an `X-User-ID` that does not resolve
        to an existing record of the matching type is rejected with
        `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403) before any resource-specific
        logic runs."

        PRD §2.5: "**Role identity.** For endpoints whose authorized roles
        include `Writer` or `Reviewer`, the presented `X-User-ID` resolves to an
        existing record of that type — otherwise `ERR_ROLE_IDENTITY_MISMATCH`."

        Design: Corner/rbac/missing_x_user_id_header_returns_unauthenticated_before_any_other_check
        """
        set_clock(CLOCK)
        bundle = assigned_plan_item_context()

        response = api.create_topic(
            create_topic_payload(bundle["plan_item_id"], slug="atlas-unknown-identity"),
            writer_headers_for(UNRESOLVABLE_ENTITY_USER_ID),
        )
        validate_error(response, ApiErrorId.ROLE_IDENTITY_MISMATCH, 403)

        accepted = validate_success(
            api.create_topic(
                create_topic_payload(bundle["plan_item_id"], slug="atlas-feature-a"),
                writer_headers_for(bundle["writer_id"]),
            ),
            201,
        )
        assert accepted["slug"] == "atlas-feature-a"

        _, meta = validate_list(
            api.list_topics(docs_lead_headers, params={"plan_item_id": bundle["plan_item_id"]})
        )
        assert meta["total_count"] == 1


class TestEveryResourceReportsItsOwnNotFound:
    """A 404 names the family of the thing that was missing, and a body reference is
    reported separately from the path resource that carried it."""

    @pytest.mark.parametrize(
        ("reader_method", "expected_error"),
        [
            ("get_release_train", ApiErrorId.RELEASE_TRAIN_NOT_FOUND),
            ("get_writer", ApiErrorId.WRITER_NOT_FOUND),
            ("get_reviewer", ApiErrorId.REVIEWER_NOT_FOUND),
            ("get_signoff", ApiErrorId.SIGNOFF_NOT_FOUND),
            ("get_doc_set_version", ApiErrorId.DOC_SET_VERSION_NOT_FOUND),
            ("get_change_record", ApiErrorId.CHANGE_RECORD_NOT_FOUND),
            ("get_release_note", ApiErrorId.RELEASE_NOTE_NOT_FOUND),
            ("get_locale_profile", ApiErrorId.LOCALE_PROFILE_NOT_FOUND),
            ("get_localization_job", ApiErrorId.LOCALIZATION_JOB_NOT_FOUND),
            ("get_terminology_term", ApiErrorId.TERM_NOT_FOUND),
            ("get_deprecation_notice", ApiErrorId.DEPRECATION_NOTICE_NOT_FOUND),
        ],
    )
    def test_an_unknown_identifier_in_the_path_reports_its_own_resource_family(
        self, api, docs_lead_headers, reader_method, expected_error
    ):
        """Eleven resource families, eleven distinct 404 codes, one shared envelope.

        PRD §2.5: "A missing resource yields the 404 belonging to that resource's
        type: `ERR_RELEASE_TRAIN_NOT_FOUND`, `ERR_WRITER_NOT_FOUND`,
        `ERR_REVIEWER_NOT_FOUND`, `ERR_PLAN_ITEM_NOT_FOUND`,
        `ERR_TOPIC_NOT_FOUND`, `ERR_SIGNOFF_NOT_FOUND`,
        `ERR_DOC_SET_VERSION_NOT_FOUND`, `ERR_CHANGE_RECORD_NOT_FOUND`,
        `ERR_RELEASE_NOTE_NOT_FOUND`, `ERR_LOCALE_PROFILE_NOT_FOUND`,
        `ERR_LOCALIZATION_JOB_NOT_FOUND`, `ERR_TERM_NOT_FOUND`, or
        `ERR_DEPRECATION_NOTICE_NOT_FOUND`."

        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/every_addressable_resource_reports_its_own_not_found_id
        """
        set_clock(CLOCK)

        response = getattr(api, reader_method)(NON_EXISTENT_UUID, docs_lead_headers)
        validate_error(response, expected_error, 404)

        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["data"]) == {"error_id", "message"}
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
        assert body["meta"]["api_request_id"].startswith("req_")

    def test_an_unknown_information_architecture_parent_reports_the_parent_topic(
        self, api, docs_lead_headers, writer_headers_for
    ):
        """The addressed plan item exists, so the missing body reference is what is
        reported, and under its own code rather than the topic one.

        PRD §2.5: "**Body reference existence.** Every reference supplied in a
        request body resolves to a live record, reported with the same family of
        404 codes: `writer_id`, `reviewer_id`, `release_train_id`,
        `plan_item_id`, `parent_topic_id` (reported as
        `ERR_PARENT_TOPIC_NOT_FOUND`), `locale_profile_id`, `topic_id`, and
        `migration_guide_topic_id` (reported as `ERR_TOPIC_NOT_FOUND`)."

        Design: Corner/errors/every_addressable_resource_reports_its_own_not_found_id
        """
        set_clock(CLOCK)
        bundle = assigned_plan_item_context()

        response = api.create_topic(
            create_topic_payload(
                bundle["plan_item_id"],
                slug="atlas-orphan-child",
                parent_topic_id=NON_EXISTENT_UUID,
            ),
            writer_headers_for(bundle["writer_id"]),
        )
        validate_error(response, ApiErrorId.PARENT_TOPIC_NOT_FOUND, 404)

        rows, meta = validate_list(
            api.list_topics(docs_lead_headers, params={"plan_item_id": bundle["plan_item_id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert read_plan_item(bundle["plan_item_id"])["status"] == "ASSIGNED"


class TestRequestLevelRejections:
    """Three well-formed-but-invalid inputs that must stay distinct from one another
    and from a plain shape violation."""

    def test_moving_the_logical_clock_backwards_is_refused(self, api, docs_lead_headers):
        """A backwards instant is a state conflict, and the clock does not budge.

        PRD §2.4: "The clock only moves forward: a requested `current_utc`
        earlier than the clock's present value is rejected with
        `ERR_CLOCK_BACKWARD` (HTTP 409), while a value equal to the present value
        is accepted and is a no-op."

        Design: Corner/errors/request_level_input_rejections_for_clock_pagination_and_windows
        """
        set_clock(CLOCK)
        train = create_release_train()

        response = api.set_clock(
            create_clock_payload("2026-07-31T23:59:59Z"), docs_lead_headers
        )
        validate_error(response, ApiErrorId.CLOCK_BACKWARD, 409)

        assert instants_equal(read_release_train(train["id"])["created_at"], CLOCK)
        later = validate_success(
            api.create_release_train(create_release_train_payload(), docs_lead_headers), 201
        )
        assert instants_equal(later["created_at"], CLOCK)

    @pytest.mark.parametrize(
        "params",
        [{"limit": 0}, {"limit": 101}, {"offset": -1}],
        ids=["limit-below-minimum", "limit-above-maximum", "negative-offset"],
    )
    def test_a_page_window_outside_its_declared_bounds_is_a_pagination_rejection(
        self, api, docs_lead_headers, params
    ):
        """The three out-of-range paging values report the pagination error, not the
        generic shape error.

        PRD §2.3: "A `limit` outside the range 1 through 100, an `offset` below
        0, or a non-integer value for either is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)."

        PRD §2.3: "Collection endpoints accept two optional query parameters."

        Design: Corner/errors/request_level_input_rejections_for_clock_pagination_and_windows
        """
        set_clock(CLOCK)
        create_release_train()

        response = api.list_release_trains(docs_lead_headers, params=params)
        validate_error(response, ApiErrorId.INVALID_PAGINATION, 400)
        assert response.json()["data"]["error_id"] != ApiErrorId.INVALID_REQUEST.value

    def test_a_release_whose_freeze_date_follows_its_availability_date_is_refused(
        self, api, docs_lead_headers
    ):
        """Three well-formed dates in the wrong order are a date-window rejection.

        PRD §2.10: "Any misordered window or timeline is rejected with
        `ERR_INVALID_DATE_WINDOW` (HTTP 400): an authoring window whose end is
        not strictly after its start, a translation window whose end is earlier
        than its start, a deprecation timeline whose announce date is later than
        its deprecated date or whose deprecated date is not strictly earlier than
        its removal date, and a release train whose documentation freeze date is
        later than its general-availability date or whose general-availability
        date is later than its end-of-support date."

        Design: Corner/errors/request_level_input_rejections_for_clock_pagination_and_windows
        """
        set_clock(CLOCK)
        create_release_train(product_key="ATLAS", version_label="12.0")

        response = api.create_release_train(
            create_release_train_payload(
                product_key="ATLAS",
                version_label="13.0",
                doc_freeze_date="2026-09-20",
                ga_date="2026-09-01",
                support_end_date="2027-09-01",
            ),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.INVALID_DATE_WINDOW, 400)

        _, meta = validate_list(api.list_release_trains(docs_lead_headers))
        assert meta["total_count"] == 1


class TestUniquenessKeysHonourTheirScope:
    """Five natural keys, five different scopes: a collision inside the scope is
    refused while the same spelling outside the scope is free to be reused."""

    def test_a_version_label_may_repeat_across_product_lines_but_not_within_one(
        self, api, docs_lead_headers
    ):
        """The key is the pair, so ATLAS 12.0 blocks only a second ATLAS 12.0.

        PRD §3.1: "The pair of product line and version label must be unique
        across all release trains; a collision is rejected with
        `ERR_DUPLICATE_VERSION_LABEL`."

        Design: Corner/errors/uniqueness_rejections_across_all_five_scoped_keys
        """
        set_clock(CLOCK)
        create_release_train(product_key="ATLAS", version_label="12.0")

        response = api.create_release_train(
            create_release_train_payload(product_key="ATLAS", version_label="12.0"),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.DUPLICATE_VERSION_LABEL, 409)

        other_line = validate_success(
            api.create_release_train(
                create_release_train_payload(product_key="NIMBUS", version_label="12.0"),
                docs_lead_headers,
            ),
            201,
        )
        assert other_line["version_label"] == "12.0"
        assert other_line["product_key"] == "NIMBUS"

        _, meta = validate_list(api.list_release_trains(docs_lead_headers))
        assert meta["total_count"] == 2

    def test_a_person_key_is_unique_per_roster_and_is_shared_vocabulary_between_them(
        self, api, docs_lead_headers
    ):
        """A second writer cannot take the key, but a reviewer deliberately may.

        PRD §3.2: "A `DocsLead` registers a technical writer with a `person_key`
        — 3 to 40 characters, unique across the writer roster — a `full_name` of
        1 to 120 characters, a `seniority_tier` of `ASSOCIATE`, `SENIOR`, or
        `PRINCIPAL`, and `capacity_points`, a positive decimal number carried to
        one decimal place expressing how much concurrent work the writer may
        hold."

        PRD §3.2: "A duplicate `person_key` is rejected with
        `ERR_DUPLICATE_PERSON_KEY`."

        PRD §3.2: "`person_key` is deliberately shared vocabulary between the
        writer roster and the reviewer roster, and it is the mechanism behind the
        self-review prohibition described in §3.5."

        Design: Corner/errors/uniqueness_rejections_across_all_five_scoped_keys
        """
        set_clock(CLOCK)
        create_writer(person_key="w-anna")

        response = api.create_writer(
            create_writer_payload(person_key="w-anna", full_name="Anna Impostor"),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.DUPLICATE_PERSON_KEY, 409)

        reviewer = validate_success(
            api.create_reviewer(
                create_reviewer_payload(person_key="w-anna", discipline="ENGINEERING"),
                docs_lead_headers,
            ),
            201,
        )
        assert reviewer["person_key"] == "w-anna"
        assert reviewer["open_signoff_count"] == 0

        _, meta = validate_list(api.list_writers(docs_lead_headers))
        assert meta["total_count"] == 1

    def test_a_page_slug_is_unique_across_the_whole_train_not_merely_its_deliverable(
        self, api, docs_lead_headers, writer_headers_for
    ):
        """A second deliverable on the same train cannot reuse a sibling's slug.

        PRD §3.3: "The slug must be unique among all topics belonging to the same
        release train, not merely within the plan item, and a collision returns
        `ERR_DUPLICATE_TOPIC_SLUG`."

        Design: Corner/errors/uniqueness_rejections_across_all_five_scoped_keys
        """
        set_clock(CLOCK)
        bundle = topic_context(slug="atlas-shared-page")
        assert bundle["topic"]["slug"] == "atlas-shared-page"

        second_item = validate_success(
            api.create_plan_item(create_plan_item_payload(bundle["train_id"]), docs_lead_headers),
            201,
        )
        validate_success(
            api.assign_plan_item(
                second_item["id"],
                assign_plan_item_payload(
                    bundle["writer_id"],
                    window_start_date="2026-08-11",
                    window_end_date="2026-08-17",
                ),
                docs_lead_headers,
            )
        )

        response = api.create_topic(
            create_topic_payload(second_item["id"], slug="atlas-shared-page"),
            writer_headers_for(bundle["writer_id"]),
        )
        validate_error(response, ApiErrorId.DUPLICATE_TOPIC_SLUG, 409)

        _, meta = validate_list(
            api.list_topics(docs_lead_headers, params={"plan_item_id": second_item["id"]})
        )
        assert meta["total_count"] == 0
        assert read_plan_item(second_item["id"])["status"] == "ASSIGNED"

    def test_a_locale_code_is_unique_across_every_registered_locale(
        self, api, localization_coordinator_headers, docs_lead_headers
    ):
        """The locale code is global, so the second registration of fr-FR fails.

        PRD §3.8: "A `LocalizationCoordinator` registers each target language as
        a **locale profile**, supplying a `locale_code` of exactly 5 characters
        in the BCP-47 pattern of a lowercase two-letter language, a hyphen, and
        an uppercase two-letter region — unique across all locale profiles, with
        a collision refused as `ERR_DUPLICATE_LOCALE_CODE`."

        Design: Corner/errors/uniqueness_rejections_across_all_five_scoped_keys
        """
        set_clock(CLOCK)
        first = create_locale_profile(locale_code="fr-FR")

        response = api.create_locale_profile(
            create_locale_profile_payload(locale_code="fr-FR", sla_days=30),
            localization_coordinator_headers,
        )
        validate_error(response, ApiErrorId.DUPLICATE_LOCALE_CODE, 409)

        unchanged = read_locale_profile(first["id"])
        assert unchanged["sla_days"] == first["sla_days"]
        assert unchanged["open_job_count"] == 0

        _, meta = validate_list(api.list_locale_profiles(docs_lead_headers))
        assert meta["total_count"] == 1

    def test_a_style_guide_term_is_unique_only_among_the_terms_still_active(
        self, api, docs_lead_headers
    ):
        """The active-only scope is what makes the duplicate refusal meaningful.

        PRD §3.4: "A duplicate `term` among active terms is rejected with
        `ERR_DUPLICATE_TERM`; because the uniqueness test looks only at active
        terms, a retired term's spelling may be reused."

        Design: Corner/errors/uniqueness_rejections_across_all_five_scoped_keys
        """
        set_clock(CLOCK)
        first = create_terminology_term(term="sign-in", enforcement_severity="BLOCKER")
        assert first["status"] == "ACTIVE"
        assert first["retired_at"] is None

        response = api.create_terminology_term(
            create_terminology_term_payload(term="sign-in", enforcement_severity="WARNING"),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.DUPLICATE_TERM, 409)

        _, meta = validate_list(
            api.list_terminology_terms(docs_lead_headers, params={"status": "ACTIVE"})
        )
        assert meta["total_count"] == 1
