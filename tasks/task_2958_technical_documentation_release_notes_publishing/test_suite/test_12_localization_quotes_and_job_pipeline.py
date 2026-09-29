"""Vendor cost quotes and the shape of the translation pipeline.

Every translation job is priced twice — provisionally from the locale's
advertised memory coverage when the job is queued, and finally from the
vendor's measured leverage when the words come back — and both figures stay
observable on one row.  This module also walks the pipeline's non-linear parts:
the rework cycle that returns a delivery to the vendor, the delayed branch that
parks a job on a computed date, and the word reservation a locale carries from
job creation through to cancellation.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_committed_source_words,
    assert_localization_committed_cents,
    assert_localization_job,
    cancel_localization_job_payload,
    create_localization_job_payload,
    date_of_instant,
    deliver_localization_job_payload,
    expected_provisional_memory_words,
    expected_quote,
    instants_equal,
    localization_context,
    queued_job_context,
    read_locale_profile,
    read_localization_job,
    read_release_train,
    read_topic,
    scheduled_delayed_job_context,
    set_clock,
    set_clock_date,
    translated_job_context,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"

#: A locale that advertises 40% memory coverage at 12.50 cents a word on a
#: ten-day service level, quoted over an eight-day window so the rush surcharge
#: is live.
RUSHED_LOCALE = {
    "publication_mode": "SIMULTANEOUS",
    "tm_coverage_pct": 40.00,
    "per_word_rate_cents": 12.50,
    "sla_days": 10,
    "parallel_job_limit": 5,
}
RUSHED_WINDOW = {"window_start_date": "2026-08-10", "window_end_date": "2026-08-17"}


class TestProvisionalAndFinalQuoteVariants:
    """One job carries two quotes: the provisional one struck when the job is
    queued and the final one struck when the delivery is recorded."""

    def test_queuing_a_job_quotes_the_provisional_cost_from_the_advertised_coverage(
        self, api, localization_coordinator_headers
    ):
        """The provisional quote reads the locale's advertised coverage, not the vendor's.

        PRD §3.8: "Its source volume is `reserved_source_words` — the topic's
        word count pinned at creation — and its memory volume is that source
        volume multiplied by the locale's advertised `tm_coverage_pct` divided by
        100, with any fraction discarded downwards."

        PRD §3.8: "Fifth, the window length in days is the number of days from
        `window_start_date` to `window_end_date` plus one, because the interval
        is closed; when that window length is strictly shorter than the locale's
        `sla_days`, `rush_surcharge_cents` is fifteen percent of the base cost
        rounded half up to whole cents, and otherwise it is 0."

        PRD §3.8: "Its result is written to `estimated_cost_cents` with
        `cost_variant` set to `PROVISIONAL`."

        Design: Difficulty/dual_variant_calc/localization_cost_provisional_versus_final_on_one_job
        """
        set_clock(CLOCK)
        bundle = localization_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(RUSHED_LOCALE),
        )
        payload = create_localization_job_payload(
            bundle["topic_id"], bundle["locale_id"], **RUSHED_WINDOW
        )

        job = validate_success(
            api.create_localization_job(payload, localization_coordinator_headers), 201
        )

        assert_localization_job(job)
        assert job["state"] == "QUEUED"
        assert job["auto_created"] is False
        assert job["source_revision_number"] == 1
        assert job["reserved_source_words"] == 1200
        assert job["cost_variant"] == "PROVISIONAL"
        assert job["final_cost_cents"] is None
        assert job["translated_word_count"] is None
        # 1200 reserved words at 40.00% advertised coverage give 480 memory words;
        # 1200 - floor(0.70 * 480) = 864 effective words; 864 * 12.50 = 10,800 cents
        # of base cost; the closed window spans 8 days against a 10-day service
        # level, so the surcharge is 1,620 cents; 12,420 clears no discount band.
        assert expected_provisional_memory_words(1200, 40.00) == 480
        quote = expected_quote(1200, 480, 12.50, "2026-08-10", "2026-08-17", 10)
        assert quote["effective_word_count"] == 864
        assert quote["base_cost_cents"] == 10800
        assert quote["window_length_days"] == 8
        assert quote["rush_surcharge_cents"] == 1620
        assert quote["volume_discount_cents"] == 0
        assert quote["cost_cents"] == 12420
        assert job["estimated_cost_cents"] == 12420

        locale = read_locale_profile(bundle["locale_id"])
        assert_committed_source_words(locale, 1200)
        assert locale["open_job_count"] == 1
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 12420)

    def test_recording_the_delivery_requotes_the_job_from_the_measured_leverage(
        self, api, localization_coordinator_headers
    ):
        """The final quote replaces the provisional inputs and leaves the estimate alone.

        PRD §3.8: "Its source volume is `translated_word_count` as actually
        delivered and its memory volume is `tm_matched_word_count` as actually
        measured."

        PRD §3.8: "Its result is written to `final_cost_cents` with
        `cost_variant` set to `FINAL`, and `estimated_cost_cents` is deliberately
        **left intact** so both numbers remain observable on one row."

        PRD §3.8: "On success the two word counts are stored and `leverage_pct`,
        `rush_surcharge_cents`, `volume_discount_cents`, and `final_cost_cents`
        are all recomputed under the final variant with `cost_variant` set to
        `FINAL`; the train's `localization_committed_cents` now counts this job's
        final figure in place of its provisional one."

        Design: Difficulty/dual_variant_calc/localization_cost_provisional_versus_final_on_one_job
        """
        set_clock(CLOCK)
        bundle = queued_job_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(RUSHED_LOCALE),
            **RUSHED_WINDOW,
        )
        assert bundle["job"]["estimated_cost_cents"] == 12420

        job = validate_success(
            api.deliver_localization_job(
                bundle["job_id"],
                deliver_localization_job_payload(
                    translated_word_count=1300, tm_matched_word_count=780
                ),
                localization_coordinator_headers,
            )
        )

        assert job["state"] == "TRANSLATED"
        assert job["cost_variant"] == "FINAL"
        assert job["translated_word_count"] == 1300
        assert job["tm_matched_word_count"] == 780
        # 780 measured matches on 1300 delivered words is 60.00% leverage;
        # 1300 - floor(0.70 * 780) = 754 effective words; 754 * 12.50 = 9,425 cents
        # of base cost; the same 8-day window adds 15% = 1,413.75 rounded half up
        # to 1,414 cents, for a final 10,839 cents.
        final = expected_quote(1300, 780, 12.50, "2026-08-10", "2026-08-17", 10)
        assert final["effective_word_count"] == 754
        assert final["base_cost_cents"] == 9425
        assert final["rush_surcharge_cents"] == 1414
        assert final["cost_cents"] == 10839
        assert job["leverage_pct"] == pytest.approx(60.00, abs=0.01)
        assert job["rush_surcharge_cents"] == 1414
        assert job["volume_discount_cents"] == 0
        assert job["final_cost_cents"] == 10839
        assert job["estimated_cost_cents"] == 12420

        locale = read_locale_profile(bundle["locale_id"])
        assert_committed_source_words(locale, 1200)
        assert locale["open_job_count"] == 1, "delivery does not release the reservation"
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 10839)

    def test_a_word_for_word_delivery_still_diverges_from_the_provisional_quote(
        self, api, localization_coordinator_headers
    ):
        """Delivering exactly the reserved volume with no matches costs more, not the same.

        PRD §3.8: "A delivery that matches the reservation word-for-word still
        diverges from the provisional quote whenever the measured leverage
        differs from the locale's advertised coverage."

        PRD §3.8: "Second, `leverage_pct` is `0.00` when the source volume is
        zero, and otherwise the memory volume multiplied by 100 and divided by
        the source volume, rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/localization_cost_provisional_versus_final_on_one_job
        """
        set_clock(CLOCK)
        bundle = queued_job_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(RUSHED_LOCALE),
            **RUSHED_WINDOW,
        )

        job = validate_success(
            api.deliver_localization_job(
                bundle["job_id"],
                deliver_localization_job_payload(
                    translated_word_count=1200, tm_matched_word_count=0
                ),
                localization_coordinator_headers,
            )
        )

        # The same 1200 words, but zero measured matches: 1200 effective words at
        # 12.50 give 15,000 cents of base cost, the 8-day window adds 2,250, and
        # the final 17,250 cents exceeds the 12,420 the locale's advertised 40%
        # coverage had promised.
        assert job["leverage_pct"] == pytest.approx(0.00, abs=0.01)
        assert job["final_cost_cents"] == 17250
        assert job["estimated_cost_cents"] == 12420
        assert job["final_cost_cents"] > job["estimated_cost_cents"]
        assert expected_quote(1200, 0, 12.50, "2026-08-10", "2026-08-17", 10)["cost_cents"] == 17250
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 17250)


class TestSurchargeIsAppliedBeforeTheVolumeDiscount:
    """The rush surcharge enters the subtotal the discount band is chosen from, so
    the two adjustments are not commutative."""

    def test_the_volume_band_is_selected_from_the_surcharge_inclusive_subtotal(
        self, api, localization_coordinator_headers
    ):
        """A base cost in the 3% band lands in the 6% band once the surcharge is added.

        PRD §3.8: "Nine steps produce a job's cost, and their order is part of
        the contract because the rush surcharge is applied *before* the volume
        discount and the volume band is selected from the **surcharge-inclusive**
        subtotal."

        PRD §3.8: "Seventh, a discount percentage is selected from the subtotal
        by taking the first matching band in descending order: 10 percent when
        the subtotal is at least 500,000 cents, otherwise 6 percent when it is at
        least 200,000 cents, otherwise 3 percent when it is at least 50,000
        cents, and otherwise 0 percent; `volume_discount_cents` is that
        percentage of the subtotal, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/localization_cost_surcharge_before_volume_discount_mode_c
        """
        set_clock(CLOCK)
        bundle = localization_context(
            revision_overrides={"body_word_count": 15200},
            locale_overrides={
                "publication_mode": "SIMULTANEOUS",
                "tm_coverage_pct": 0.00,
                "per_word_rate_cents": 12.50,
                "sla_days": 10,
                "parallel_job_limit": 5,
            },
        )
        payload = create_localization_job_payload(
            bundle["topic_id"], bundle["locale_id"], **RUSHED_WINDOW
        )

        job = validate_success(
            api.create_localization_job(payload, localization_coordinator_headers), 201
        )

        # 15,200 effective words at 12.50 give 190,000 cents of base cost; the
        # 8-day window against a 10-day service level adds 28,500; the subtotal of
        # 218,500 clears the 200,000-cent band, so 6% = 13,110 comes off and the
        # quote is 205,390 cents.
        quote = expected_quote(15200, 0, 12.50, "2026-08-10", "2026-08-17", 10)
        assert quote["base_cost_cents"] == 190000
        assert quote["rush_surcharge_cents"] == 28500
        assert quote["subtotal_cents"] == 218500
        assert quote["volume_discount_pct"] == 6
        assert quote["volume_discount_cents"] == 13110
        assert quote["cost_cents"] == 205390
        assert job["reserved_source_words"] == 15200
        assert job["estimated_cost_cents"] == 205390
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 205390)

    def test_discounting_the_base_cost_before_the_surcharge_would_pick_a_lighter_band(
        self, api, localization_coordinator_headers
    ):
        """The surcharge is what carries this job over the 200,000-cent threshold.

        PRD §3.8: "Applying the discount to the base cost first and adding the
        surcharge afterwards would select a band from a different number and
        yield a different total, which is why the order is fixed."

        PRD §3.8: "Sixth, the subtotal is the base cost plus the surcharge."

        PRD §3.8: "Eighth and last, the cost is the subtotal minus the discount."

        Design: Difficulty/combinatorial_formula/localization_cost_surcharge_before_volume_discount_mode_c
        """
        set_clock(CLOCK)
        bundle = localization_context(
            revision_overrides={"body_word_count": 14000},
            locale_overrides={
                "publication_mode": "SIMULTANEOUS",
                "tm_coverage_pct": 0.00,
                "per_word_rate_cents": 12.50,
                "sla_days": 10,
                "parallel_job_limit": 5,
            },
        )
        payload = create_localization_job_payload(
            bundle["topic_id"], bundle["locale_id"], **RUSHED_WINDOW
        )

        job = validate_success(
            api.create_localization_job(payload, localization_coordinator_headers), 201
        )

        # 14,000 words at 12.50 give 175,000 cents of base cost, which on its own
        # sits in the 3% band; the 26,250-cent surcharge lifts the subtotal to
        # 201,250 and into the 6% band, so 12,075 comes off and the quote is
        # 189,175 cents.
        quote = expected_quote(14000, 0, 12.50, "2026-08-10", "2026-08-17", 10)
        assert quote["base_cost_cents"] == 175000
        assert quote["subtotal_cents"] == 201250
        assert quote["volume_discount_pct"] == 6
        assert quote["cost_cents"] == 189175
        assert job["estimated_cost_cents"] == 189175
        # Discounting the base cost first would pick the 3% band: 175,000 - 5,250
        # = 169,750, and adding the surcharge afterwards gives either 196,000 or,
        # if the surcharge is taken on the discounted base, 195,213.
        assert job["estimated_cost_cents"] != 196000
        assert job["estimated_cost_cents"] != 195213
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 189175)


class TestReworkCycleAndDelayedBranch:
    """The pipeline is not a straight line: a delivery can be bounced back to the
    vendor, and a delayed locale parks its page on a computed publication date
    before rejoining the others at ``PUBLISHED_LOCALIZED``."""

    #: A delayed locale on a ten-day lag, quoted over an eleven-day window so the
    #: window is never shorter than the service level and no surcharge applies.
    LAGGED_LOCALE = {
        "publication_mode": "DELAYED",
        "tm_coverage_pct": 40.00,
        "per_word_rate_cents": 10.00,
        "sla_days": 10,
        "parallel_job_limit": 5,
    }
    LAGGED_WINDOW = {"window_start_date": "2026-08-01", "window_end_date": "2026-08-11"}
    FIRST_DELIVERY = {"translated_word_count": 1250, "tm_matched_word_count": 500}

    def test_a_bounced_delivery_holds_its_old_figures_until_the_vendor_returns(
        self, api, localization_coordinator_headers
    ):
        """Rework counts the bounce, keeps the stale quote, and the redelivery replaces it.

        PRD §3.8: "Bouncing a delivery back to the vendor moves the job from
        `TRANSLATED` to `REWORK_REQUESTED` and increases `rework_count` by 1; a
        job in any other state is refused with
        `ERR_LOCALIZATION_JOB_NOT_TRANSLATED`."

        PRD §3.8: "The bounced delivery's `final_cost_cents` and `leverage_pct`
        stand unchanged until the next delivery overwrites them."

        PRD §3.8: "Recording a delivery moves the job from `QUEUED` to
        `TRANSLATED`, or from `REWORK_REQUESTED` back to `TRANSLATED` to close the
        rework loop."

        Design: Difficulty/non_linear_state_machine/localization_job_fork_join_via_delayed_branch_and_rework_cycle
        """
        set_clock(CLOCK)
        bundle = translated_job_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(self.LAGGED_LOCALE),
            delivery_overrides=dict(self.FIRST_DELIVERY),
            **self.LAGGED_WINDOW,
        )
        # 1200 reserved words at 40% coverage: 864 effective words at 10.00 give
        # 8,640 cents provisionally, with no surcharge on an 11-day window.
        assert bundle["job"]["estimated_cost_cents"] == 8640
        # 500 matches on 1250 delivered words: 900 effective words, 9,000 cents.
        assert bundle["job"]["final_cost_cents"] == 9000

        bounced = validate_success(
            api.rework_localization_job(bundle["job_id"], {}, localization_coordinator_headers)
        )

        assert bounced["state"] == "REWORK_REQUESTED"
        assert bounced["rework_count"] == 1
        assert bounced["cost_variant"] == "FINAL"
        assert bounced["final_cost_cents"] == 9000
        assert bounced["leverage_pct"] == pytest.approx(40.00, abs=0.01)

        redelivered = validate_success(
            api.deliver_localization_job(
                bundle["job_id"],
                deliver_localization_job_payload(
                    translated_word_count=1300, tm_matched_word_count=650
                ),
                localization_coordinator_headers,
            )
        )

        # 650 matches on 1300 words is 50.00% leverage; 1300 - floor(0.70 * 650)
        # = 845 effective words at 10.00 give a fresh final quote of 8,450 cents.
        assert redelivered["state"] == "TRANSLATED"
        assert redelivered["rework_count"] == 1, "closing the loop is not a second bounce"
        assert redelivered["leverage_pct"] == pytest.approx(50.00, abs=0.01)
        assert redelivered["final_cost_cents"] == 8450
        assert redelivered["estimated_cost_cents"] == 8640
        assert expected_quote(1300, 650, 10.00, "2026-08-01", "2026-08-11", 10)["cost_cents"] == 8450

        locale = read_locale_profile(bundle["locale_id"])
        assert_committed_source_words(locale, 1200)
        assert locale["open_job_count"] == 1
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 8450)

    def test_the_delayed_branch_parks_the_page_and_keeps_the_reservation(
        self, api, localization_coordinator_headers
    ):
        """Publishing a delayed locale computes a schedule and never consults the train.

        PRD §3.8: "On the **delayed branch** — taken when the locale's
        `publication_mode` is `DELAYED` — the train's status is **not** consulted
        at all, and the outcome depends on the clock."

        PRD §3.8: "When the logical clock's date is still earlier than the source
        topic's publication date plus the locale's `sla_days`, the job moves
        `TRANSLATED → SCHEDULED_DELAYED`: `scheduled_publish_date` is computed as
        the calendar date of the topic's `published_at` plus `sla_days` days,
        `publication_mode_applied` is set to `DELAYED`, `published_at` stays null,
        and — diverging from the simultaneous branch — the locale's reservation is
        **not** released."

        Design: Difficulty/non_linear_state_machine/localization_job_fork_join_via_delayed_branch_and_rework_cycle
        """
        set_clock(CLOCK)
        bundle = translated_job_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(self.LAGGED_LOCALE),
            delivery_overrides=dict(self.FIRST_DELIVERY),
            **self.LAGGED_WINDOW,
        )
        assert date_of_instant(read_topic(bundle["topic_id"])["published_at"]) == "2026-08-01"

        parked = validate_success(
            api.publish_localization_job(bundle["job_id"], {}, localization_coordinator_headers)
        )

        # The page went live on 2026-08-01 and the locale lags by 10 days, so the
        # schedule falls on 2026-08-11, which the clock has not reached.
        assert parked["state"] == "SCHEDULED_DELAYED"
        assert parked["publication_mode_applied"] == "DELAYED"
        assert parked["scheduled_publish_date"] == "2026-08-11"
        assert parked["published_at"] is None
        assert parked["final_cost_cents"] == 9000

        assert read_release_train(bundle["train_id"])["status"] == "PLANNED"
        locale = read_locale_profile(bundle["locale_id"])
        assert_committed_source_words(locale, 1200)
        assert locale["open_job_count"] == 1
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 9000)

    def test_the_parked_page_rejoins_the_others_once_its_schedule_arrives(
        self, api, localization_coordinator_headers
    ):
        """A second attempt on the scheduled day publishes and releases the reservation.

        PRD §3.8: "A later publication attempt on that parked job moves
        `SCHEDULED_DELAYED → PUBLISHED_LOCALIZED` once the logical clock's date
        has reached or passed `scheduled_publish_date`; before that date the job
        simply stays `SCHEDULED_DELAYED` and the response repeats it."

        PRD §3.8: "Whenever a job reaches `PUBLISHED_LOCALIZED`, by either
        branch, it leaves the locale's active set: `committed_source_words`
        decreases by `reserved_source_words`, `open_job_count` decreases by 1, and
        the train's `localization_committed_cents` is recomputed."

        Design: Difficulty/non_linear_state_machine/localization_job_fork_join_via_delayed_branch_and_rework_cycle
        """
        set_clock(CLOCK)
        bundle = scheduled_delayed_job_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(self.LAGGED_LOCALE),
            delivery_overrides=dict(self.FIRST_DELIVERY),
            **self.LAGGED_WINDOW,
        )
        assert bundle["job"]["state"] == "SCHEDULED_DELAYED"
        assert bundle["job"]["scheduled_publish_date"] == "2026-08-11"
        set_clock_date("2026-08-11")

        published = validate_success(
            api.publish_localization_job(bundle["job_id"], {}, localization_coordinator_headers)
        )

        assert published["state"] == "PUBLISHED_LOCALIZED"
        assert published["publication_mode_applied"] == "DELAYED"
        assert published["scheduled_publish_date"] == "2026-08-11"
        assert instants_equal(published["published_at"], "2026-08-11T00:00:00Z")
        assert published["final_cost_cents"] == 9000, "publication never requotes"
        assert published["cost_variant"] == "FINAL"

        locale = read_locale_profile(bundle["locale_id"])
        assert_committed_source_words(locale, 0)
        assert locale["open_job_count"] == 0
        train = read_release_train(bundle["train_id"])
        assert_localization_committed_cents(train, 0)
        assert train["status"] == "PLANNED", "the delayed branch never needed a GA train"


class TestReservationConservedAcrossCreateAndCancel:
    """A locale's committed word volume and the train's committed spend are one
    reservation seen twice, and a cancel must undo both in the same call."""

    LEDGER_LOCALE = {
        "publication_mode": "DELAYED",
        "tm_coverage_pct": 0.00,
        "per_word_rate_cents": 10.00,
        "sla_days": 10,
        "parallel_job_limit": 3,
    }
    LEDGER_WINDOW = {"window_start_date": "2026-08-01", "window_end_date": "2026-08-21"}
    CANCEL_REASON = "Locale dropped from this release"

    def test_queuing_a_job_charges_the_word_ledger_and_its_monetary_shadow(
        self, api, localization_coordinator_headers
    ):
        """One create moves both the locale's words and the train's cents off zero.

        PRD §3.8: "The locale's `committed_source_words` increases by
        `reserved_source_words`, its `open_job_count` increases by 1, and the
        owning release train's `localization_committed_cents` is recomputed."

        PRD §3.8: "A release train's `localization_committed_cents` sums, over the
        jobs in that same open-state set whose topic belongs to the train through
        its plan item, each job's `final_cost_cents` when its `cost_variant` is
        `FINAL` and its `estimated_cost_cents` otherwise — so a delivered job
        visibly switches which of its two costs the train's ledger counts."

        Design: Difficulty/compensating_invariant/locale_committed_source_words_conserved_across_job_create_cancel
        """
        set_clock(CLOCK)
        bundle = localization_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(self.LEDGER_LOCALE),
        )
        before_locale = read_locale_profile(bundle["locale_id"])
        assert_committed_source_words(before_locale, 0)
        assert before_locale["open_job_count"] == 0
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 0)

        job = validate_success(
            api.create_localization_job(
                create_localization_job_payload(
                    bundle["topic_id"], bundle["locale_id"], **self.LEDGER_WINDOW
                ),
                localization_coordinator_headers,
            ),
            201,
        )

        # 1200 words at zero advertised coverage: 1200 effective words at 10.00
        # give 12,000 cents, and the 21-day window is longer than the 10-day
        # service level, so no surcharge enters the quote.
        assert job["state"] == "QUEUED"
        assert job["cost_variant"] == "PROVISIONAL"
        assert job["reserved_source_words"] == 1200
        assert job["estimated_cost_cents"] == 12000
        assert expected_quote(1200, 0, 10.00, "2026-08-01", "2026-08-21", 10)["cost_cents"] == 12000

        locale = read_locale_profile(bundle["locale_id"])
        assert_committed_source_words(locale, 1200)
        assert locale["open_job_count"] == 1
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 12000)

    def test_cancelling_returns_both_ledgers_to_their_pre_create_values(
        self, api, localization_coordinator_headers
    ):
        """The compensating cancel releases the words and the cents in one call.

        PRD §2.8: "A create followed by its compensating cancel must return each
        affected ledger to precisely its pre-create value."

        PRD §3.8: "Cancelling has the same balance effect and is available from
        `QUEUED`, `TRANSLATED`, `REWORK_REQUESTED`, or `SCHEDULED_DELAYED`; a job
        that is already `PUBLISHED_LOCALIZED` or `CANCELLED` is refused with
        `ERR_LOCALIZATION_JOB_NOT_CANCELLABLE`."

        PRD §3.8: "A locale's `committed_source_words` is the sum of
        `reserved_source_words` over that locale's jobs whose state is `QUEUED`,
        `TRANSLATED`, `REWORK_REQUESTED`, or `SCHEDULED_DELAYED`, and
        `open_job_count` is the count of that same set; jobs that are
        `PUBLISHED_LOCALIZED` or `CANCELLED` are excluded."

        Design: Difficulty/compensating_invariant/locale_committed_source_words_conserved_across_job_create_cancel
        """
        set_clock(CLOCK)
        bundle = queued_job_context(
            revision_overrides={"body_word_count": 1200},
            locale_overrides=dict(self.LEDGER_LOCALE),
            **self.LEDGER_WINDOW,
        )
        assert bundle["job"]["estimated_cost_cents"] == 12000
        assert_committed_source_words(read_locale_profile(bundle["locale_id"]), 1200)
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 12000)

        cancelled = validate_success(
            api.cancel_localization_job(
                bundle["job_id"],
                cancel_localization_job_payload(cancel_reason=self.CANCEL_REASON),
                localization_coordinator_headers,
            )
        )

        assert cancelled["state"] == "CANCELLED"
        assert cancelled["cancel_reason"] == self.CANCEL_REASON
        # The row keeps its history: the reservation and the provisional quote are
        # still legible even though neither counts towards a ledger any more.
        assert cancelled["reserved_source_words"] == 1200
        assert cancelled["estimated_cost_cents"] == 12000

        locale = read_locale_profile(bundle["locale_id"])
        assert_committed_source_words(locale, 0)
        assert locale["open_job_count"] == 0
        assert_localization_committed_cents(read_release_train(bundle["train_id"]), 0)
        assert read_localization_job(bundle["job_id"])["state"] == "CANCELLED"
        assert read_topic(bundle["topic_id"])["publication_state"] == "PUBLISHED", (
            "cancelling a translation never touches the source page"
        )
