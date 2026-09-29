"""Reader ratings, the deflection window, and the two documentation-health variants.

Readers are the only anonymous participants in this system and they contribute
exactly one thing: a rating on a page they actually read.  Those ratings feed a
trailing thirty-day window whose aggregates are deliberately three-valued, and
the window in turn feeds the post-publication half of the page's health score.
This module covers the same page scored before and after it goes live, the two
empty boundaries of the window, and the gate that keeps ratings off a page no
reader could have seen.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_deflection_summary,
    assert_page_feedback,
    create_doc_set_version,
    create_feedback,
    create_feedback_payload,
    create_locale_profile,
    create_revision,
    decide_signoff,
    expected_deflection_window,
    expected_health_score,
    expected_mean_rating,
    expected_pct,
    feedback_context,
    publish_doc_set_version,
    read_topic,
    request_signoff,
    reviewer_pair,
    revised_topic_context,
    set_clock,
    set_clock_date,
    submit_topic,
    topic_context,
    validate_error,
    validate_list,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"
SUBMIT_DAY = "2026-08-05"
APPROVE_DAY = "2026-08-09"


def _churned_topic_approved_after_four_days() -> dict:
    """A topic carrying four source revisions, submitted on the fifth of August and
    fully approved on the ninth, so churn and latency are both non-zero."""
    bundle = topic_context()
    for _ in range(3):
        create_revision(bundle["topic_id"], bundle["writer_id"])
    set_clock_date(SUBMIT_DAY)
    create_revision(bundle["topic_id"], bundle["writer_id"])
    submit_topic(bundle["topic_id"], bundle["writer_id"])
    bundle.update(reviewer_pair())
    engineering = request_signoff(bundle["topic_id"], bundle["engineering_reviewer_id"])
    product = request_signoff(bundle["topic_id"], bundle["product_reviewer_id"])
    set_clock_date(APPROVE_DAY)
    decide_signoff(engineering["id"], bundle["engineering_reviewer_id"], "APPROVED")
    decide_signoff(product["id"], bundle["product_reviewer_id"], "APPROVED")
    bundle["topic"] = read_topic(bundle["topic_id"])
    return bundle


def _take_live(bundle: dict) -> dict:
    """Publish the bundle's train so its approved topic goes live, then register a
    locale profile a reader can name."""
    doc_set = create_doc_set_version(bundle["train_id"])
    publish_doc_set_version(doc_set["id"])
    locale = create_locale_profile()
    bundle.update(doc_set=doc_set, locale=locale, locale_code=locale["locale_code"])
    bundle["topic"] = read_topic(bundle["topic_id"])
    return bundle


class TestHealthScoreAcrossPublication:
    """The same churn and latency figures score differently once reader signals are
    allowed to enter the calculation."""

    def test_the_pre_publication_score_counts_only_churn_and_latency(self, api, docs_lead_headers):
        """Four revisions and a four-day review cost 8 and 2 points respectively.

        PRD §3.10: "The churn penalty is 4 points for each revision beyond the
        second — that is, 4 multiplied by the amount by which
        `current_revision_number` exceeds 2, or zero when it does not exceed 2."

        PRD §3.10: "The latency penalty is zero when `signoff_latency_days` is
        null, and otherwise 2 points for each day by which
        `signoff_latency_days` exceeds a three-day grace period, or zero when it
        does not exceed it."

        PRD §3.10: "The **pre-publication** variant applies while the page's
        `publication_state` is `UNPUBLISHED`, and is the variant used when a
        topic reaches `FULLY_APPROVED`."

        Design: Difficulty/dual_variant_calc/topic_health_score_pre_versus_post_publication
        """
        set_clock(CLOCK)
        bundle = _churned_topic_approved_after_four_days()

        topic = validate_success(api.get_topic(bundle["topic_id"], docs_lead_headers))

        assert topic["review_state"] == "FULLY_APPROVED"
        assert topic["publication_state"] == "UNPUBLISHED"
        assert topic["current_revision_number"] == 4
        assert topic["signoff_latency_days"] == 4
        assert topic["open_blocker_violations"] == 0
        assert topic["open_warning_violations"] == 0
        assert topic["health_score_variant"] == "PRE_PUBLICATION"
        assert topic["health_score"] == pytest.approx(90.00, abs=0.01)
        assert topic["health_score"] == pytest.approx(
            expected_health_score(4, 0, 0, 4, variant="PRE_PUBLICATION"), abs=0.01
        )

    def test_publication_switches_the_variant_without_moving_an_unrated_score(
        self, api, docs_lead_headers
    ):
        """With an empty window the post-publication figure equals the
        pre-publication one, and only the variant label changes.

        PRD §3.10: "A consequence worth internalizing: a published page with no
        feedback inside the window scores exactly what it scored before
        publication, while reporting `health_score_variant` as
        `POST_PUBLICATION`."

        PRD §3.10: "The rating penalty is zero when the deflection window's
        `sample_count` is zero, and otherwise 4 points for each whole point by
        which the window's `mean_rating` falls short of 5 — that is, 4
        multiplied by five minus the mean rating, rounded half up to two decimal
        places."

        PRD §3.10: "The deflection penalty is zero when `deflection_pct` is
        null, and otherwise 0.06 points for each percentage point by which
        `deflection_pct` falls short of 100, rounded half up to two decimal
        places."

        Design: Difficulty/dual_variant_calc/topic_health_score_pre_versus_post_publication
        """
        set_clock(CLOCK)
        bundle = _churned_topic_approved_after_four_days()
        pre_score = bundle["topic"]["health_score"]
        _take_live(bundle)

        topic = validate_success(api.get_topic(bundle["topic_id"], docs_lead_headers))

        assert topic["publication_state"] == "PUBLISHED"
        assert topic["health_score_variant"] == "POST_PUBLICATION"
        assert topic["health_score"] == pytest.approx(90.00, abs=0.01)
        assert topic["health_score"] == pytest.approx(pre_score, abs=0.01)
        assert topic["health_score"] == pytest.approx(
            expected_health_score(4, 0, 0, 4, variant="POST_PUBLICATION", sample_count=0), abs=0.01
        )
        assert topic["current_revision_number"] == 4
        assert topic["signoff_latency_days"] == 4

    def test_reader_ratings_deduct_the_rating_and_deflection_penalties_from_a_live_page(
        self, api, docs_lead_headers, support_analyst_headers
    ):
        """Four ratings averaging 4.00 with a 75.00 percent deflection rate cost
        4.00 plus 1.50 points on top of the unchanged churn and latency.

        PRD §3.10: "The **post-publication** variant applies while
        `publication_state` is `PUBLISHED` or `ARCHIVED`, and subtracts two
        further penalties in this order."

        PRD §3.10: "The rating penalty is zero when the deflection window's
        `sample_count` is zero, and otherwise 4 points for each whole point by
        which the window's `mean_rating` falls short of 5 — that is, 4
        multiplied by five minus the mean rating, rounded half up to two decimal
        places."

        PRD §3.10: "The deflection penalty is zero when `deflection_pct` is
        null, and otherwise 0.06 points for each percentage point by which
        `deflection_pct` falls short of 100, rounded half up to two decimal
        places."

        PRD §3.3: "Reading a single topic — the one read that role `Reader` is
        permitted — exposes both state dimensions, the live violation counters,
        and the health score; for a topic that is live, that read re-derives the
        health score under its post-publication variant before rendering the
        response, so a fresh reader rating is visible in the score on the very
        next read."

        Design: Difficulty/dual_variant_calc/topic_health_score_pre_versus_post_publication
        """
        set_clock(CLOCK)
        bundle = _churned_topic_approved_after_four_days()
        _take_live(bundle)
        unrated_score = read_topic(bundle["topic_id"])["health_score"]

        first = create_feedback(bundle["topic_id"], bundle["locale_code"], rating=5)
        create_feedback(bundle["topic_id"], bundle["locale_code"], rating=3)
        create_feedback(bundle["topic_id"], bundle["locale_code"], rating=4)
        create_feedback(
            bundle["topic_id"], bundle["locale_code"], rating=4, outcome="OPENED_TICKET"
        )
        assert_page_feedback(first)

        summary = validate_success(
            api.get_deflection_summary(bundle["topic_id"], support_analyst_headers)
        )
        assert_deflection_summary(summary)
        assert summary["window_start_date"] == "2026-07-10"
        assert summary["window_end_date"] == APPROVE_DAY
        assert summary["sample_count"] == 4
        assert summary["mean_rating"] == pytest.approx(4.00, abs=0.01)
        assert summary["mean_rating"] == pytest.approx(expected_mean_rating([5, 3, 4, 4]), abs=0.01)
        assert summary["deflection_pct"] == pytest.approx(75.00, abs=0.01)
        assert summary["ticket_rate_pct"] == pytest.approx(25.00, abs=0.01)
        assert summary["deflection_pct"] == pytest.approx(expected_pct(3, 4), abs=0.01)

        topic = validate_success(api.get_topic(bundle["topic_id"], docs_lead_headers))
        assert topic["health_score_variant"] == "POST_PUBLICATION"
        assert topic["health_score"] == pytest.approx(84.50, abs=0.01)
        assert topic["health_score"] == pytest.approx(
            expected_health_score(
                4, 0, 0, 4,
                variant="POST_PUBLICATION",
                sample_count=4,
                mean_rating=4.00,
                deflection_pct=75.00,
            ),
            abs=0.01,
        )
        assert unrated_score - topic["health_score"] == pytest.approx(5.50, abs=0.01)


class TestDeflectionWindowBoundaries:
    """Two empty windows that must not be conflated, and the moment ratings age out
    of the window without leaving the feedback list."""

    def test_a_live_page_nobody_has_rated_reports_every_aggregate_as_null(
        self, api, docs_lead_headers, support_analyst_headers
    ):
        """A zero-sample window nulls the mean rating and both rates, and leaves the
        health score at its unpenalised ceiling.

        PRD §3.10: "The window begins 30 days before the logical clock and ends
        at the logical clock, with **both ends inclusive**; the response reports
        those bounds as `window_start_date` and `window_end_date`."

        PRD §3.10: "`mean_rating` is null when `sample_count` is zero and
        otherwise the sum of the `rating` values divided by `sample_count`,
        rounded half up to two decimal places."

        PRD §3.10: "Two empty cases are therefore distinct: a page with no
        feedback in the window reports a null `mean_rating` and a null
        `deflection_pct`, whereas a page whose window contains only abandoned
        sessions reports a real `mean_rating` and still a null `deflection_pct`."

        Design: Difficulty/boundary_precision_check/deflection_metrics_zero_sample_and_all_abandoned_null_boundaries
        """
        set_clock(CLOCK)
        bundle = feedback_context()

        summary = validate_success(
            api.get_deflection_summary(bundle["topic_id"], support_analyst_headers)
        )
        assert_deflection_summary(summary)
        assert summary["window_start_date"] == "2026-07-02"
        assert summary["window_end_date"] == "2026-08-01"
        assert (summary["window_start_date"], summary["window_end_date"]) == (
            expected_deflection_window("2026-08-01")
        )
        assert summary["sample_count"] == 0
        assert summary["mean_rating"] is None
        assert summary["deflection_pct"] is None
        assert summary["ticket_rate_pct"] is None

        topic = validate_success(api.get_topic(bundle["topic_id"], docs_lead_headers))
        assert topic["publication_state"] == "PUBLISHED"
        assert topic["current_revision_number"] == 1
        assert topic["signoff_latency_days"] == 0
        assert topic["health_score_variant"] == "POST_PUBLICATION"
        assert topic["health_score"] == pytest.approx(100.00, abs=0.01)
        assert topic["health_score"] == pytest.approx(
            expected_health_score(1, 0, 0, 0, variant="POST_PUBLICATION", sample_count=0), abs=0.01
        )

    def test_a_window_of_only_abandoned_sessions_reports_a_mean_but_no_deflection(
        self, api, docs_lead_headers, support_analyst_headers
    ):
        """Abandoned sessions count toward the sample and the mean while emptying
        the deflection denominator, so the rating penalty bites and the deflection
        penalty does not.

        PRD §3.10: "The *decided* rows are those in the window whose `outcome` is
        `RESOLVED_SELF_SERVE` or `OPENED_TICKET`; rows with `outcome`
        `ABANDONED` count toward `sample_count` and toward `mean_rating` but are
        excluded from the deflection denominator, because an abandoned session is
        neither a deflection nor an escalation."

        PRD §3.10: "When there are no decided rows at all, both `deflection_pct`
        and `ticket_rate_pct` are null; otherwise `deflection_pct` is the number
        of `RESOLVED_SELF_SERVE` rows multiplied by 100 and divided by the number
        of decided rows, rounded half up to two decimal places, and
        `ticket_rate_pct` is the number of `OPENED_TICKET` rows treated the same
        way."

        PRD §3.10: "The deflection penalty is zero when `deflection_pct` is null,
        and otherwise 0.06 points for each percentage point by which
        `deflection_pct` falls short of 100, rounded half up to two decimal
        places."

        Design: Difficulty/boundary_precision_check/deflection_metrics_zero_sample_and_all_abandoned_null_boundaries
        """
        set_clock(CLOCK)
        bundle = feedback_context(
            rows=(
                {"rating": 2, "outcome": "ABANDONED"},
                {"rating": 4, "outcome": "ABANDONED"},
            )
        )

        summary = validate_success(
            api.get_deflection_summary(bundle["topic_id"], support_analyst_headers)
        )
        assert summary["sample_count"] == 2
        assert summary["mean_rating"] == pytest.approx(3.00, abs=0.01)
        assert summary["mean_rating"] == pytest.approx(expected_mean_rating([2, 4]), abs=0.01)
        assert summary["deflection_pct"] is None
        assert summary["ticket_rate_pct"] is None
        assert expected_pct(0, 0) is None

        topic = validate_success(api.get_topic(bundle["topic_id"], docs_lead_headers))
        assert topic["health_score_variant"] == "POST_PUBLICATION"
        assert topic["health_score"] == pytest.approx(92.00, abs=0.01)
        assert topic["health_score"] == pytest.approx(
            expected_health_score(
                1, 0, 0, 0,
                variant="POST_PUBLICATION",
                sample_count=2,
                mean_rating=3.00,
                deflection_pct=None,
            ),
            abs=0.01,
        )

    def test_ratings_that_age_out_of_the_window_stop_influencing_every_figure(
        self, api, docs_lead_headers, support_analyst_headers
    ):
        """Six weeks later the same two rows are still listed but no longer counted,
        and the health score returns to its unrated value.

        PRD §3.10: "`sample_count` is the number of the topic's feedback rows
        whose `created_at` falls inside that window."

        PRD §3.10: "A `DocsLead` or a `SupportAnalyst` — and nobody else — may
        list a page's feedback, filtered by `outcome`, in `created_at` ascending
        order; rows that have aged out of the metrics window are still returned
        there even though they no longer influence any figure."

        Design: Difficulty/boundary_precision_check/deflection_metrics_zero_sample_and_all_abandoned_null_boundaries
        """
        set_clock(CLOCK)
        bundle = feedback_context(
            rows=(
                {"rating": 2, "outcome": "ABANDONED"},
                {"rating": 4, "outcome": "ABANDONED"},
            )
        )
        set_clock_date("2026-09-15")

        summary = validate_success(
            api.get_deflection_summary(bundle["topic_id"], support_analyst_headers)
        )
        assert summary["window_start_date"] == "2026-08-16"
        assert summary["window_end_date"] == "2026-09-15"
        assert summary["sample_count"] == 0
        assert summary["mean_rating"] is None
        assert summary["deflection_pct"] is None

        rows, meta = validate_list(
            api.list_topic_feedback(bundle["topic_id"], support_analyst_headers)
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2

        topic = validate_success(api.get_topic(bundle["topic_id"], docs_lead_headers))
        assert topic["health_score_variant"] == "POST_PUBLICATION"
        assert topic["health_score"] == pytest.approx(100.00, abs=0.01)


class TestReaderFeedbackRequiresALivePage:
    """The feedback endpoint's validity turns on a different entity's state: the
    page a reader claims to have read must actually be published."""

    def test_a_rating_on_a_page_that_was_never_published_is_refused(
        self, api, docs_lead_headers, reader_headers
    ):
        """With a resolvable locale code the only remaining obstacle is the topic's
        own publication state, and that is what the refusal names.

        PRD §3.10: "At most one feedback row may exist per topic and session, and
        the page's `publication_state` must be `PUBLISHED` — feedback against a
        page that is `UNPUBLISHED` or `ARCHIVED` is refused with
        `ERR_FEEDBACK_TOPIC_NOT_PUBLISHED`."

        PRD §3.10: "Recording one recomputes the topic's `health_score` under the
        post-publication variant."

        Design: Corner/validations/reader_feedback_on_an_unpublished_topic_rejected
        """
        set_clock(CLOCK)
        bundle = revised_topic_context()
        locale = create_locale_profile()
        assert read_topic(bundle["topic_id"])["publication_state"] == "UNPUBLISHED"

        response = api.create_feedback(
            bundle["topic_id"],
            create_feedback_payload(locale["locale_code"], rating=4, comment="Clear enough"),
            reader_headers,
        )
        validate_error(response, ApiErrorId.FEEDBACK_TOPIC_NOT_PUBLISHED, 409)

        _, meta = validate_list(api.list_topic_feedback(bundle["topic_id"], docs_lead_headers))
        assert meta["total_count"] == 0

        topic = read_topic(bundle["topic_id"])
        assert topic["publication_state"] == "UNPUBLISHED"
        assert topic["review_state"] == "NOT_SUBMITTED"
        assert topic["health_score_variant"] != "POST_PUBLICATION"
