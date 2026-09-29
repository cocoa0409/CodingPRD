"""The gates that decide whether translation work may start, land, or go live.

Nothing is translated until the source page is live, the locale is accepting
work, and the locale's overlapping-window ceiling has room — except for the jobs
a documentation-set publication seeds, which are exempt from that ceiling.  This
module also covers the order in which a delivery's checks run, the three-day
grace period the service-level test allows, and the release-train condition the
simultaneous publication branch adds.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_train,
    assert_committed_source_words,
    assert_localization_committed_cents,
    cancel_localization_job,
    cancel_localization_job_payload,
    create_locale_profile,
    create_localization_job,
    create_localization_job_payload,
    deliver_localization_job_payload,
    draft_doc_set_context,
    expected_quote,
    instants_equal,
    publish_doc_set_version,
    published_topic_context,
    published_topics_context,
    queued_job_context,
    read_locale_profile,
    read_localization_job,
    read_release_train,
    read_topic,
    set_clock,
    translated_job_context,
    validate_error,
    validate_list,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"

#: A locale that publishes on a lag, so a documentation-set publication seeds no
#: job for it and its budget projection contributes nothing.
LAGGING_LOCALE = {
    "publication_mode": "DELAYED",
    "tm_coverage_pct": 0.00,
    "per_word_rate_cents": 10.00,
    "sla_days": 10,
    "parallel_job_limit": 5,
}


class TestSourcePageMustBeLiveBeforeTranslation:
    """A translation job's first gate is a state on a *different* entity — the
    source topic's publication state — and nothing else about the request changes
    when that gate opens."""

    JOB_WINDOW = {"window_start_date": "2026-08-01", "window_end_date": "2026-08-21"}

    def test_translation_is_refused_while_the_source_page_is_still_unpublished(
        self, api, localization_coordinator_headers
    ):
        """An approved-but-unpublished page cannot be handed to a vendor.

        PRD §3.8: "The source topic's `publication_state` must be `PUBLISHED` —
        only live pages are translated — else `ERR_SOURCE_TOPIC_NOT_PUBLISHED`."

        PRD §3.8: "The locale's `committed_source_words` increases by
        `reserved_source_words`, its `open_job_count` increases by 1, and the
        owning release train's `localization_committed_cents` is recomputed."

        Design: Difficulty/cross_entity_state_dependency/localization_job_creation_gated_by_source_topic_publication_state
        """
        set_clock(CLOCK)
        bundle = draft_doc_set_context(revision_overrides={"body_word_count": 1200})
        locale = create_locale_profile(**LAGGING_LOCALE)
        assert read_topic(bundle["topic_id"])["publication_state"] == "UNPUBLISHED"
        assert read_topic(bundle["topic_id"])["review_state"] == "FULLY_APPROVED"

        response = api.create_localization_job(
            create_localization_job_payload(
                bundle["topic_id"], locale["id"], **self.JOB_WINDOW
            ),
            localization_coordinator_headers,
        )
        validate_error(response, ApiErrorId.SOURCE_TOPIC_NOT_PUBLISHED, 409)

        unchanged = read_locale_profile(locale["id"])
        assert_committed_source_words(unchanged, 0)
        assert unchanged["open_job_count"] == 0
        _, meta = validate_list(
            api.list_localization_jobs(
                localization_coordinator_headers, {"topic_id": bundle["topic_id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_the_identical_request_succeeds_once_the_documentation_set_goes_live(
        self, api, localization_coordinator_headers
    ):
        """Publishing the set flips the guarding state and the same body is accepted.

        PRD §3.6: "Every topic of the train whose `review_state` is
        `FULLY_APPROVED` moves `publication_state` from `UNPUBLISHED` to
        `PUBLISHED`, in `created_at` ascending order, each taking `published_at`
        from the logical clock and `published_in_doc_set_version_id` from the
        publishing set; `published_topic_count` is set to the number of topics
        taken live."

        PRD §3.6: "Second, the participating locales are the locale profiles whose
        `status` is `ACTIVE` **and** whose `publication_mode` is `SIMULTANEOUS`,
        walked in `locale_code` ascending order; paused locales and
        delayed-publication locales contribute nothing at all."

        PRD §3.8: "A successful create opens the job in state `QUEUED` with
        `auto_created` false, pins `source_revision_number` from the topic's
        `current_revision_number` and `reserved_source_words` from the topic's
        `latest_body_word_count`, and quotes a provisional cost."

        Design: Difficulty/cross_entity_state_dependency/localization_job_creation_gated_by_source_topic_publication_state
        """
        set_clock(CLOCK)
        bundle = draft_doc_set_context(revision_overrides={"body_word_count": 1200})
        locale = create_locale_profile(**LAGGING_LOCALE)
        payload = create_localization_job_payload(
            bundle["topic_id"], locale["id"], **self.JOB_WINDOW
        )
        validate_error(
            api.create_localization_job(payload, localization_coordinator_headers),
            ApiErrorId.SOURCE_TOPIC_NOT_PUBLISHED,
            409,
        )

        doc_set = publish_doc_set_version(bundle["doc_set_id"])
        assert doc_set["published_topic_count"] == 1
        assert doc_set["projected_localization_budget_cents"] == 0, (
            "a delayed-publication locale contributes nothing to the projection"
        )
        assert read_topic(bundle["topic_id"])["publication_state"] == "PUBLISHED"

        job = validate_success(
            api.create_localization_job(payload, localization_coordinator_headers), 201
        )

        assert job["state"] == "QUEUED"
        assert job["auto_created"] is False
        assert job["source_revision_number"] == 1
        assert job["reserved_source_words"] == 1200
        # 1200 words at zero coverage and 10.00 a word is 12,000 cents, with the
        # 21-day window clearing the locale's 10-day service level surcharge-free.
        assert job["estimated_cost_cents"] == 12000
        assert expected_quote(1200, 0, 10.00, "2026-08-01", "2026-08-21", 10)["cost_cents"] == 12000

        locale_after = read_locale_profile(locale["id"])
        assert_committed_source_words(locale_after, 1200)
        assert locale_after["open_job_count"] == 1
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 12000)


class TestParallelWindowCeilingOverClosedIntervals:
    """The ceiling counts open jobs whose closed windows intersect the requested
    one, and the jobs a publication seeded are exempt from it."""

    #: A locale that tolerates only one overlapping vendor window at a time.
    NARROW_LOCALE = {
        "publication_mode": "DELAYED",
        "tm_coverage_pct": 0.00,
        "per_word_rate_cents": 5.00,
        "sla_days": 20,
        "parallel_job_limit": 1,
    }

    def test_publication_seeds_more_jobs_than_the_locale_ceiling_would_allow(
        self, api, localization_coordinator_headers
    ):
        """Two auto-created jobs land on a locale whose ceiling is one.

        PRD §3.6: "For each topic just taken live, and for each locale profile
        whose `status` is `ACTIVE` and whose `publication_mode` is `SIMULTANEOUS`
        — walked in `locale_code` ascending order — a translation job is
        auto-created in state `QUEUED` with `auto_created` set to true, reserving
        that topic's `latest_body_word_count` on that locale and carrying a
        provisional cost quote."

        PRD §3.6: "What *is* waived is the locale's parallelism ceiling:
        auto-created jobs bypass `parallel_job_limit` entirely."

        PRD §3.6: "Each auto-created job spans from the logical clock's date
        through that date plus the locale's `sla_days`, which makes its window
        exactly one day longer than the service-level period, so an auto-created
        job never carries a rush surcharge."

        Design: Difficulty/resource_temporal_overlap/locale_parallel_limit_over_closed_intervals_with_auto_created_bypass
        """
        set_clock(CLOCK)
        bundle = published_topics_context(
            topic_count=2,
            locales=[
                {
                    "publication_mode": "SIMULTANEOUS",
                    "tm_coverage_pct": 0.00,
                    "per_word_rate_cents": 8.00,
                    "sla_days": 15,
                    "parallel_job_limit": 1,
                }
            ],
            revision_overrides={"body_word_count": 1200},
        )
        locale = bundle["locale_profiles"][0]

        assert bundle["doc_set"]["published_topic_count"] == 2
        # Two live 1200-word pages give a publishable volume of 2400 words, and
        # the single participating locale contributes 2400 * 8.00 = 19,200 cents.
        assert bundle["doc_set"]["projected_localization_budget_cents"] == 19200

        rows, meta = validate_list(
            api.list_localization_jobs(
                localization_coordinator_headers, {"locale_profile_id": locale["id"]}
            )
        )
        assert meta["total_count"] == 2, "the ceiling of 1 did not hold back the cascade"
        assert sorted(row["topic_id"] for row in rows) == sorted(bundle["topic_ids"])
        for row in rows:
            assert row["auto_created"] is True
            assert row["state"] == "QUEUED"
            assert row["reserved_source_words"] == 1200
            # The window runs from 2026-08-01 through 2026-08-01 + 15 days, so its
            # 16 closed days exceed the 15-day service level surcharge-free.
            assert row["window_start_date"] == "2026-08-01"
            assert row["window_end_date"] == "2026-08-16"
            assert row["estimated_cost_cents"] == 9600
            assert expected_quote(
                1200, 0, 8.00, "2026-08-01", "2026-08-16", 15
            )["rush_surcharge_cents"] == 0

        locale_after = read_locale_profile(locale["id"])
        assert_committed_source_words(locale_after, 2400)
        assert locale_after["open_job_count"] == 2
        assert locale_after["parallel_job_limit"] == 1
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 19200)

    def test_two_windows_touching_on_a_single_day_exhaust_the_ceiling(
        self, api, localization_coordinator_headers
    ):
        """A manual job whose window shares only 2026-08-10 is refused, not queued.

        PRD §3.8: "Finally the locale's parallelism ceiling: count the locale's
        open jobs whose closed `[window_start_date, window_end_date]` interval
        intersects the requested closed interval, and reject with
        `ERR_LOCALE_PARALLEL_JOB_LIMIT_EXCEEDED` when that count has already
        reached `parallel_job_limit`."

        PRD §3.8: "Because these intervals are closed, two windows that touch on
        a single shared date do intersect — the opposite of the half-open writer
        windows of §3.2 — and jobs the publication cascade auto-created bypass
        this ceiling entirely."

        Design: Difficulty/resource_temporal_overlap/locale_parallel_limit_over_closed_intervals_with_auto_created_bypass
        """
        set_clock(CLOCK)
        bundle = published_topics_context(
            topic_count=2, revision_overrides={"body_word_count": 1200}
        )
        locale = create_locale_profile(**self.NARROW_LOCALE)
        first = create_localization_job(
            bundle["topic_ids"][0],
            locale["id"],
            window_start_date="2026-08-05",
            window_end_date="2026-08-10",
        )
        assert first["state"] == "QUEUED"

        response = api.create_localization_job(
            create_localization_job_payload(
                bundle["topic_ids"][1],
                locale["id"],
                window_start_date="2026-08-10",
                window_end_date="2026-08-15",
            ),
            localization_coordinator_headers,
        )
        validate_error(response, ApiErrorId.LOCALE_PARALLEL_JOB_LIMIT_EXCEEDED, 409)

        unchanged = read_locale_profile(locale["id"])
        assert_committed_source_words(unchanged, 1200)
        assert unchanged["open_job_count"] == 1
        _, meta = validate_list(
            api.list_localization_jobs(
                localization_coordinator_headers, {"locale_profile_id": locale["id"]}
            )
        )
        assert meta["total_count"] == 1

    def test_a_window_opening_the_day_after_clears_the_ceiling(
        self, api, localization_coordinator_headers
    ):
        """Moving the requested window one day later leaves the intervals disjoint.

        PRD §3.8: "Finally the locale's parallelism ceiling: count the locale's
        open jobs whose closed `[window_start_date, window_end_date]` interval
        intersects the requested closed interval, and reject with
        `ERR_LOCALE_PARALLEL_JOB_LIMIT_EXCEEDED` when that count has already
        reached `parallel_job_limit`."

        PRD §3.8: "A manual **translation job** is queued by a
        `LocalizationCoordinator` against a `topic_id` and a `locale_profile_id`
        over a closed calendar window given by `window_start_date` and
        `window_end_date`."

        Design: Difficulty/resource_temporal_overlap/locale_parallel_limit_over_closed_intervals_with_auto_created_bypass
        """
        set_clock(CLOCK)
        bundle = published_topics_context(
            topic_count=2, revision_overrides={"body_word_count": 1200}
        )
        locale = create_locale_profile(**self.NARROW_LOCALE)
        create_localization_job(
            bundle["topic_ids"][0],
            locale["id"],
            window_start_date="2026-08-05",
            window_end_date="2026-08-10",
        )

        job = validate_success(
            api.create_localization_job(
                create_localization_job_payload(
                    bundle["topic_ids"][1],
                    locale["id"],
                    window_start_date="2026-08-11",
                    window_end_date="2026-08-15",
                ),
                localization_coordinator_headers,
            ),
            201,
        )

        assert job["state"] == "QUEUED"
        assert job["window_start_date"] == "2026-08-11"
        assert job["reserved_source_words"] == 1200
        after = read_locale_profile(locale["id"])
        assert_committed_source_words(after, 2400)
        assert after["open_job_count"] == 2


class TestDeliveryStateIsCheckedBeforeTheServiceLevel:
    """When a stale delivery is both aimed at a closed job and hopelessly late,
    the state error wins and the breach is never reported."""

    #: A four-day window against a ten-day service level, so the provisional quote
    #: carries a rush surcharge and the grace period expires on 2026-08-08.
    SHORT_LOCALE = {
        "publication_mode": "DELAYED",
        "tm_coverage_pct": 0.00,
        "per_word_rate_cents": 10.00,
        "sla_days": 10,
        "parallel_job_limit": 5,
    }
    SHORT_WINDOW = {"window_start_date": "2026-08-02", "window_end_date": "2026-08-05"}
    LATE_CLOCK = "2026-09-01T09:00:00Z"

    def test_a_stale_delivery_aimed_at_a_cancelled_job_reports_the_state_error(
        self, api, localization_coordinator_headers
    ):
        """Both gates fail; the job-state gate is the one the caller hears about.

        PRD §3.8: "The job's `state` must be `QUEUED` or `REWORK_REQUESTED`, else
        `ERR_LOCALIZATION_JOB_NOT_DELIVERABLE` — and this state test runs
        **before** the service-level test, so a stale delivery aimed at an
        already-published or cancelled job reports the state error and never a
        breach."

        PRD §2.5: "A localization job in a terminal state reports its state error
        and never a service-level breach."

        Design: Difficulty/priority_pair_validation_conflict/localization_job_state_check_beats_sla_breach_rejected
        """
        set_clock(CLOCK)
        bundle = queued_job_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(self.SHORT_LOCALE),
            **self.SHORT_WINDOW,
        )
        # 1200 words at 10.00 give 12,000 cents of base cost, and the four-day
        # window against a ten-day service level adds 1,800, for 13,800.
        assert bundle["job"]["estimated_cost_cents"] == 13800
        cancel_localization_job(
            bundle["job_id"], cancel_reason="scope withdrawn by the coordinator"
        )
        set_clock(self.LATE_CLOCK)

        response = api.deliver_localization_job(
            bundle["job_id"],
            deliver_localization_job_payload(
                translated_word_count=1200, tm_matched_word_count=0
            ),
            localization_coordinator_headers,
        )
        validate_error(response, ApiErrorId.LOCALIZATION_JOB_NOT_DELIVERABLE, 409)

        job = read_localization_job(bundle["job_id"])
        assert job["state"] == "CANCELLED"
        assert job["cost_variant"] == "PROVISIONAL"
        assert job["translated_word_count"] is None
        assert job["final_cost_cents"] is None
        assert job["estimated_cost_cents"] == 13800
        locale = read_locale_profile(bundle["locale_id"])
        assert_committed_source_words(locale, 0)
        assert locale["open_job_count"] == 0
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 0)

    def test_the_same_late_delivery_on_an_open_job_does_report_the_breach(
        self, api, localization_coordinator_headers
    ):
        """With the state gate satisfied the service-level gate is the one that fires.

        PRD §3.8: "The service-level test then requires that the logical clock's
        date is on or before `window_end_date` plus a three-day grace period; a
        delivery arriving later than that is refused outright with
        `ERR_LOCALIZATION_SLA_BREACH` rather than repriced."

        PRD §3.8: "Recording a delivery moves the job from `QUEUED` to
        `TRANSLATED`, or from `REWORK_REQUESTED` back to `TRANSLATED` to close the
        rework loop."

        Design: Difficulty/priority_pair_validation_conflict/localization_job_state_check_beats_sla_breach_rejected
        """
        set_clock(CLOCK)
        bundle = queued_job_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(self.SHORT_LOCALE),
            **self.SHORT_WINDOW,
        )
        set_clock(self.LATE_CLOCK)

        response = api.deliver_localization_job(
            bundle["job_id"],
            deliver_localization_job_payload(
                translated_word_count=1200, tm_matched_word_count=0
            ),
            localization_coordinator_headers,
        )
        validate_error(response, ApiErrorId.LOCALIZATION_SLA_BREACH, 409)

        job = read_localization_job(bundle["job_id"])
        assert job["state"] == "QUEUED"
        assert job["cost_variant"] == "PROVISIONAL"
        assert job["final_cost_cents"] is None
        assert job["estimated_cost_cents"] == 13800
        locale = read_locale_profile(bundle["locale_id"])
        assert_committed_source_words(locale, 1200)
        assert locale["open_job_count"] == 1
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 13800)


class TestDeliveryGraceWindow:
    """The service-level test allows three days past the window's end, inclusive."""

    #: Zero advertised coverage at 10.00 a word on a fourteen-day service level,
    #: quoted over a 21-day window so no surcharge muddies the two figures.
    GRACE_LOCALE = {
        "publication_mode": "SIMULTANEOUS",
        "tm_coverage_pct": 0.00,
        "per_word_rate_cents": 10.00,
        "sla_days": 14,
        "parallel_job_limit": 5,
    }
    GRACE_WINDOW = {"window_start_date": "2026-08-05", "window_end_date": "2026-08-25"}

    def test_delivery_on_the_final_grace_day_is_accepted_and_switches_the_ledger(
        self, api, localization_coordinator_headers
    ):
        """2026-08-28 is exactly the last day the comparison admits.

        PRD §3.8: "The service-level test then requires that the logical clock's
        date is on or before `window_end_date` plus a three-day grace period; a
        delivery arriving later than that is refused outright with
        `ERR_LOCALIZATION_SLA_BREACH` rather than repriced."

        PRD §3.8: "A release train's `localization_committed_cents` sums, over the
        jobs in that same open-state set whose topic belongs to the train through
        its plan item, each job's `final_cost_cents` when its `cost_variant` is
        `FINAL` and its `estimated_cost_cents` otherwise — so a delivered job
        visibly switches which of its two costs the train's ledger counts."

        Design: Corner/validations/localization_delivery_on_the_last_grace_day_accepted
        """
        set_clock(CLOCK)
        bundle = queued_job_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(self.GRACE_LOCALE),
            **self.GRACE_WINDOW,
        )
        assert bundle["job"]["estimated_cost_cents"] == 12000
        set_clock("2026-08-28T09:00:00Z")

        job = validate_success(
            api.deliver_localization_job(
                bundle["job_id"],
                deliver_localization_job_payload(
                    translated_word_count=1300, tm_matched_word_count=780
                ),
                localization_coordinator_headers,
            )
        )

        # 780 matches on 1300 words is 60.00% leverage; 1300 - floor(0.70 * 780)
        # = 754 effective words at 10.00 give 7,540 cents, and the 21-day window
        # keeps the surcharge at zero.
        assert job["state"] == "TRANSLATED"
        assert job["cost_variant"] == "FINAL"
        assert job["leverage_pct"] == pytest.approx(60.00, abs=0.01)
        assert job["final_cost_cents"] == 7540
        assert job["rush_surcharge_cents"] == 0
        assert job["estimated_cost_cents"] == 12000
        assert expected_quote(1300, 780, 10.00, "2026-08-05", "2026-08-25", 14)["cost_cents"] == 7540

        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 7540)
        locale = read_locale_profile(bundle["locale_id"])
        assert_committed_source_words(locale, 1200)
        assert locale["open_job_count"] == 1

    def test_delivery_one_day_past_the_grace_window_is_refused_outright(
        self, api, localization_coordinator_headers
    ):
        """2026-08-29 is refused rather than repriced, and the ledger stays provisional.

        PRD §3.8: "The service-level test then requires that the logical clock's
        date is on or before `window_end_date` plus a three-day grace period; a
        delivery arriving later than that is refused outright with
        `ERR_LOCALIZATION_SLA_BREACH` rather than repriced."

        PRD §3.8: "Its result is written to `final_cost_cents` with `cost_variant`
        set to `FINAL`, and `estimated_cost_cents` is deliberately **left intact**
        so both numbers remain observable on one row."

        Design: Corner/validations/localization_delivery_one_day_past_the_grace_window_rejected
        """
        set_clock(CLOCK)
        bundle = queued_job_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(self.GRACE_LOCALE),
            **self.GRACE_WINDOW,
        )
        set_clock("2026-08-29T09:00:00Z")

        response = api.deliver_localization_job(
            bundle["job_id"],
            deliver_localization_job_payload(
                translated_word_count=1300, tm_matched_word_count=780
            ),
            localization_coordinator_headers,
        )
        validate_error(response, ApiErrorId.LOCALIZATION_SLA_BREACH, 409)

        job = read_localization_job(bundle["job_id"])
        assert job["state"] == "QUEUED"
        assert job["cost_variant"] == "PROVISIONAL"
        assert job["translated_word_count"] is None
        assert job["tm_matched_word_count"] is None
        assert job["final_cost_cents"] is None
        assert job["estimated_cost_cents"] == 12000
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 12000)


