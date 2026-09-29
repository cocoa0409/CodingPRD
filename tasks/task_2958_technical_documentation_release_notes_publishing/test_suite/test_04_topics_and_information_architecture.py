"""Topics, the information-architecture tree, and append-only source revisions.

A topic is one documentation page, and pages are arranged into a shallow tree
whose shape the server polices: a parent must belong to the same deliverable,
and the tree may not run deeper than four levels below its root.  Content
arrives as immutable source revisions that are never edited, only appended, and
which can be discovered either through their topic or through the writer who
authored them.  This module covers all three of those concerns.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_append_only_audit_fields,
    assert_committed_load_points,
    assert_created_at_ascending,
    assert_error_envelope,
    assert_ids_in_order,
    assert_instant_format,
    assert_new_topic_defaults,
    assert_pagination_meta,
    assert_source_revision,
    assert_topic,
    assert_versioned_audit_fields,
    assign_plan_item,
    create_plan_item,
    create_revision,
    create_topic,
    create_topic_payload,
    create_writer,
    instants_equal,
    is_valid_uuid,
    plan_item_context,
    read_plan_item,
    read_topic,
    read_writer,
    set_clock,
    validate_error,
    validate_list,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"

#: A release train whose planning window stays open for every window used below.
TRAIN = {
    "product_key": "ATLAS",
    "doc_freeze_date": "2026-08-20",
    "ga_date": "2026-09-01",
    "support_end_date": "2027-09-01",
    "localization_budget_cap_cents": 5000000,
}

#: 6 planned pages, 10 complexity points, a new topic for a STANDARD audience.
STANDARD_ITEM = {
    "ia_placement": "NEW_TOPIC",
    "audience_tier": "STANDARD",
    "planned_page_count": 6,
    "complexity_points": 10,
}

#: A small internal update: 2 planned pages, 4 complexity points.
INTERNAL_ITEM = {
    "ia_placement": "EXISTING_TOPIC_UPDATE",
    "audience_tier": "INTERNAL",
    "planned_page_count": 2,
    "complexity_points": 4,
}

WRITER = {"seniority_tier": "SENIOR", "capacity_points": 40.0}


class TestTopicAddressing:
    """A page that does not exist, and a deliverable that does not exist, each
    report their own 404 rather than an empty success."""

    def test_reading_an_unknown_page_reports_the_topic_not_found_code(
        self, api, docs_lead_headers
    ):
        """A well-formed UUID naming no topic is a 404, not an empty 200.

        PRD §2.5: "**Path existence.** Every identifier embedded in the URL is
        resolved **left to right**, so that on a nested path the outer resource's
        absence is reported before the inner one is even looked for. A missing
        resource yields the 404 belonging to that resource's type:
        `ERR_RELEASE_TRAIN_NOT_FOUND`, `ERR_WRITER_NOT_FOUND`,
        `ERR_REVIEWER_NOT_FOUND`, `ERR_PLAN_ITEM_NOT_FOUND`,
        `ERR_TOPIC_NOT_FOUND`, `ERR_SIGNOFF_NOT_FOUND`,
        `ERR_DOC_SET_VERSION_NOT_FOUND`, `ERR_CHANGE_RECORD_NOT_FOUND`,
        `ERR_RELEASE_NOTE_NOT_FOUND`, `ERR_LOCALE_PROFILE_NOT_FOUND`,
        `ERR_LOCALIZATION_JOB_NOT_FOUND`, `ERR_TERM_NOT_FOUND`, or
        `ERR_DEPRECATION_NOTICE_NOT_FOUND`."

        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/topic_get_with_unknown_id_not_found
        """
        set_clock(CLOCK)

        response = api.get_topic(NON_EXISTENT_UUID, docs_lead_headers)

        validate_error(response, ApiErrorId.TOPIC_NOT_FOUND, 404)
        assert_error_envelope(response)
        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["data"].keys()) == {"error_id", "message"}
        assert isinstance(body["data"]["message"], str)

    def test_authoring_against_an_unknown_deliverable_reports_the_plan_item_code(
        self, api, docs_lead_headers, writer_headers_for
    ):
        """Body-reference existence is checked before writer ownership.

        PRD §2.5: "**Body reference existence.** Every reference supplied in a
        request body resolves to a live record, reported with the same family of
        404 codes: `writer_id`, `reviewer_id`, `release_train_id`, `plan_item_id`,
        `parent_topic_id` (reported as `ERR_PARENT_TOPIC_NOT_FOUND`),
        `locale_profile_id`, `topic_id`, and `migration_guide_topic_id` (reported
        as `ERR_TOPIC_NOT_FOUND`)."

        PRD §2.5: "**Writer ownership.** Where a `Writer` acts on a topic,
        `X-User-ID` equals the topic's plan item `assigned_writer_id` — otherwise
        `ERR_NOT_ASSIGNED_WRITER` (HTTP 403)."

        Design: Corner/entities/topic_create_with_unknown_plan_item_not_found
        """
        set_clock(CLOCK)
        writer = create_writer(person_key="w-anna", full_name="Anna Reyes", **WRITER)

        response = api.create_topic(
            create_topic_payload(
                NON_EXISTENT_UUID, slug="atlas-orphan-topic", title="Orphan topic"
            ),
            writer_headers_for(writer["id"]),
        )

        validate_error(response, ApiErrorId.PLAN_ITEM_NOT_FOUND, 404)
        assert (
            response.json()["data"]["error_id"] != ApiErrorId.NOT_ASSIGNED_WRITER.value
        ), "existence of the referenced deliverable precedes the ownership check"

        _, meta = validate_list(api.list_topics(docs_lead_headers))
        assert meta["total_count"] == 0


class TestTopicCreation:
    """What the server mints for a brand-new page, and what authoring the first
    page does to the deliverable that owns it."""

    def test_a_new_page_is_stamped_entirely_by_the_server(
        self, api, docs_lead_headers, writer_headers_for
    ):
        """Identity, audit fields, both state dimensions, and every counter.

        PRD §2.4: "Every resource is addressed by an `id` that the server mints as
        a UUID. Identifiers carry no type prefix and are never supplied by the
        client."

        PRD §3.3: "A newly created topic opens with `review_state`
        `NOT_SUBMITTED`, `publication_state` `UNPUBLISHED`,
        `current_revision_number` and `last_submitted_revision_number` both 0,
        `latest_body_word_count` 0, both violation counters 0, and `health_score`
        null — a page with no authored content has no health figure at all, and
        `health_score_variant` is likewise unset."

        PRD §3.3: "`ia_depth` is 0 for a root topic (no parent supplied) and
        otherwise one more than the parent's own `ia_depth`."

        Design: Corner/entities/topic_system_fields_are_server_generated
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides=dict(person_key="w-anna", full_name="Anna Reyes", **WRITER),
            feature_key="feature-a",
            **STANDARD_ITEM,
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-17",
        )

        response = api.create_topic(
            create_topic_payload(
                bundle["plan_item_id"], slug="atlas-feature-a", title="Feature A guide"
            ),
            writer_headers_for(bundle["writer_id"]),
        )
        topic = validate_success(response, 201)

        assert_topic(topic)
        assert is_valid_uuid(topic["id"])
        assert_versioned_audit_fields(topic, expected_version=1)
        assert_instant_format(topic["created_at"])
        assert instants_equal(topic["created_at"], CLOCK)
        assert instants_equal(topic["updated_at"], CLOCK)
        assert topic["ia_depth"] == 0
        assert topic["parent_topic_id"] is None
        assert_new_topic_defaults(topic)
        for field in (
            "submitted_at",
            "approved_at",
            "published_at",
            "published_in_doc_set_version_id",
            "signoff_latency_days",
            "health_score",
            "health_score_variant",
        ):
            assert topic[field] is None, f"{field} must be unset on a fresh page"

    def test_the_first_page_moves_its_deliverable_into_authoring(
        self, api, docs_lead_headers, writer_headers_for
    ):
        """Authoring begins as a side effect of the first page, not a separate call.

        PRD §3.3: "Creating the *first* topic under a plan item moves that item
        from `ASSIGNED` to `IN_AUTHORING`."

        Design: Corner/entities/topic_system_fields_are_server_generated
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides=dict(person_key="w-anna", full_name="Anna Reyes", **WRITER),
            feature_key="feature-a",
            **STANDARD_ITEM,
        )
        assigned = assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-17",
        )
        assert assigned["status"] == "ASSIGNED"

        validate_success(
            api.create_topic(
                create_topic_payload(
                    bundle["plan_item_id"], slug="atlas-feature-a", title="Feature A guide"
                ),
                writer_headers_for(bundle["writer_id"]),
            ),
            201,
        )

        assert read_plan_item(bundle["plan_item_id"])["status"] == "IN_AUTHORING"


class TestInformationArchitectureTree:
    """The parent edge is scoped to one deliverable and the tree is four levels
    deep below its root — no more, and no less."""

    def test_a_parent_under_a_different_deliverable_is_a_mismatch_not_a_depth_error(
        self, api, docs_lead_headers, writer_headers_for
    ):
        """The parent exists; it simply belongs to the wrong plan item.

        PRD §3.3: "When supplied, the parent must be a topic under the **same**
        plan item; a parent belonging to a different deliverable is rejected with
        `ERR_PARENT_TOPIC_MISMATCH`."

        PRD §3.3: "The referential check on which plan item the parent belongs to
        runs before the depth-and-cycle check, so a cross-item parent is reported
        as a mismatch rather than as a depth violation."

        Design: Corner/entities/topic_parent_under_a_different_plan_item_rejected
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides=dict(person_key="w-anna", full_name="Anna Reyes", **WRITER),
            feature_key="feature-a",
            **STANDARD_ITEM,
        )
        second_item = create_plan_item(
            bundle["train_id"], feature_key="feature-b", **INTERNAL_ITEM
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-17",
        )
        assign_plan_item(
            second_item["id"],
            bundle["writer_id"],
            window_start_date="2026-08-20",
            window_end_date="2026-09-05",
        )
        parent = create_topic(
            bundle["plan_item_id"],
            bundle["writer_id"],
            slug="atlas-feature-a",
            title="Feature A guide",
        )

        response = api.create_topic(
            create_topic_payload(
                second_item["id"],
                slug="atlas-feature-b",
                title="Feature B update",
                parent_topic_id=parent["id"],
            ),
            writer_headers_for(bundle["writer_id"]),
        )

        validate_error(response, ApiErrorId.PARENT_TOPIC_MISMATCH, 409)
        assert (
            response.json()["data"]["error_id"] != ApiErrorId.PARENT_TOPIC_NOT_FOUND.value
        ), "the parent resolves; it is under the other deliverable"

        _, meta = validate_list(
            api.list_topics(docs_lead_headers, params={"plan_item_id": second_item["id"]})
        )
        assert meta["total_count"] == 0
        assert read_plan_item(second_item["id"])["status"] == "ASSIGNED"
        # 26.00 for the STANDARD item plus 6.75 for the INTERNAL one.
        assert_committed_load_points(read_writer(bundle["writer_id"]), 32.75)

    def test_a_chain_of_five_pages_is_legal_and_bottoms_out_at_depth_four(
        self, api, docs_lead_headers, writer_headers_for
    ):
        """Root plus four descendants: the fifth page is created, at ia_depth 4.

        PRD §3.3: "The resulting parent chain must remain acyclic, and the new
        topic's depth must not exceed 4 — both failures report
        `ERR_IA_DEPTH_EXCEEDED`."

        PRD §3.3: "`ia_depth` is 0 for a root topic (no parent supplied) and
        otherwise one more than the parent's own `ia_depth`."

        Design: Corner/errors/information_architecture_depth_limit_exceeded_at_the_sixth_level
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides=dict(person_key="w-anna", full_name="Anna Reyes", **WRITER),
            feature_key="feature-a",
            **STANDARD_ITEM,
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-17",
        )

        chain = [
            create_topic(
                bundle["plan_item_id"],
                bundle["writer_id"],
                slug="atlas-level-0",
                title="Level 0",
            )
        ]
        for level in range(1, 4):
            chain.append(
                create_topic(
                    bundle["plan_item_id"],
                    bundle["writer_id"],
                    slug=f"atlas-level-{level}",
                    title=f"Level {level}",
                    parent_topic_id=chain[-1]["id"],
                )
            )

        deepest = validate_success(
            api.create_topic(
                create_topic_payload(
                    bundle["plan_item_id"],
                    slug="atlas-level-4",
                    title="Level 4",
                    parent_topic_id=chain[-1]["id"],
                ),
                writer_headers_for(bundle["writer_id"]),
            ),
            201,
        )

        assert [topic["ia_depth"] for topic in chain] == [0, 1, 2, 3]
        assert deepest["ia_depth"] == 4
        assert deepest["parent_topic_id"] == chain[-1]["id"]

    def test_a_sixth_level_is_refused_and_leaves_the_tree_five_pages_deep(
        self, api, docs_lead_headers, writer_headers_for
    ):
        """Depth 5 would exceed the limit, so the sixth page is never created.

        PRD §3.3: "The resulting parent chain must remain acyclic, and the new
        topic's depth must not exceed 4 — both failures report
        `ERR_IA_DEPTH_EXCEEDED`."

        PRD §3.3: "`ia_depth` is 0 for a root topic (no parent supplied) and
        otherwise one more than the parent's own `ia_depth`."

        Design: Corner/errors/information_architecture_depth_limit_exceeded_at_the_sixth_level
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides=dict(person_key="w-anna", full_name="Anna Reyes", **WRITER),
            feature_key="feature-a",
            **STANDARD_ITEM,
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-17",
        )
        deepest = create_topic(
            bundle["plan_item_id"], bundle["writer_id"], slug="atlas-level-0", title="Level 0"
        )
        for level in range(1, 5):
            deepest = create_topic(
                bundle["plan_item_id"],
                bundle["writer_id"],
                slug=f"atlas-level-{level}",
                title=f"Level {level}",
                parent_topic_id=deepest["id"],
            )
        assert deepest["ia_depth"] == 4

        response = api.create_topic(
            create_topic_payload(
                bundle["plan_item_id"],
                slug="atlas-level-5",
                title="Level 5",
                parent_topic_id=deepest["id"],
            ),
            writer_headers_for(bundle["writer_id"]),
        )
        validate_error(response, ApiErrorId.IA_DEPTH_EXCEEDED, 409)

        rows, meta = validate_list(
            api.list_topics(docs_lead_headers, params={"plan_item_id": bundle["plan_item_id"]})
        )
        assert meta["total_count"] == 5
        assert "atlas-level-5" not in {row["slug"] for row in rows}


