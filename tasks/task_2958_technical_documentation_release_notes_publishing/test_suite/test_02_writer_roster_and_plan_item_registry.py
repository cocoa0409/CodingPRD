"""The writer roster and the documentation plan-item registry.

Before any documentation can be written the shop has to know who its writers
are and what deliverables it owes.  This module covers the two registries that
answer those questions: what a writer's record looks like the moment it is
created and read back, which fields the server refuses to take dictation on,
and what a plan item looks like at rest — the required inputs, the enum sets,
the opening state, and the paged view of a train's backlog.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_pagination_meta,
    assert_plan_item,
    assert_response_envelope,
    assert_versioned_audit_fields,
    assert_writer,
    create_plan_item,
    create_plan_item_payload,
    create_release_train,
    create_writer_payload,
    is_valid_uuid,
    read_plan_item,
    read_release_train,
    set_clock,
    validate_error,
    validate_list,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"


class TestWriterRoster:
    """What a writer's record holds the moment it is registered, and which of
    its fields the server declines to take from the caller."""

    def test_writer_read_back_carries_the_stored_roster_fields_and_a_zero_ledger(
        self, api, docs_lead_headers
    ):
        """A brand-new writer reads back with both ledger fields at zero.

        PRD §3.2: "A `DocsLead` registers a technical writer with a `person_key`
        — 3 to 40 characters, unique across the writer roster — a `full_name` of
        1 to 120 characters, a `seniority_tier` of `ASSOCIATE`, `SENIOR`, or
        `PRINCIPAL`, and `capacity_points`, a positive decimal number carried to
        one decimal place expressing how much concurrent work the writer may
        hold."

        PRD §3.2: "New writers open with `committed_load_points` of `0.00` and
        `assignment_count` of 0."

        Design: Corner/entities/writer_retrieval_returns_stored_and_computed_fields
        """
        set_clock(CLOCK)
        payload = create_writer_payload(
            person_key="w-anna",
            full_name="Anna Reyes",
            seniority_tier="SENIOR",
            capacity_points=40.0,
        )
        created = validate_success(api.create_writer(payload, docs_lead_headers), 201)

        response = api.get_writer(created["id"], docs_lead_headers)
        data = validate_success(response)

        assert_response_envelope(response, "object")
        assert_writer(data)
        assert is_valid_uuid(data["id"])
        assert data["person_key"] == "w-anna"
        assert data["full_name"] == "Anna Reyes"
        assert data["seniority_tier"] == "SENIOR"
        assert data["capacity_points"] == pytest.approx(40.0, abs=0.01)
        assert data["status"] == "ACTIVE"
        assert data["committed_load_points"] == pytest.approx(0.00, abs=0.01)
        assert data["assignment_count"] == 0
        assert_versioned_audit_fields(data, expected_version=1)

    def test_writer_status_defaults_to_active_when_the_optional_field_is_omitted(
        self, api, docs_lead_headers
    ):
        """An omitted status stores ACTIVE, so the writer is immediately assignable.

        PRD §3.2: "An optional `status` may be supplied as either `ACTIVE` or
        `ON_LEAVE` and defaults to `ACTIVE`."

        PRD §3.2: "The roster can be listed and filtered by `status` and by
        `seniority_tier`, and every writer's own source revisions across all
        topics can be listed on their behalf, ordered by `created_at` ascending
        — one of only two ways to discover revisions, since a revision is never
        returned by any create response other than its own."

        Design: Corner/entities/writer_status_defaults_to_active_when_omitted
        """
        set_clock(CLOCK)
        payload = create_writer_payload(
            person_key="w-anna",
            full_name="Anna Reyes",
            seniority_tier="SENIOR",
            capacity_points=40.0,
        )
        assert "status" not in payload

        created = validate_success(api.create_writer(payload, docs_lead_headers), 201)
        assert created["status"] == "ACTIVE"
        assert created["status"] is not None

        active_rows, active_meta = validate_list(
            api.list_writers(docs_lead_headers, params={"status": "ACTIVE"})
        )
        assert active_meta["total_count"] == 1
        assert [row["id"] for row in active_rows] == [created["id"]]

        _, on_leave_meta = validate_list(
            api.list_writers(docs_lead_headers, params={"status": "ON_LEAVE"})
        )
        assert on_leave_meta["total_count"] == 0

    def test_ledger_figures_supplied_at_registration_are_ignored(self, api, docs_lead_headers):
        """committed_load_points and assignment_count are derived, never dictated.

        PRD §3.2: "New writers open with `committed_load_points` of `0.00` and
        `assignment_count` of 0."

        PRD §3.2: "A writer's `committed_load_points` is the sum of
        `load_points` over the plan items assigned to them whose status is
        `ASSIGNED`, `IN_AUTHORING`, `IN_REVIEW`, `IN_REVISION`, or
        `APPROVED_CONTENT`, rounded half up to two decimal places, and
        `assignment_count` is the number of items in that same set."

        Design: Corner/entities/writer_committed_load_points_input_ignored
        """
        set_clock(CLOCK)
        payload = create_writer_payload(
            person_key="w-anna",
            full_name="Anna Reyes",
            seniority_tier="SENIOR",
            capacity_points=40.0,
            committed_load_points=99.0,
            assignment_count=5,
        )

        created = validate_success(api.create_writer(payload, docs_lead_headers), 201)

        assert created["committed_load_points"] == pytest.approx(0.00, abs=0.01)
        assert created["assignment_count"] == 0
        assert created["capacity_points"] == pytest.approx(40.0, abs=0.01)

        read_back = validate_success(api.get_writer(created["id"], docs_lead_headers))
        assert read_back["committed_load_points"] == pytest.approx(0.00, abs=0.01)
        assert read_back["assignment_count"] == 0


class TestPlanItemRegistrationInputs:
    """The registry refuses a malformed deliverable before it books anything
    against the train's backlog."""

    def test_deliverable_without_a_feature_key_is_refused_and_books_nothing(
        self, api, docs_lead_headers
    ):
        """A missing required field is a shape violation, not a stored row.

        PRD §3.2: "A `DocsLead` creates it against a `release_train_id` with a
        `feature_key` of 1 to 60 characters that must be unique within that
        train, an `ia_placement` of `NEW_TOPIC`, `EXISTING_TOPIC_UPDATE`, or
        `CONCEPT_HUB` recording the information-architecture decision, an
        `audience_tier` of `CRITICAL`, `STANDARD`, or `INTERNAL`, a
        `planned_page_count` between 1 and 500 inclusive, and
        `complexity_points` between 0 and 100 inclusive as the estimator's
        judgement of difficulty."

        PRD §2.5: "**Request shape.** On every write endpoint: all required
        fields present, JSON types correct, enum values drawn from their declared
        sets, integer counts non-negative where declared, a rating between 1 and
        5 inclusive, money supplied as integer counts of cents rather than
        strings, calendar dates formatted `YYYY-MM-DD`, and instants formatted
        as ISO 8601 UTC with a trailing `Z` — otherwise `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/plan_item_create_missing_required_feature_key_rejected
        """
        set_clock(CLOCK)
        train = create_release_train(
            product_key="ATLAS",
            version_label="12.0",
            doc_freeze_date="2026-08-20",
            ga_date="2026-09-01",
            support_end_date="2027-09-01",
            localization_budget_cap_cents=5000000,
        )
        payload = create_plan_item_payload(
            train["id"],
            ia_placement="NEW_TOPIC",
            audience_tier="STANDARD",
            planned_page_count=6,
            complexity_points=10,
        )
        del payload["feature_key"]

        response = api.create_plan_item(payload, docs_lead_headers)
        validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

        _, meta = validate_list(
            api.list_plan_items(docs_lead_headers, params={"release_train_id": train["id"]})
        )
        assert meta["total_count"] == 0
        assert read_release_train(train["id"])["plan_item_count"] == 0

    def test_deliverable_with_an_unrecognised_audience_tier_is_refused(
        self, api, docs_lead_headers
    ):
        """audience_tier admits three symbols, and EXECUTIVE is not one of them.

        PRD §3.2: "A `DocsLead` creates it against a `release_train_id` with a
        `feature_key` of 1 to 60 characters that must be unique within that
        train, an `ia_placement` of `NEW_TOPIC`, `EXISTING_TOPIC_UPDATE`, or
        `CONCEPT_HUB` recording the information-architecture decision, an
        `audience_tier` of `CRITICAL`, `STANDARD`, or `INTERNAL`, a
        `planned_page_count` between 1 and 500 inclusive, and
        `complexity_points` between 0 and 100 inclusive as the estimator's
        judgement of difficulty."

        PRD §2.5: "**Request shape.** On every write endpoint: all required
        fields present, JSON types correct, enum values drawn from their declared
        sets, integer counts non-negative where declared, a rating between 1 and
        5 inclusive, money supplied as integer counts of cents rather than
        strings, calendar dates formatted `YYYY-MM-DD`, and instants formatted
        as ISO 8601 UTC with a trailing `Z` — otherwise `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/plan_item_create_with_invalid_audience_tier_enum_rejected
        """
        set_clock(CLOCK)
        train = create_release_train(
            product_key="ATLAS",
            version_label="12.0",
            doc_freeze_date="2026-08-20",
            ga_date="2026-09-01",
            support_end_date="2027-09-01",
            localization_budget_cap_cents=5000000,
        )

        response = api.create_plan_item(
            create_plan_item_payload(
                train["id"],
                feature_key="feature-a",
                ia_placement="NEW_TOPIC",
                audience_tier="EXECUTIVE",
                planned_page_count=6,
                complexity_points=10,
            ),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

        assert read_release_train(train["id"])["plan_item_count"] == 0
        _, meta = validate_list(
            api.list_plan_items(docs_lead_headers, params={"release_train_id": train["id"]})
        )
        assert meta["total_count"] == 0


class TestPlanItemOpeningState:
    """A deliverable at rest: DRAFTED, unassigned, and already counted against
    its train's readiness figures."""

    def test_a_new_deliverable_opens_drafted_with_no_assignment_data(
        self, api, docs_lead_headers
    ):
        """Assignment data appears only once the assign transition runs.

        PRD §3.2: "A new plan item opens with `status` `DRAFTED`, `load_points`
        of `0.00`, and `rework_count` of 0, and its creation increments the
        train's `plan_item_count` and triggers a readiness recomputation."

        PRD §3.2: "Assigning a deliverable to a writer is what turns planning
        into work, and it moves the item from `DRAFTED` to `ASSIGNED`."

        Design: Corner/state_machines/plan_item_initial_state_is_drafted
        """
        set_clock(CLOCK)
        train = create_release_train(
            product_key="ATLAS",
            version_label="12.0",
            doc_freeze_date="2026-08-20",
            ga_date="2026-09-01",
            support_end_date="2027-09-01",
            localization_budget_cap_cents=5000000,
        )

        response = api.create_plan_item(
            create_plan_item_payload(
                train["id"],
                feature_key="feature-a",
                ia_placement="NEW_TOPIC",
                audience_tier="STANDARD",
                planned_page_count=6,
                complexity_points=10,
            ),
            docs_lead_headers,
        )
        data = validate_success(response, 201)

        assert_plan_item(data)
        assert data["status"] == "DRAFTED"
        assert data["assigned_writer_id"] is None
        assert data["window_start_date"] is None
        assert data["window_end_date"] is None
        assert data["load_points"] == pytest.approx(0.00, abs=0.01)
        assert data["rework_count"] == 0
        assert data["cancel_reason"] is None
        assert_versioned_audit_fields(data, expected_version=1)

        read_back = read_plan_item(data["id"])
        assert read_back["status"] == "DRAFTED"
        assert read_back["load_points"] == pytest.approx(0.00, abs=0.01)
        assert read_back["rework_count"] == 0

    def test_the_first_deliverable_drags_the_ratio_to_zero_while_planning_stays_open(
        self, api, docs_lead_headers
    ):
        """One DRAFTED item makes the ratio 0.00, yet a PLANNED train stays OPEN.

        PRD §3.2: "A new plan item opens with `status` `DRAFTED`, `load_points`
        of `0.00`, and `rework_count` of 0, and its creation increments the
        train's `plan_item_count` and triggers a readiness recomputation."

        PRD §3.1: "Third, `approved_topic_ratio` is `1.00` when `plan_item_count`
        is zero — a train with no counted deliverables is vacuously ready, not
        zero and not null — and otherwise the approved count divided by the total
        count, rounded half up to two decimal places."

        PRD §3.1: "Fourth, `doc_readiness_posture` is decided as follows: if the
        train's status is `MAINTENANCE` or `END_OF_LIFE` the posture is `FROZEN`,
        and this test short-circuits before the ratio is consulted at all;
        otherwise, if the status is `PLANNED` the posture is `OPEN`, because
        planning is always open; otherwise — that is, for `DOC_FREEZE` and `GA`,
        the ratio-driven band — the posture is `OPEN` when the ratio is at least
        0.80, `RESTRICTED` when it is at least 0.50 but below 0.80, and `FROZEN`
        when it is below 0.50."

        Design: Corner/state_machines/plan_item_initial_state_is_drafted
        """
        set_clock(CLOCK)
        train = create_release_train(
            product_key="ATLAS",
            version_label="12.0",
            doc_freeze_date="2026-08-20",
            ga_date="2026-09-01",
            support_end_date="2027-09-01",
            localization_budget_cap_cents=5000000,
        )
        assert train["plan_item_count"] == 0
        assert train["approved_topic_ratio"] == pytest.approx(1.00, abs=0.01)

        create_plan_item(
            train["id"],
            feature_key="feature-a",
            ia_placement="NEW_TOPIC",
            audience_tier="STANDARD",
            planned_page_count=6,
            complexity_points=10,
        )

        read_back = validate_success(api.get_release_train(train["id"], docs_lead_headers))
        assert read_back["plan_item_count"] == 1
        assert read_back["approved_plan_item_count"] == 0
        assert read_back["approved_topic_ratio"] == pytest.approx(0.00, abs=0.01)
        assert read_back["status"] == "PLANNED"
        assert read_back["doc_readiness_posture"] == "OPEN"


class TestPlanItemBacklogListing:
    """The train's backlog is a paged collection, and the page metadata has to
    describe the whole filtered set rather than the page in hand."""

    def test_backlog_pages_report_the_filtered_total_and_the_remainder_flag(
        self, api, docs_lead_headers
    ):
        """Three deliverables read two at a time: total 3, then has_more false.

        PRD §3.2: "Plan items can be listed and filtered by `release_train_id`,
        `assigned_writer_id`, `status`, and `audience_tier`, and read
        individually with their computed `load_points` and `rework_count` on
        display."

        PRD §2.3: "Every paginated response carries `limit`, `offset`,
        `total_count`, and `has_more` in its `meta` block."

        PRD §2.3: "`total_count` is the number of records matching the request's
        filters before pagination is applied, and `has_more` is true exactly when
        records matching the filters remain beyond the returned page."

        Design: Corner/entities/plan_item_listing_reports_total_count_and_has_more
        """
        set_clock(CLOCK)
        train = create_release_train(
            product_key="ATLAS",
            version_label="12.0",
            doc_freeze_date="2026-08-20",
            ga_date="2026-09-01",
            support_end_date="2027-09-01",
            localization_budget_cap_cents=5000000,
        )
        item_a = create_plan_item(
            train["id"],
            feature_key="feature-a",
            ia_placement="NEW_TOPIC",
            audience_tier="STANDARD",
            planned_page_count=6,
            complexity_points=10,
        )
        item_b = create_plan_item(
            train["id"],
            feature_key="feature-b",
            ia_placement="EXISTING_TOPIC_UPDATE",
            audience_tier="INTERNAL",
            planned_page_count=2,
            complexity_points=4,
        )
        item_c = create_plan_item(
            train["id"],
            feature_key="feature-c",
            ia_placement="CONCEPT_HUB",
            audience_tier="CRITICAL",
            planned_page_count=4,
            complexity_points=25,
        )

        first_response = api.list_plan_items(
            docs_lead_headers,
            params={"release_train_id": train["id"], "limit": 2, "offset": 0},
        )
        first_rows, first_meta = validate_list(first_response)
        assert_response_envelope(first_response, "array")
        assert len(first_rows) == 2
        assert_pagination_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)

        second_rows, second_meta = validate_list(
            api.list_plan_items(
                docs_lead_headers,
                params={"release_train_id": train["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(second_rows) == 1
        assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)

        paged_ids = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
        assert len(paged_ids) == len(set(paged_ids)), "a row was repeated across the two pages"
        assert set(paged_ids) == {item_a["id"], item_b["id"], item_c["id"]}
        assert read_release_train(train["id"])["plan_item_count"] == 3