class TestLocaleAvailabilityAndJobStateGates:
    """Four refusals that all sit behind a live source page: a paused locale, a
    second open job for the same page, rework before any delivery, and a second
    cancellation."""

    ACTIVE_LOCALE = {
        "publication_mode": "DELAYED",
        "tm_coverage_pct": 0.00,
        "per_word_rate_cents": 10.00,
        "sla_days": 14,
        "parallel_job_limit": 5,
    }
    FIRST_WINDOW = {"window_start_date": "2026-08-01", "window_end_date": "2026-08-20"}
    SECOND_WINDOW = {"window_start_date": "2026-08-02", "window_end_date": "2026-08-21"}
    THIRD_WINDOW = {"window_start_date": "2026-08-03", "window_end_date": "2026-08-22"}
    CANCEL_REASON = "Locale deprioritised for this release"

    def test_a_paused_locale_accepts_no_new_translation_work(
        self, api, localization_coordinator_headers
    ):
        """The page is live, so the refusal is about the locale and not the topic.

        PRD §3.8: "The locale profile's `status` must be `ACTIVE`, else
        `ERR_LOCALE_PAUSED`."

        PRD §3.8: "An optional `status` of `ACTIVE` or `PAUSED` defaults to
        `ACTIVE`; a paused locale accepts no new jobs and is skipped entirely by
        publication cascades."

        Design: Corner/errors/paused_locale_duplicate_job_and_job_state_gates_rejected
        """
        set_clock(CLOCK)
        bundle = published_topic_context(revision_overrides={"body_word_count": 1200})
        paused = create_locale_profile(
            status="PAUSED",
            publication_mode="SIMULTANEOUS",
            tm_coverage_pct=0.00,
            per_word_rate_cents=10.00,
            sla_days=14,
            parallel_job_limit=5,
        )
        assert paused["status"] == "PAUSED"
        assert read_topic(bundle["topic_id"])["publication_state"] == "PUBLISHED"

        response = api.create_localization_job(
            create_localization_job_payload(
                bundle["topic_id"], paused["id"], **self.FIRST_WINDOW
            ),
            localization_coordinator_headers,
        )
        validate_error(response, ApiErrorId.LOCALE_PAUSED, 409)

        unchanged = read_locale_profile(paused["id"])
        assert_committed_source_words(unchanged, 0)
        assert unchanged["open_job_count"] == 0
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 0)

    def test_a_queued_job_can_be_neither_reworked_nor_duplicated(
        self, api, localization_coordinator_headers
    ):
        """Rework demands a delivery, and one open job per page and locale is the limit.

        PRD §3.8: "Bouncing a delivery back to the vendor moves the job from
        `TRANSLATED` to `REWORK_REQUESTED` and increases `rework_count` by 1; a job
        in any other state is refused with `ERR_LOCALIZATION_JOB_NOT_TRANSLATED`."

        PRD §3.8: "The topic must have no non-terminal job for that same locale
        already, else `ERR_DUPLICATE_LOCALIZATION_JOB`."

        Design: Corner/errors/paused_locale_duplicate_job_and_job_state_gates_rejected
        """
        set_clock(CLOCK)
        bundle = published_topic_context(revision_overrides={"body_word_count": 1200})
        locale = create_locale_profile(**self.ACTIVE_LOCALE)
        first = create_localization_job(
            bundle["topic_id"], locale["id"], **self.FIRST_WINDOW
        )
        assert first["state"] == "QUEUED"

        bounce = api.rework_localization_job(
            first["id"], {}, localization_coordinator_headers
        )
        validate_error(bounce, ApiErrorId.LOCALIZATION_JOB_NOT_TRANSLATED, 409)
        assert read_localization_job(first["id"])["rework_count"] == 0
        assert read_localization_job(first["id"])["state"] == "QUEUED"

        duplicate = api.create_localization_job(
            create_localization_job_payload(
                bundle["topic_id"], locale["id"], **self.SECOND_WINDOW
            ),
            localization_coordinator_headers,
        )
        validate_error(duplicate, ApiErrorId.DUPLICATE_LOCALIZATION_JOB, 409)

        locale_after = read_locale_profile(locale["id"])
        assert_committed_source_words(locale_after, 1200)
        assert locale_after["open_job_count"] == 1
        _, meta = validate_list(
            api.list_localization_jobs(
                localization_coordinator_headers,
                {"topic_id": bundle["topic_id"], "locale_profile_id": locale["id"]},
            )
        )
        assert meta["total_count"] == 1

    def test_a_cancelled_job_cannot_be_cancelled_twice_but_stops_blocking_a_successor(
        self, api, localization_coordinator_headers
    ):
        """The duplicate rule counts only non-terminal jobs, so a replacement is allowed.

        PRD §3.8: "Cancelling has the same balance effect and is available from
        `QUEUED`, `TRANSLATED`, `REWORK_REQUESTED`, or `SCHEDULED_DELAYED`; a job
        that is already `PUBLISHED_LOCALIZED` or `CANCELLED` is refused with
        `ERR_LOCALIZATION_JOB_NOT_CANCELLABLE`."

        PRD §3.8: "The topic must have no non-terminal job for that same locale
        already, else `ERR_DUPLICATE_LOCALIZATION_JOB`."

        Design: Corner/errors/paused_locale_duplicate_job_and_job_state_gates_rejected
        """
        set_clock(CLOCK)
        bundle = published_topic_context(revision_overrides={"body_word_count": 1200})
        locale = create_locale_profile(**self.ACTIVE_LOCALE)
        first = create_localization_job(
            bundle["topic_id"], locale["id"], **self.FIRST_WINDOW
        )
        cancel_localization_job(first["id"], cancel_reason=self.CANCEL_REASON)

        response = api.cancel_localization_job(
            first["id"],
            cancel_localization_job_payload(cancel_reason="Cancelling again"),
            localization_coordinator_headers,
        )
        validate_error(response, ApiErrorId.LOCALIZATION_JOB_NOT_CANCELLABLE, 409)
        assert read_localization_job(first["id"])["cancel_reason"] == self.CANCEL_REASON

        rows, meta = validate_list(
            api.list_localization_jobs(
                localization_coordinator_headers,
                {"topic_id": bundle["topic_id"], "locale_profile_id": locale["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["state"] == "CANCELLED"

        replacement = validate_success(
            api.create_localization_job(
                create_localization_job_payload(
                    bundle["topic_id"], locale["id"], **self.THIRD_WINDOW
                ),
                localization_coordinator_headers,
            ),
            201,
        )

        assert replacement["state"] == "QUEUED"
        assert replacement["id"] != first["id"]
        locale_after = read_locale_profile(locale["id"])
        assert_committed_source_words(locale_after, 1200)
        assert locale_after["open_job_count"] == 1


class TestSimultaneousBranchNeedsAGenerallyAvailableTrain:
    """The simultaneous branch adds one condition the delayed branch never
    consults, and taking it releases the locale's reservation."""

    SIMULTANEOUS_LOCALE = {
        "publication_mode": "SIMULTANEOUS",
        "tm_coverage_pct": 0.00,
        "per_word_rate_cents": 10.00,
        "sla_days": 14,
        "parallel_job_limit": 5,
    }
    JOB_WINDOW = {"window_start_date": "2026-08-05", "window_end_date": "2026-08-25"}
    DELIVERY = {"translated_word_count": 1300, "tm_matched_word_count": 780}

    def test_localized_publication_is_refused_while_the_release_is_not_yet_general(
        self, api, localization_coordinator_headers
    ):
        """A delivered translation waits for the train, and nothing on the job moves.

        PRD §3.8: "On the **simultaneous branch** — taken when the locale's
        `publication_mode` is `SIMULTANEOUS` — the release train's `status` must
        additionally be `GA` or `MAINTENANCE`, else `ERR_TRAIN_NOT_GA`; the job
        then moves `TRANSLATED → PUBLISHED_LOCALIZED` with `published_at` stamped
        from the logical clock, `publication_mode_applied` set to `SIMULTANEOUS`,
        and `scheduled_publish_date` left null."

        Design: Corner/endpoints/simultaneous_localized_publish_conditional_on_train_ga
        """
        set_clock(CLOCK)
        bundle = translated_job_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(self.SIMULTANEOUS_LOCALE),
            delivery_overrides=dict(self.DELIVERY),
            **self.JOB_WINDOW,
        )
        assert bundle["job"]["final_cost_cents"] == 7540
        assert read_release_train(bundle["train_id"])["status"] == "PLANNED"

        response = api.publish_localization_job(
            bundle["job_id"], {}, localization_coordinator_headers
        )
        validate_error(response, ApiErrorId.TRAIN_NOT_GA, 409)

        job = read_localization_job(bundle["job_id"])
        assert job["state"] == "TRANSLATED"
        assert job["publication_mode_applied"] is None
        assert job["published_at"] is None
        locale = read_locale_profile(bundle["locale_id"])
        assert_committed_source_words(locale, 1200)
        assert locale["open_job_count"] == 1
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 7540)

    def test_the_same_publication_succeeds_once_the_release_goes_generally_available(
        self, api, localization_coordinator_headers
    ):
        """The accepted call takes the simultaneous branch and computes no schedule.

        PRD §3.8: "On the **simultaneous branch** — taken when the locale's
        `publication_mode` is `SIMULTANEOUS` — the release train's `status` must
        additionally be `GA` or `MAINTENANCE`, else `ERR_TRAIN_NOT_GA`; the job
        then moves `TRANSLATED → PUBLISHED_LOCALIZED` with `published_at` stamped
        from the logical clock, `publication_mode_applied` set to `SIMULTANEOUS`,
        and `scheduled_publish_date` left null."

        PRD §3.8: "Whenever a job reaches `PUBLISHED_LOCALIZED`, by either branch,
        it leaves the locale's active set: `committed_source_words` decreases by
        `reserved_source_words`, `open_job_count` decreases by 1, and the train's
        `localization_committed_cents` is recomputed."

        Design: Corner/endpoints/simultaneous_localized_publish_conditional_on_train_ga
        """
        set_clock(CLOCK)
        bundle = translated_job_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(self.SIMULTANEOUS_LOCALE),
            delivery_overrides=dict(self.DELIVERY),
            **self.JOB_WINDOW,
        )
        validate_error(
            api.publish_localization_job(bundle["job_id"], {}, localization_coordinator_headers),
            ApiErrorId.TRAIN_NOT_GA,
            409,
        )
        advance_train(bundle["train_id"], "DOC_FREEZE")
        assert advance_train(bundle["train_id"], "GA")["status"] == "GA"

        job = validate_success(
            api.publish_localization_job(
                bundle["job_id"], {}, localization_coordinator_headers
            )
        )

        assert job["state"] == "PUBLISHED_LOCALIZED"
        assert job["publication_mode_applied"] == "SIMULTANEOUS"
        assert job["scheduled_publish_date"] is None
        assert instants_equal(job["published_at"], CLOCK)
        assert job["final_cost_cents"] == 7540, "publication does not requote"
        assert job["cost_variant"] == "FINAL"

        locale = read_locale_profile(bundle["locale_id"])
        assert_committed_source_words(locale, 0)
        assert locale["open_job_count"] == 0
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 0)