class TestSourceRevisionImmutability:
    """A revision is a commit: it is stamped once, carries no version, and the
    older commit keeps its own word count after a newer one lands."""

    def _authored_page(self) -> dict[str, str]:
        """An assigned deliverable with one empty page, ready for commits."""
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides=dict(person_key="w-anna", full_name="Anna Reyes", **WRITER),
            feature_key="feature-a",
            **STANDARD_ITEM,
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-17",
        )
        topic = create_topic(
            bundle["plan_item_id"],
            bundle["writer_id"],
            slug="atlas-feature-a",
            title="Feature A guide",
        )
        return {"writer_id": bundle["writer_id"], "topic_id": topic["id"]}

    def test_each_commit_is_an_append_only_record_with_no_version_of_its_own(
        self, api, writer_headers_for
    ):
        """Two commits, two ids, numbers 1 then 2, and no mutable audit fields.

        PRD §2.4: "Two resources in this domain are append-only records of
        something that happened, and they therefore carry only `id` and
        `created_at`: a source revision and a page feedback row."

        PRD §2.4: "Neither has an `updated_at` field and neither has a `version`
        field, because neither is ever modified after it is written."

        PRD §3.3: "The server stamps `topic_id`, sets `author_writer_id` from the
        acting writer's `X-User-ID`, and assigns `revision_number` as one more
        than the topic's `current_revision_number`; the topic's
        `current_revision_number` and `latest_body_word_count` are updated to
        match."

        Design: Corner/entities/source_revision_is_immutable_with_no_version_field
        """
        page = self._authored_page()

        first = create_revision(
            page["topic_id"],
            page["writer_id"],
            body_word_count=1200,
            summary="First draft of the feature guide",
        )
        second = create_revision(
            page["topic_id"],
            page["writer_id"],
            body_word_count=1350,
            summary="Expanded the configuration section",
        )

        for revision in (first, second):
            assert_source_revision(revision)
            assert_append_only_audit_fields(revision)
            assert revision["topic_id"] == page["topic_id"]
            assert revision["author_writer_id"] == page["writer_id"]
            assert_instant_format(revision["created_at"])
            assert instants_equal(revision["created_at"], CLOCK)
        assert first["revision_number"] == 1
        assert second["revision_number"] == 2
        assert first["id"] != second["id"]
        assert first["body_word_count"] == 1200
        assert second["body_word_count"] == 1350

    def test_the_newer_commit_never_rewrites_the_older_one(
        self, api, writer_headers_for
    ):
        """The page tracks the latest word count; commit 1 keeps its own.

        PRD §3.3: "Revisions are immutable and are never returned by any other
        create response, so they are discovered either through the topic's own
        revision list — ordered by `revision_number` ascending — or through the
        per-writer revision list."

        PRD §3.3: "The server stamps `topic_id`, sets `author_writer_id` from the
        acting writer's `X-User-ID`, and assigns `revision_number` as one more
        than the topic's `current_revision_number`; the topic's
        `current_revision_number` and `latest_body_word_count` are updated to
        match."

        Design: Corner/entities/source_revision_is_immutable_with_no_version_field
        """
        page = self._authored_page()
        first = create_revision(
            page["topic_id"],
            page["writer_id"],
            body_word_count=1200,
            summary="First draft of the feature guide",
        )
        create_revision(
            page["topic_id"],
            page["writer_id"],
            body_word_count=1350,
            summary="Expanded the configuration section",
        )

        rows, meta = validate_list(
            api.list_topic_revisions(page["topic_id"], writer_headers_for(page["writer_id"]))
        )

        assert meta["total_count"] == 2
        assert [row["revision_number"] for row in rows] == [1, 2]
        stored_first = next(row for row in rows if row["id"] == first["id"])
        assert stored_first["body_word_count"] == 1200, "commit 1 was rewritten in place"
        assert stored_first["summary"] == "First draft of the feature guide"
        assert "version" not in stored_first
        assert "updated_at" not in stored_first

        topic = read_topic(page["topic_id"])
        assert topic["current_revision_number"] == 2
        assert topic["latest_body_word_count"] == 1350


