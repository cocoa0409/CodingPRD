"""The two deep cascades: archiving a documentation set and retiring a release.

Retiring documentation is never a single write.  Archiving a published set walks
five ordered hops from the customer-visible notice down to the release train's
money ledger, unwinding topics, translation jobs and locale word reservations on
the way, and the last hop of the train's own lifecycle spine runs the same
unwinding a second time while generating the end-of-life notice text itself and
retiring every published deprecation notice.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_release_train_payload,
    advance_train,
    archive_doc_set_version_payload,
    expected_eol_notice_text,
    instants_equal,
    published_deprecation_notice_context,
    published_topic_context,
    read_deprecation_notice,
    read_doc_set_version,
    read_locale_profile,
    read_plan_item,
    read_release_train,
    read_topic,
    read_writer,
    set_clock,
    set_clock_date,
    validate_paginated,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"
ARCHIVE_CLOCK = "2026-08-05T09:30:00Z"
NOTICE_TEXT = "This documentation set is archived and no longer maintained."
GERMAN_LOCALE = {
    "locale_code": "de-DE",
    "tm_coverage_pct": 0.00,
    "per_word_rate_cents": 10.00,
    "sla_days": 15,
    "parallel_job_limit": 3,
}


class TestArchivingAPublishedDocumentationSet:
    """One archive request walks five hops, from the customer-visible notice down to
    the release train's committed-spend ledger."""

    def test_archiving_posts_the_notice_and_takes_the_live_page_out_of_circulation(
        self, api, docs_lead_headers
    ):
        """Hops one and two: the set itself, the train's notice flag, and the page.

        PRD §3.6: "**Hop one** sets `status` to `ARCHIVED`, stamps `archived_at`
        from the logical clock, stores the notice text, and sets the release
        train's `eol_notice_posted` to true."

        PRD §3.6: "**Hop two**, caused by hop one, moves every topic whose
        `published_in_doc_set_version_id` names this set from `publication_state`
        `PUBLISHED` to `ARCHIVED`, in `created_at` ascending order, recomputing
        each one's `health_score` under the post-publication variant."

        Design: Difficulty/transitive_cascade/doc_set_archive_cascade_depth_five_to_train_ledger
        """
        set_clock(CLOCK)
        bundle = published_topic_context(
            locales=[GERMAN_LOCALE],
            revision_overrides={"body_word_count": 1200},
            train_overrides={"localization_budget_cap_cents": 5000000},
        )
        live_topic = read_topic(bundle["topic_id"])
        assert live_topic["publication_state"] == "PUBLISHED"
        assert live_topic["published_in_doc_set_version_id"] == bundle["doc_set_id"]
        set_clock(ARCHIVE_CLOCK)

        archived = validate_success(
            api.archive_doc_set_version(
                bundle["doc_set_id"],
                archive_doc_set_version_payload(eol_notice_text=NOTICE_TEXT),
                docs_lead_headers,
            )
        )

        assert archived["status"] == "ARCHIVED"
        assert archived["eol_notice_text"] == NOTICE_TEXT
        assert instants_equal(archived["archived_at"], ARCHIVE_CLOCK)
        assert instants_equal(archived["published_at"], CLOCK)
        assert archived["published_topic_count"] == 1
        assert read_release_train(bundle["train_id"])["eol_notice_posted"] is True

        retired_topic = read_topic(bundle["topic_id"])
        assert retired_topic["publication_state"] == "ARCHIVED"
        assert retired_topic["published_in_doc_set_version_id"] == bundle["doc_set_id"]
        assert retired_topic["health_score_variant"] == "POST_PUBLICATION"
        assert retired_topic["health_score"] == pytest.approx(
            live_topic["health_score"], abs=0.01
        )

    def test_archiving_cancels_the_open_translation_jobs_and_frees_the_locale_words(
        self, api, docs_lead_headers, localization_coordinator_headers
    ):
        """Hops three and four: the queued job and the locale's word reservation.

        PRD §3.6: "**Hop three**, caused by hop two, moves every translation job
        of those topics whose state is `QUEUED`, `TRANSLATED`,
        `REWORK_REQUESTED`, or `SCHEDULED_DELAYED` to `CANCELLED`, in
        `created_at` ascending order, with `cancel_reason` recorded as exactly
        `CASCADE_DOC_SET_ARCHIVED`."

        PRD §3.6: "**Hop four**, caused by hop three, decreases each affected
        locale profile's `committed_source_words` by the cancelled job's
        `reserved_source_words` and its `open_job_count` by 1."

        Design: Difficulty/transitive_cascade/doc_set_archive_cascade_depth_five_to_train_ledger
        """
        set_clock(CLOCK)
        bundle = published_topic_context(
            locales=[GERMAN_LOCALE],
            revision_overrides={"body_word_count": 1200},
            train_overrides={"localization_budget_cap_cents": 5000000},
        )
        locale_id = bundle["pre_publication_locales"][0]["id"]
        rows, meta = validate_paginated(
            api.list_localization_jobs(localization_coordinator_headers, {"limit": 100})
        )
        assert meta["total_count"] == 1
        queued_job = rows[0]
        assert queued_job["state"] == "QUEUED"
        assert queued_job["reserved_source_words"] == 1200
        locale_before = read_locale_profile(locale_id)
        assert locale_before["committed_source_words"] == 1200
        assert locale_before["open_job_count"] == 1
        set_clock(ARCHIVE_CLOCK)

        validate_success(
            api.archive_doc_set_version(
                bundle["doc_set_id"],
                archive_doc_set_version_payload(eol_notice_text=NOTICE_TEXT),
                docs_lead_headers,
            )
        )

        cancelled_rows, _meta = validate_paginated(
            api.list_localization_jobs(localization_coordinator_headers, {"limit": 100})
        )
        cancelled = cancelled_rows[0]
        assert cancelled["id"] == queued_job["id"]
        assert cancelled["state"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "CASCADE_DOC_SET_ARCHIVED"
        assert cancelled["reserved_source_words"] == 1200

        locale_after = read_locale_profile(locale_id)
        assert locale_after["committed_source_words"] == 0
        assert locale_after["open_job_count"] == 0

    def test_the_cascade_ends_in_the_release_trains_committed_spend_ledger(
        self, api, docs_lead_headers, localization_coordinator_headers
    ):
        """Hop five: the train's money ledger returns to its pre-publication value.

        PRD §3.6: "**Hop five**, caused by hop four, recomputes the train's
        `localization_committed_cents` over the jobs that survived."

        PRD §2.8: "A create followed by its compensating cancel must return each
        affected ledger to precisely its pre-create value."

        Design: Difficulty/transitive_cascade/doc_set_archive_cascade_depth_five_to_train_ledger
        """
        set_clock(CLOCK)
        bundle = published_topic_context(
            locales=[GERMAN_LOCALE],
            revision_overrides={"body_word_count": 1200},
            train_overrides={"localization_budget_cap_cents": 5000000},
        )
        # 1200 words x 10.00 cents, no rush surcharge and no volume discount: 12000 cents.
        assert read_release_train(bundle["train_id"])["localization_committed_cents"] == 12000
        rows, _meta = validate_paginated(
            api.list_localization_jobs(localization_coordinator_headers, {"limit": 100})
        )
        assert rows[0]["estimated_cost_cents"] == 12000
        set_clock(ARCHIVE_CLOCK)

        validate_success(
            api.archive_doc_set_version(
                bundle["doc_set_id"],
                archive_doc_set_version_payload(eol_notice_text=NOTICE_TEXT),
                docs_lead_headers,
            )
        )

        assert read_release_train(bundle["train_id"])["localization_committed_cents"] == 0
        surviving_rows, _surviving_meta = validate_paginated(
            api.list_localization_jobs(localization_coordinator_headers, {"limit": 100})
        )
        history = surviving_rows[0]
        assert history["state"] == "CANCELLED"
        assert history["reserved_source_words"] == 1200, "the job keeps its own history"
        assert history["estimated_cost_cents"] == 12000
        assert read_doc_set_version(bundle["doc_set_id"])[
            "projected_localization_budget_cents"
        ] == 12000, "the stored projection is a published fact, not a live ledger"

    def test_every_record_the_cascade_touches_is_versioned_as_if_written_directly(
        self, api, docs_lead_headers, localization_coordinator_headers
    ):
        """The cascade stamps each touched record, and touches nothing else.

        PRD §2.8: "Every record a cascade touches has its `updated_at` refreshed
        to the current logical clock instant and its `version` incremented by 1,
        exactly as if it had been written directly — a topic archived as the
        fourth hop of an end-of-life cascade is as much a mutation of that topic
        as an explicit archive would have been."

        PRD §2.8: "Cascades run to completion inside the originating request; a
        response is never returned with a cascade half-applied."

        Design: Difficulty/transitive_cascade/doc_set_archive_cascade_depth_five_to_train_ledger
        """
        set_clock(CLOCK)
        bundle = published_topic_context(
            locales=[GERMAN_LOCALE],
            revision_overrides={"body_word_count": 1200},
            train_overrides={"localization_budget_cap_cents": 5000000},
        )
        locale_id = bundle["pre_publication_locales"][0]["id"]
        topic_before = read_topic(bundle["topic_id"])
        locale_before = read_locale_profile(locale_id)
        rows, _meta = validate_paginated(
            api.list_localization_jobs(localization_coordinator_headers, {"limit": 100})
        )
        job_before = rows[0]
        plan_item_before = read_plan_item(bundle["plan_item_id"])
        set_clock(ARCHIVE_CLOCK)

        validate_success(
            api.archive_doc_set_version(
                bundle["doc_set_id"],
                archive_doc_set_version_payload(eol_notice_text=NOTICE_TEXT),
                docs_lead_headers,
            )
        )

        topic_after = read_topic(bundle["topic_id"])
        locale_after = read_locale_profile(locale_id)
        job_rows, _job_meta = validate_paginated(
            api.list_localization_jobs(localization_coordinator_headers, {"limit": 100})
        )
        job_after = job_rows[0]
        for before, after in (
            (topic_before, topic_after),
            (locale_before, locale_after),
            (job_before, job_after),
        ):
            assert after["version"] == before["version"] + 1
            assert instants_equal(after["updated_at"], ARCHIVE_CLOCK)

        plan_item_after = read_plan_item(bundle["plan_item_id"])
        assert plan_item_after["status"] == "PUBLISHED"
        assert plan_item_after["version"] == plan_item_before["version"]
        assert topic_after["review_state"] == "FULLY_APPROVED", (
            "archival is a publication-dimension event, not a review-dimension one"
        )
        assert read_release_train(bundle["train_id"])["status"] == "PLANNED"
        assert read_writer(bundle["writer_id"])["committed_load_points"] == pytest.approx(
            0.00, abs=0.01
        )


class TestEndOfLifeRetirementOfARelease:
    """The last hop of the lifecycle spine generates the customer-facing notice text
    itself, runs the same unwinding, and retires every published deprecation."""

    def test_end_of_life_archives_the_published_set_with_the_generated_notice_text(
        self, api, docs_lead_headers
    ):
        """Hops one through three, with the notice text composed from the train.

        PRD §3.1: "**Hop one** sets the train's `status` to `END_OF_LIFE`, forces
        `doc_readiness_posture` to `FROZEN`, and sets `eol_notice_posted` to
        true."

        PRD §3.1: "**Hop two**, caused by hop one, takes every documentation set
        of this train whose status is `PUBLISHED`, in `created_at` ascending
        order, to `ARCHIVED`, stamping `archived_at` with the logical clock and
        writing an `eol_notice_text` of the form `End of life: support for
        <product_key> <version_label> ended on <support_end_date>.` — with the
        train's own product key, version label, and end-of-support date
        substituted in."

        PRD §3.1: "**Hop three**, caused by hop two, moves every topic whose
        `published_in_doc_set_version_id` names one of those documentation sets
        from `publication_state` `PUBLISHED` to `ARCHIVED`, in `created_at`
        ascending order, and recomputes each such topic's health score under its
        post-publication variant."

        Design: Corner/state_machines/release_train_end_of_life_cascade_archives_doc_set_and_retires_notice
        """
        set_clock(CLOCK)
        bundle = published_deprecation_notice_context(
            locales=[GERMAN_LOCALE],
            revision_overrides={"body_word_count": 1200},
            train_overrides={
                "doc_freeze_date": "2026-08-10",
                "ga_date": "2026-08-20",
                "support_end_date": "2026-09-01",
                "localization_budget_cap_cents": 5000000,
            },
        )
        train_before = read_release_train(bundle["train_id"])
        topic_before = read_topic(bundle["topic_id"])
        advance_train(bundle["train_id"], "DOC_FREEZE")
        advance_train(bundle["train_id"], "GA")
        advance_train(bundle["train_id"], "MAINTENANCE")
        set_clock_date("2026-09-01")

        train = validate_success(
            api.advance_release_train(
                bundle["train_id"],
                advance_release_train_payload("END_OF_LIFE"),
                docs_lead_headers,
            )
        )

        assert train["status"] == "END_OF_LIFE"
        assert train["doc_readiness_posture"] == "FROZEN"
        assert train["eol_notice_posted"] is True

        archived = read_doc_set_version(bundle["doc_set_id"])
        assert archived["status"] == "ARCHIVED"
        assert instants_equal(archived["archived_at"], "2026-09-01T00:00:00Z")
        assert archived["eol_notice_text"] == expected_eol_notice_text(
            train_before["product_key"], train_before["version_label"], "2026-09-01"
        )
        assert archived["eol_notice_text"] == (
            f"End of life: support for {train_before['product_key']} "
            f"{train_before['version_label']} ended on 2026-09-01."
        )

        retired_topic = read_topic(bundle["topic_id"])
        assert retired_topic["publication_state"] == "ARCHIVED"
        assert retired_topic["health_score_variant"] == "POST_PUBLICATION"
        assert retired_topic["health_score"] == pytest.approx(
            topic_before["health_score"], abs=0.01
        )

    def test_end_of_life_unwinds_the_locale_ledgers_and_retires_the_deprecation(
        self, api, docs_lead_headers, localization_coordinator_headers
    ):
        """Hops four and five, plus the independent retirement of the notice.

        PRD §3.1: "**Hop four**, caused by hop three, cancels every translation
        job of those topics whose state is `QUEUED`, `TRANSLATED`,
        `REWORK_REQUESTED`, or `SCHEDULED_DELAYED`, in `created_at` ascending
        order, recording `cancel_reason` as exactly `CASCADE_DOC_SET_ARCHIVED`."

        PRD §3.1: "**Hop five**, caused by hop four, decreases each affected
        locale profile's `committed_source_words` by that job's
        `reserved_source_words` and its `open_job_count` by 1, after which the
        train's `localization_committed_cents` is recomputed over the jobs that
        survived."

        PRD §3.1: "Independently of those five hops, every deprecation notice of
        this train whose status is `PUBLISHED` moves to `RETIRED`, and the
        train's own `version` is incremented by 1."

        Design: Corner/state_machines/release_train_end_of_life_cascade_archives_doc_set_and_retires_notice
        """
        set_clock(CLOCK)
        bundle = published_deprecation_notice_context(
            locales=[GERMAN_LOCALE],
            revision_overrides={"body_word_count": 1200},
            train_overrides={
                "doc_freeze_date": "2026-08-10",
                "ga_date": "2026-08-20",
                "support_end_date": "2026-09-01",
                "localization_budget_cap_cents": 5000000,
            },
        )
        locale_id = bundle["pre_publication_locales"][0]["id"]
        notice_before = read_deprecation_notice(bundle["deprecation_notice_id"])
        assert notice_before["status"] == "PUBLISHED"
        assert read_locale_profile(locale_id)["committed_source_words"] == 1200
        assert read_release_train(bundle["train_id"])["localization_committed_cents"] == 12000
        advance_train(bundle["train_id"], "DOC_FREEZE")
        advance_train(bundle["train_id"], "GA")
        advance_train(bundle["train_id"], "MAINTENANCE")
        set_clock_date("2026-09-01")

        validate_success(
            api.advance_release_train(
                bundle["train_id"],
                advance_release_train_payload("END_OF_LIFE"),
                docs_lead_headers,
            )
        )

        rows, meta = validate_paginated(
            api.list_localization_jobs(localization_coordinator_headers, {"limit": 100})
        )
        assert meta["total_count"] == 1
        assert rows[0]["state"] == "CANCELLED"
        assert rows[0]["cancel_reason"] == "CASCADE_DOC_SET_ARCHIVED"

        locale_after = read_locale_profile(locale_id)
        assert locale_after["committed_source_words"] == 0
        assert locale_after["open_job_count"] == 0
        assert read_release_train(bundle["train_id"])["localization_committed_cents"] == 0

        notice_after = read_deprecation_notice(bundle["deprecation_notice_id"])
        assert notice_after["status"] == "RETIRED"
        assert instants_equal(notice_after["published_at"], notice_before["published_at"])
        assert notice_after["version"] == notice_before["version"] + 1
        assert notice_after["feature_key"] == notice_before["feature_key"]
