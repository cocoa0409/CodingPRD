"""Documentation-set drafts, the publication gate, and the localization budget.

A documentation set version is the labelled snapshot customers actually read, so
opening one is guarded by the release train's optimistic lock and publishing one
is guarded by three preconditions that run in a pinned order before a single
field is written.  The densest of those preconditions is the localization budget
projection, whose rounding order — round per locale, then sum — is itself part of
the contract, because a cent of rounding drift is exactly enough to flip the cap
comparison.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    archived_doc_set_context,
    create_doc_set_version_payload,
    create_locale_profile,
    create_release_train,
    draft_doc_set_context,
    editorial_pass_payload,
    excluded_change_record_context,
    expected_budget_projection,
    expected_load_points,
    expected_locale_projection_contribution,
    instants_equal,
    read_change_record,
    read_doc_set_version,
    read_locale_profile,
    read_plan_item,
    read_release_train,
    read_topic,
    read_writer,
    set_clock,
    submitted_topic_context,
    validate_error,
    validate_paginated,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"


class TestDocumentationSetDraftOpening:
    """Opening a draft is destructive to the train's previous draft, so the train's
    own version is the only defence a caller has against acting on a stale view."""

    def test_second_draft_opened_from_a_stale_view_of_the_train_is_refused(
        self, api, docs_lead_headers
    ):
        """The first draft bumps the train, so replaying its version is rejected.

        PRD §3.6: "A new draft opens with `status` `DRAFT`,
        `published_topic_count` 0, and `projected_localization_budget_cents` 0,
        since no projection exists until publication."

        PRD §3.6: "Opening a new draft moves any documentation set of that train
        that is currently the train's only `DRAFT` row to `SUPERSEDED`, and
        increments the release train's `version` by 1."

        PRD §2.6: "If that value does not equal the release train's current
        `version` — because some other writer advanced the train's lifecycle
        status, changed its readiness posture, or already opened a newer draft
        since the client read it — the request is rejected with
        `ERR_STALE_RELEASE_TRAIN_VERSION` (HTTP 412) and nothing is created."

        Design: Corner/cross_cutting_complexity_layers/doc_set_create_with_stale_release_train_version_rejected
        """
        set_clock(CLOCK)
        train = create_release_train()
        observed_version = train["version"]

        first = validate_success(
            api.create_doc_set_version(
                create_doc_set_version_payload(train["id"], observed_version), docs_lead_headers
            ),
            201,
        )
        assert first["status"] == "DRAFT"
        assert first["published_topic_count"] == 0
        assert first["projected_localization_budget_cents"] == 0
        assert read_release_train(train["id"])["version"] == observed_version + 1

        response = api.create_doc_set_version(
            create_doc_set_version_payload(train["id"], observed_version), docs_lead_headers
        )
        validate_error(response, ApiErrorId.STALE_RELEASE_TRAIN_VERSION, 412)

        rows, meta = validate_paginated(
            api.list_doc_set_versions(docs_lead_headers, {"release_train_id": train["id"]})
        )
        assert meta["total_count"] == 1, "the refused create must not have persisted a draft"
        assert rows[0]["id"] == first["id"]
        assert read_doc_set_version(first["id"])["status"] == "DRAFT"
        assert read_release_train(train["id"])["version"] == observed_version + 1

    def test_reopening_the_draft_from_a_fresh_read_supersedes_the_earlier_one(
        self, api, docs_lead_headers
    ):
        """Once the caller re-reads the train, the same create is accepted and the
        earlier draft is retired.

        PRD §2.6: "Because a new draft legitimately supersedes the train's
        previous draft, the operation cannot protect itself by refusing to
        overwrite; the parent version check is the only defence against a caller
        acting on an out-of-date picture of the train."

        PRD §3.6: "Opening a new draft moves any documentation set of that train
        that is currently the train's only `DRAFT` row to `SUPERSEDED`, and
        increments the release train's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/doc_set_create_with_stale_release_train_version_rejected
        """
        set_clock(CLOCK)
        train = create_release_train()
        first = validate_success(
            api.create_doc_set_version(
                create_doc_set_version_payload(train["id"], train["version"]), docs_lead_headers
            ),
            201,
        )
        refreshed_version = read_release_train(train["id"])["version"]

        second = validate_success(
            api.create_doc_set_version(
                create_doc_set_version_payload(train["id"], refreshed_version), docs_lead_headers
            ),
            201,
        )

        assert second["status"] == "DRAFT"
        assert read_doc_set_version(first["id"])["status"] == "SUPERSEDED"
        assert read_release_train(train["id"])["version"] == refreshed_version + 1
        _rows, meta = validate_paginated(
            api.list_doc_set_versions(docs_lead_headers, {"release_train_id": train["id"]})
        )
        assert meta["total_count"] == 2


class TestPublicationWithNothingToPublish:
    """An empty candidate set is reported as an empty candidate set — never as a
    budget figure — and a record already dropped from customer communication is
    equally closed to further editing."""

    def test_publication_with_no_fully_approved_page_never_reports_a_budget_figure(
        self, api, docs_lead_headers
    ):
        """A train whose only page is still in review has an empty candidate set.

        PRD §3.6: "At least one topic of the train must have `review_state`
        `FULLY_APPROVED`, else `ERR_NO_APPROVED_TOPICS` — this is checked
        *before* the budget projection, so an empty candidate set never surfaces
        as a budget error."

        PRD §2.5: "A doc set publication with no approved topics reports the
        empty candidate set and never a budget figure."

        Design: Corner/errors/doc_set_publish_without_approved_topics_and_excluded_record_not_editable
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context(
            train_overrides={"localization_budget_cap_cents": 0}
        )
        locale = create_locale_profile(
            locale_code="de-DE", tm_coverage_pct=0.00, per_word_rate_cents=12.50
        )
        doc_set = validate_success(
            api.create_doc_set_version(
                create_doc_set_version_payload(
                    bundle["train_id"], read_release_train(bundle["train_id"])["version"]
                ),
                docs_lead_headers,
            ),
            201,
        )

        response = api.publish_doc_set_version(doc_set["id"], {}, docs_lead_headers)
        validate_error(response, ApiErrorId.NO_APPROVED_TOPICS, 409)

        unchanged = read_doc_set_version(doc_set["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["published_topic_count"] == 0
        assert unchanged["projected_localization_budget_cents"] == 0
        assert unchanged["published_at"] is None
        assert read_topic(bundle["topic_id"])["review_state"] == "PENDING_SIGNOFF"
        assert read_topic(bundle["topic_id"])["publication_state"] == "UNPUBLISHED"
        assert read_locale_profile(locale["id"])["committed_source_words"] == 0
        assert read_release_train(bundle["train_id"])["localization_committed_cents"] == 0

    def test_excluded_change_record_cannot_be_taken_through_an_editorial_pass(
        self, api, docs_lead_alt_headers
    ):
        """Exclusion is permanent, so the editorial endpoint refuses the record.

        PRD §3.7: "A `DocsLead` supplies an `exclusion_reason` of 5 to 200
        characters and the record moves to `EXCLUDED`, permitted only from
        `SUBMITTED` or `REWORK_REQUESTED` and otherwise refused with
        `ERR_CHANGE_RECORD_NOT_EDITABLE`."

        PRD §3.7: "The record's `state` must be `SUBMITTED` or
        `REWORK_REQUESTED`; a record that is `EDITORIALLY_APPROVED`, `EXCLUDED`,
        or `PUBLISHED` is refused with `ERR_CHANGE_RECORD_NOT_EDITABLE`."

        Design: Corner/errors/doc_set_publish_without_approved_topics_and_excluded_record_not_editable
        """
        set_clock(CLOCK)
        bundle = excluded_change_record_context()
        excluded = bundle["change_record"]
        assert excluded["state"] == "EXCLUDED"

        response = api.editorial_pass(
            bundle["change_record_id"],
            editorial_pass_payload(customer_facing_text="A cleaner customer-facing wording."),
            docs_lead_alt_headers,
        )
        validate_error(response, ApiErrorId.CHANGE_RECORD_NOT_EDITABLE, 409)

        unchanged = read_change_record(bundle["change_record_id"])
        assert unchanged["state"] == "EXCLUDED"
        assert unchanged["customer_facing_text"] is None
        assert unchanged["editorial_by_user_id"] is None
        assert unchanged["rework_count"] == 0
        assert unchanged["exclusion_reason"] == excluded["exclusion_reason"]
        assert unchanged["version"] == excluded["version"]

    def test_archived_documentation_set_cannot_be_published_a_second_time(
        self, api, docs_lead_headers
    ):
        """ARCHIVED is one of the three states the DRAFT precondition excludes.

        PRD §3.6: "The set's `status` must be `DRAFT`; a set that is already
        `PUBLISHED`, `SUPERSEDED`, or `ARCHIVED` is refused with
        `ERR_DOC_SET_NOT_DRAFT`."

        PRD §3.6: "Three preconditions are evaluated in a fixed order, all of
        them **before any state is mutated**."

        Design: Corner/state_machines/doc_set_publish_from_archived_state_rejected
        """
        set_clock(CLOCK)
        bundle = archived_doc_set_context(
            archive_overrides={"eol_notice_text": "This release has reached end of life."}
        )
        archived = read_doc_set_version(bundle["doc_set_id"])
        assert archived["status"] == "ARCHIVED"

        response = api.publish_doc_set_version(bundle["doc_set_id"], {}, docs_lead_headers)
        validate_error(response, ApiErrorId.DOC_SET_NOT_DRAFT, 409)

        unchanged = read_doc_set_version(bundle["doc_set_id"])
        assert unchanged["status"] == "ARCHIVED"
        assert unchanged["eol_notice_text"] == "This release has reached end of life."
        assert instants_equal(unchanged["archived_at"], archived["archived_at"])
        assert instants_equal(unchanged["published_at"], archived["published_at"])
        assert unchanged["published_topic_count"] == archived["published_topic_count"]
        assert unchanged["version"] == archived["version"]
        assert read_topic(bundle["topic_id"])["publication_state"] == "ARCHIVED"


class TestLocalizationBudgetProjection:
    """The projection rounds each participating locale to whole cents on its own and
    only then adds them up, which is what makes the cap comparison reproducible."""

    def test_projection_rounds_each_locale_before_summing_and_publishes_at_the_cap(
        self, api, docs_lead_headers
    ):
        """1205 words across two locales project to exactly the cap and go live.

        PRD §3.6: "The projection is a base quote only — no rush surcharge and no
        volume discount enters it — and its rounding order is part of the
        contract: **round per locale, then sum**."

        PRD §3.6: "Third, for each locale in that order: the
        translation-memory word count is the publishable volume multiplied by
        that locale's `tm_coverage_pct` divided by 100, with any fraction
        discarded downwards; the effective word count is the publishable volume
        minus seventy percent of that translation-memory word count, again with
        any fraction of the seventy-percent figure discarded downwards, because
        memory matches are cheaper rather than free; and that locale's
        contribution in cents is the effective word count multiplied by the
        locale's `per_word_rate_cents`, **rounded half up to whole cents right
        there**."

        PRD §3.6: "Fourth, `projected_localization_budget_cents` is the sum of
        those already-rounded per-locale figures."

        PRD §3.6: "Then the **localization budget projection** is computed,
        stored in `projected_localization_budget_cents`, and compared against the
        train's `localization_budget_cap_cents`; a projection strictly greater
        than the cap is refused with `ERR_LOCALIZATION_BUDGET_EXCEEDED`, while a
        projection exactly equal to the cap is allowed to publish."

        Design: Difficulty/combinatorial_formula/doc_set_budget_rounds_per_locale_before_summing_mode_b
        """
        set_clock(CLOCK)
        bundle = draft_doc_set_context(
            train_overrides={"localization_budget_cap_cents": 20846},
            revision_overrides={"body_word_count": 1205},
        )
        create_locale_profile(
            locale_code="de-DE", tm_coverage_pct=0.00, per_word_rate_cents=9.44
        )
        create_locale_profile(
            locale_code="fr-FR", tm_coverage_pct=0.00, per_word_rate_cents=7.86
        )
        assert read_topic(bundle["topic_id"])["latest_body_word_count"] == 1205

        published = validate_success(
            api.publish_doc_set_version(bundle["doc_set_id"], {}, docs_lead_headers)
        )

        # de-DE: 1205 x 9.44 = 11375.20 -> 11375 cents.
        # fr-FR: 1205 x 7.86 =  9471.30 ->  9471 cents.
        # 11375 + 9471 = 20846, which is exactly the cap.
        assert published["projected_localization_budget_cents"] == 20846
        assert published["projected_localization_budget_cents"] == expected_budget_projection(
            1205, [(0.00, 9.44), (0.00, 7.86)]
        )
        assert published["projected_localization_budget_cents"] != 20847, (
            "summing the unrounded products and rounding once would give 20847"
        )
        assert published["status"] == "PUBLISHED"
        assert published["published_topic_count"] == 1
        assert instants_equal(published["published_at"], CLOCK)
        assert read_topic(bundle["topic_id"])["publication_state"] == "PUBLISHED"

    def test_each_participating_locale_reserves_its_own_words_and_its_own_cents(
        self, api, docs_lead_headers, localization_coordinator_headers
    ):
        """Publication seeds one job per locale, each carrying that locale's figure.

        PRD §3.6: "For each topic just taken live, and for each locale profile
        whose `status` is `ACTIVE` and whose `publication_mode` is
        `SIMULTANEOUS` — walked in `locale_code` ascending order — a translation
        job is auto-created in state `QUEUED` with `auto_created` set to true,
        reserving that topic's `latest_body_word_count` on that locale and
        carrying a provisional cost quote."

        PRD §3.6: "Each auto-created job spans from the logical clock's date
        through that date plus the locale's `sla_days`, which makes its window
        exactly one day longer than the service-level period, so an auto-created
        job never carries a rush surcharge."

        PRD §3.6: "Each new job increases its locale's `committed_source_words`
        by the reserved volume and its `open_job_count` by 1."

        Design: Difficulty/combinatorial_formula/doc_set_budget_rounds_per_locale_before_summing_mode_b
        """
        set_clock(CLOCK)
        bundle = draft_doc_set_context(
            train_overrides={"localization_budget_cap_cents": 20846},
            revision_overrides={"body_word_count": 1205},
        )
        german = create_locale_profile(
            locale_code="de-DE", tm_coverage_pct=0.00, per_word_rate_cents=9.44, sla_days=10
        )
        french = create_locale_profile(
            locale_code="fr-FR", tm_coverage_pct=0.00, per_word_rate_cents=7.86, sla_days=10
        )

        validate_success(api.publish_doc_set_version(bundle["doc_set_id"], {}, docs_lead_headers))

        rows, meta = validate_paginated(
            api.list_localization_jobs(localization_coordinator_headers, {"limit": 100})
        )
        assert meta["total_count"] == 2
        by_locale = {row["locale_profile_id"]: row for row in rows}
        assert set(by_locale) == {german["id"], french["id"]}
        for job in rows:
            assert job["auto_created"] is True
            assert job["state"] == "QUEUED"
            assert job["reserved_source_words"] == 1205
            assert job["cost_variant"] == "PROVISIONAL"
            assert job["window_start_date"] == "2026-08-01"
            assert job["window_end_date"] == "2026-08-11"
            assert job["rush_surcharge_cents"] == 0

        assert by_locale[german["id"]]["estimated_cost_cents"] == 11375
        assert by_locale[french["id"]]["estimated_cost_cents"] == 9471
        assert by_locale[german["id"]]["estimated_cost_cents"] == (
            expected_locale_projection_contribution(1205, 0.00, 9.44)
        )
        assert by_locale[french["id"]]["estimated_cost_cents"] == (
            expected_locale_projection_contribution(1205, 0.00, 7.86)
        )

        for locale_id in (german["id"], french["id"]):
            locale = read_locale_profile(locale_id)
            assert locale["committed_source_words"] == 1205
            assert locale["open_job_count"] == 1
        assert read_release_train(bundle["train_id"])["localization_committed_cents"] == 20846

    @pytest.mark.parametrize(
        "cap_cents, expected_status",
        [(20845, "DRAFT"), (20846, "PUBLISHED"), (20847, "PUBLISHED")],
    )
    def test_the_cap_comparison_turns_on_the_per_locale_rounded_total(
        self, api, docs_lead_headers, cap_cents, expected_status
    ):
        """One cent below the per-locale total refuses; at it and above it publish.

        PRD §3.6: "Then the **localization budget projection** is computed,
        stored in `projected_localization_budget_cents`, and compared against the
        train's `localization_budget_cap_cents`; a projection strictly greater
        than the cap is refused with `ERR_LOCALIZATION_BUDGET_EXCEEDED`, while a
        projection exactly equal to the cap is allowed to publish."

        PRD §3.6: "Summing the unrounded products and rounding once at the end
        can differ by up to a cent per locale, and that difference is exactly
        enough to flip the cap comparison, so the pinned order is mandatory."

        Design: Difficulty/combinatorial_formula/doc_set_budget_rounds_per_locale_before_summing_mode_b
        """
        set_clock(CLOCK)
        bundle = draft_doc_set_context(
            train_overrides={"localization_budget_cap_cents": cap_cents},
            revision_overrides={"body_word_count": 1205},
        )
        create_locale_profile(
            locale_code="de-DE", tm_coverage_pct=0.00, per_word_rate_cents=9.44
        )
        create_locale_profile(
            locale_code="fr-FR", tm_coverage_pct=0.00, per_word_rate_cents=7.86
        )

        response = api.publish_doc_set_version(bundle["doc_set_id"], {}, docs_lead_headers)

        if expected_status == "PUBLISHED":
            published = validate_success(response)
            assert published["projected_localization_budget_cents"] == 20846
            assert published["status"] == "PUBLISHED"
        else:
            validate_error(response, ApiErrorId.LOCALIZATION_BUDGET_EXCEEDED, 409)
            refused = read_doc_set_version(bundle["doc_set_id"])
            assert refused["status"] == "DRAFT"
            assert refused["projected_localization_budget_cents"] == 0
            assert refused["published_at"] is None

    def test_publication_one_cent_over_the_cap_leaves_every_ledger_untouched(
        self, api, docs_lead_headers, localization_coordinator_headers
    ):
        """A 12000-cent projection against an 11999-cent cap mutates nothing at all.

        PRD §3.6: "Three preconditions are evaluated in a fixed order, all of
        them **before any state is mutated**."

        PRD §3.6: "Then the **localization budget projection** is computed,
        stored in `projected_localization_budget_cents`, and compared against the
        train's `localization_budget_cap_cents`; a projection strictly greater
        than the cap is refused with `ERR_LOCALIZATION_BUDGET_EXCEEDED`, while a
        projection exactly equal to the cap is allowed to publish."

        PRD §2.5: "**Fiscal capacity, evaluated last.** Localization budget caps
        and writer capacity ceilings."

        Design: Corner/validations/doc_set_publish_over_budget_by_one_cent_mutates_nothing
        """
        set_clock(CLOCK)
        bundle = draft_doc_set_context(
            train_overrides={"localization_budget_cap_cents": 11999},
            revision_overrides={"body_word_count": 1200},
        )
        locale = create_locale_profile(
            locale_code="de-DE", tm_coverage_pct=0.00, per_word_rate_cents=10.00
        )
        committed_before = expected_load_points(3, 10, "NEW_TOPIC", "STANDARD", "SENIOR")

        response = api.publish_doc_set_version(bundle["doc_set_id"], {}, docs_lead_headers)
        validate_error(response, ApiErrorId.LOCALIZATION_BUDGET_EXCEEDED, 409)

        # 1200 words x 10.00 cents = 12000 cents, one cent over the 11999 cap.
        assert expected_budget_projection(1200, [(0.00, 10.00)]) == 12000
        refused = read_doc_set_version(bundle["doc_set_id"])
        assert refused["status"] == "DRAFT"
        assert refused["published_topic_count"] == 0
        assert refused["projected_localization_budget_cents"] == 0
        assert refused["published_at"] is None

        assert read_topic(bundle["topic_id"])["publication_state"] == "UNPUBLISHED"
        assert read_topic(bundle["topic_id"])["health_score_variant"] == "PRE_PUBLICATION"
        assert read_plan_item(bundle["plan_item_id"])["status"] == "APPROVED_CONTENT"
        assert read_writer(bundle["writer_id"])["committed_load_points"] == pytest.approx(
            committed_before, abs=0.01
        )
        untouched_locale = read_locale_profile(locale["id"])
        assert untouched_locale["committed_source_words"] == 0
        assert untouched_locale["open_job_count"] == 0
        assert read_release_train(bundle["train_id"])["localization_committed_cents"] == 0
        _rows, meta = validate_paginated(
            api.list_localization_jobs(localization_coordinator_headers, {"limit": 100})
        )
        assert meta["total_count"] == 0