class TestWriterRevisionsSubresource:
    """A writer's own commit history spans every page they touched, in the order
    they wrote them, and stops at the edge of their own authorship."""

    def _two_writers_each_with_commits(self) -> dict[str, str]:
        """Commits a1, b1, a2 written an hour apart by two different writers."""
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides=dict(person_key="w-anna", full_name="Anna Reyes", **WRITER),
            feature_key="feature-a",
            **STANDARD_ITEM,
        )
        other_writer = create_writer(
            person_key="w-bruno", full_name="Bruno Sá", **WRITER
        )
        other_item = create_plan_item(
            bundle["train_id"], feature_key="feature-b", **INTERNAL_ITEM
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-17",
        )
        assign_plan_item(
            other_item["id"],
            other_writer["id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-17",
        )
        anna_page = create_topic(
            bundle["plan_item_id"],
            bundle["writer_id"],
            slug="atlas-feature-a",
            title="Feature A guide",
        )
        bruno_page = create_topic(
            other_item["id"],
            other_writer["id"],
            slug="atlas-feature-b",
            title="Feature B update",
        )

        first_by_anna = create_revision(
            anna_page["id"], bundle["writer_id"], body_word_count=1200, summary="Anna draft one"
        )
        set_clock("2026-08-01T01:00:00Z")
        only_by_bruno = create_revision(
            bruno_page["id"], other_writer["id"], body_word_count=800, summary="Bruno draft one"
        )
        set_clock("2026-08-01T02:00:00Z")
        second_by_anna = create_revision(
            anna_page["id"], bundle["writer_id"], body_word_count=1350, summary="Anna draft two"
        )
        return {
            "anna_id": bundle["writer_id"],
            "bruno_id": other_writer["id"],
            "anna_first": first_by_anna["id"],
            "anna_second": second_by_anna["id"],
            "bruno_only": only_by_bruno["id"],
        }

    def test_a_writers_history_is_paged_oldest_first_across_all_their_pages(
        self, api, writer_headers_for
    ):
        """Anna's two commits come back in writing order on a default page.

        PRD §3.2: "The roster can be listed and filtered by `status` and by
        `seniority_tier`, and every writer's own source revisions across all
        topics can be listed on their behalf, ordered by `created_at` ascending —
        one of only two ways to discover revisions, since a revision is never
        returned by any create response other than its own."

        PRD §2.3: "Every paginated response carries `limit`, `offset`,
        `total_count`, and `has_more` in its `meta` block."

        Design: Corner/endpoints/writer_revisions_subresource_lists_authored_revisions_paginated
        """
        cast = self._two_writers_each_with_commits()

        rows, meta = validate_list(
            api.list_writer_revisions(cast["anna_id"], writer_headers_for(cast["anna_id"]))
        )

        assert_pagination_meta(meta, 10, 0, 2, False)
        assert_ids_in_order(rows, [cast["anna_first"], cast["anna_second"]])
        assert_created_at_ascending(rows)
        assert [row["revision_number"] for row in rows] == [1, 2]
        assert cast["bruno_only"] not in {row["id"] for row in rows}
        for row in rows:
            assert row["author_writer_id"] == cast["anna_id"]
            assert "version" not in row

    def test_the_other_writers_history_holds_only_their_own_commit(
        self, api, writer_headers_for
    ):
        """Bruno's list is one row: the subresource is scoped to authorship.

        PRD §3.2: "The roster can be listed and filtered by `status` and by
        `seniority_tier`, and every writer's own source revisions across all
        topics can be listed on their behalf, ordered by `created_at` ascending —
        one of only two ways to discover revisions, since a revision is never
        returned by any create response other than its own."

        PRD §2.3: "`total_count` is the number of records matching the request's
        filters before pagination is applied, and `has_more` is true exactly when
        records matching the filters remain beyond the returned page."

        Design: Corner/endpoints/writer_revisions_subresource_lists_authored_revisions_paginated
        """
        cast = self._two_writers_each_with_commits()

        rows, meta = validate_list(
            api.list_writer_revisions(cast["bruno_id"], writer_headers_for(cast["bruno_id"]))
        )

        assert_pagination_meta(meta, 10, 0, 1, False)
        assert_ids_in_order(rows, [cast["bruno_only"]])
        assert rows[0]["revision_number"] == 1
        assert rows[0]["author_writer_id"] == cast["bruno_id"]
        assert "version" not in rows[0]
        assert "updated_at" not in rows[0]
