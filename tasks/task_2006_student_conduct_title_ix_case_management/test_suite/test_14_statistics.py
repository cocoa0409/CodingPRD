"""Annual statistics: hierarchy rule, rounding order, frozen vs live, guards."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    begin_jurisdiction_review,
    create_case,
    dismiss_case,
    get_annual_statistics,
    make_cast,
    make_coordinator_headers,
    set_clock,
    stats_live_counts,
    validate_error,
    validate_success,
)
from test_helpers import api_client


def _received_case(cast, categories, received_via="EMAIL", occurred_at="2026-07-15T22:00:00Z",
                   **overrides):
    return create_case(
        cast, categories=list(categories), received_via=received_via,
        occurred_at=occurred_at, **overrides,
    )


class TestHierarchyRule:
    def test_statistics_hierarchy_rule_single_bucket_per_case(self, api):
        """PRD 3.8: "The **hierarchy rule** counts every included case in exactly
        one category bucket: the case's assigned category is the member of its
        `categories` with the highest §2.7 hierarchy priority, so a case alleging
        both `STALKING` and `SEXUAL_ASSAULT` counts toward `SEXUAL_ASSAULT`
        (priority 7 over 4) — and the `per_category` counts sum exactly to
        `reports_received`."

        Design: Corner/calculations/statistics_hierarchy_rule_single_bucket_per_case
        """
        cast = make_cast("comp", "resp", "coord")
        _received_case(cast, ("STALKING", "SEXUAL_ASSAULT"))
        _received_case(cast, ("STALKING",), occurred_at="2026-07-16T22:00:00Z")

        data = get_annual_statistics(2026, cast["coord"]["id"])
        counts = stats_live_counts(data)
        assert counts["reports_received"] == 2
        per_category = counts["per_category"]
        # The multi-category case lands only in the higher-priority bucket.
        assert per_category["SEXUAL_ASSAULT"] == 1
        assert per_category["STALKING"] == 1
        assert sum(per_category.values()) == counts["reports_received"] == 2


class TestAvgResolutionDays:
    def _three_clocked_cases(self, cast):
        """Three cases received and dismissed at clock-controlled instants:
        1.5d, 1.5d, and 2.4d resolution spans, all in calendar 2026."""
        coord_id = cast["coord"]["id"]
        set_clock("2026-01-05T00:00:00Z")
        c1 = _received_case(cast, ("STALKING",), occurred_at="2026-01-04T20:00:00Z")
        begin_jurisdiction_review(c1["id"], coord_id)
        set_clock("2026-01-06T12:00:00Z")
        dismiss_case(c1["id"], coord_id,
                     dismissal_reason="DISCRETIONARY_COMPLAINANT_WITHDRAWN")

        set_clock("2026-01-10T00:00:00Z")
        c2 = _received_case(cast, ("SEXUAL_HARASSMENT",), received_via="ONLINE_FORM",
                            occurred_at="2026-01-09T20:00:00Z")
        begin_jurisdiction_review(c2["id"], coord_id)
        set_clock("2026-01-11T12:00:00Z")
        dismiss_case(c2["id"], coord_id,
                     dismissal_reason="DISCRETIONARY_COMPLAINANT_WITHDRAWN")

        set_clock("2026-02-01T00:00:00Z")
        c3 = _received_case(cast, ("DATING_VIOLENCE",), received_via="IN_PERSON",
                            occurred_at="2026-01-30T20:00:00Z")
        begin_jurisdiction_review(c3["id"], coord_id)
        set_clock("2026-02-03T09:36:00Z")
        dismiss_case(c3["id"], coord_id,
                     dismissal_reason="DISCRETIONARY_RESPONDENT_DEPARTED")
        return c1, c2, c3

    def test_avg_resolution_days_nested_rounding(self, api):
        """PRD 3.8: "First, per resolved case — included cases with `closed_at`
        set and `closed_at` strictly before the following January 1 boundary —
        compute whole days as the floor of the elapsed seconds between
        `closed_at` and `received_at` divided by 86,400. Second, take the exact
        rational mean of those per-case integers. Third, round the mean half-up
        to one decimal place — a single rounding, last."

        Design: Difficulty/combinatorial_formula/avg_resolution_days_nested_rounding_mode_b
        """
        cast = make_cast("comp", "resp", "coord")
        self._three_clocked_cases(cast)
        data = get_annual_statistics(2026, cast["coord"]["id"])
        counts = stats_live_counts(data)
        assert counts["reports_received"] == 3
        assert counts["dismissed"] == 3
        # Floor-first per case: 1.5d->1, 1.5d->1, 2.4d->2; exact mean 4/3;
        # single round half-up at the end -> 1.3. (Averaging the exact spans
        # first would report 1.8.)
        assert counts["avg_resolution_days"] == pytest.approx(1.3, abs=0.001)

    def test_avg_resolution_days_per_category_assignment(self, api):
        """PRD 3.8: "The **hierarchy rule** counts every included case in exactly
        one category bucket: the case's assigned category is the member of its
        `categories` with the highest §2.7 hierarchy priority, so a case alleging
        both `STALKING` and `SEXUAL_ASSAULT` counts toward `SEXUAL_ASSAULT`
        (priority 7 over 4) — and the `per_category` counts sum exactly to
        `reports_received`."

        Design: Difficulty/combinatorial_formula/avg_resolution_days_nested_rounding_mode_b
        """
        cast = make_cast("comp", "resp", "coord")
        self._three_clocked_cases(cast)
        data = get_annual_statistics(2026, cast["coord"]["id"])
        counts = stats_live_counts(data)
        per_category = counts["per_category"]
        assert per_category["STALKING"] == 1
        assert per_category["SEXUAL_HARASSMENT"] == 1
        assert per_category["DATING_VIOLENCE"] == 1
        assert sum(per_category.values()) == counts["reports_received"] == 3
        assert counts["avg_resolution_days"] == pytest.approx(1.3, abs=0.001)

    def test_avg_resolution_days_null_when_no_resolved_cases(self, api):
        """PRD 3.8: "If the resolved set is empty, `avg_resolution_days` is null,
        never zero."

        Design: Corner/calculations/avg_resolution_days_null_when_no_resolved_cases
        """
        cast = make_cast("comp", "resp", "coord")
        _received_case(cast, ("STALKING",))
        data = get_annual_statistics(2026, cast["coord"]["id"])
        counts = stats_live_counts(data)
        assert counts["reports_received"] == 1
        assert counts["dismissed"] == 0
        assert counts["avg_resolution_days"] is None, (
            "an empty resolved set cannot masquerade as instant resolution"
        )


class TestFrozenVsLive:
    def _two_cases_and_publish(self, cast):
        """Two 2026 cases in JURISDICTION_REVIEW; publish the 2026 statistics."""
        coord_id = cast["coord"]["id"]
        c1 = _received_case(cast, ("STALKING",), occurred_at="2026-06-01T20:00:00Z")
        begin_jurisdiction_review(c1["id"], coord_id)
        c2 = _received_case(cast, ("SEXUAL_HARASSMENT",), received_via="IN_PERSON",
                            occurred_at="2026-06-20T20:00:00Z")
        begin_jurisdiction_review(c2["id"], coord_id)
        resp = api_client.publish_annual_statistics(2026, make_coordinator_headers(coord_id))
        published = validate_success(resp, 201)
        return c1, c2, published

    def test_published_snapshot_frozen_vs_live(self, api):
        """PRD 3.8: "Thereafter the frozen snapshot never moves: later case
        mutations — dismissals, reversals, new findings — do not touch it, so the
        same underlying cases can yield different numbers under the live and
        published views."
        PRD 3.8: "Publishing — a coordinator act, with the `year` required to lie
        within 2000 through 2100 inclusive, failing as
        `ERR_STATISTICS_YEAR_INVALID` (422) — freezes the live computation into
        `snapshot_counts` on a new `AnnualStatistic` row in `PUBLISHED` status
        with `published_at` stamped".

        Design: Difficulty/dual_variant_calc/annual_statistics_published_snapshot_frozen_vs_live
        """
        cast = make_cast("comp", "resp", "coord")
        c1, c2, published = self._two_cases_and_publish(cast)
        # Frozen at publish: both cases in flight, nothing dismissed.
        assert published["status"] == "PUBLISHED"
        assert published["snapshot_counts"]["reports_received"] == 2
        assert published["snapshot_counts"]["dismissed"] == 0

        dismiss_case(c2["id"], cast["coord"]["id"],
                     dismissal_reason="DISCRETIONARY_EVIDENCE_UNAVAILABLE")

        data = get_annual_statistics(2026, cast["coord"]["id"])
        assert data["status"] == "PUBLISHED"
        assert data["snapshot_counts"]["dismissed"] == 0
        assert data["snapshot_counts"]["reports_received"] == 2
        live = stats_live_counts(data)
        assert live["dismissed"] == 1, "live recompute sees the post-publish dismissal"
        assert live["reports_received"] == 2

    def test_snapshot_does_not_move_after_post_publish_mutation(self, api):
        """PRD 3.8: "Thereafter the frozen snapshot never moves: later case
        mutations — dismissals, reversals, new findings — do not touch it, so the
        same underlying cases can yield different numbers under the live and
        published views."

        Design: Difficulty/dual_variant_calc/annual_statistics_published_snapshot_frozen_vs_live
        """
        cast = make_cast("comp", "resp", "coord")
        c1, c2, published = self._two_cases_and_publish(cast)
        assert_instant_equals(
            published["published_at"], "2026-08-01T00:00:00Z", "published_at"
        )
        dismiss_case(c2["id"], cast["coord"]["id"],
                     dismissal_reason="DISCRETIONARY_EVIDENCE_UNAVAILABLE")
        dismiss_case(c1["id"], cast["coord"]["id"],
                     dismissal_reason="DISCRETIONARY_COMPLAINANT_WITHDRAWN")

        data = get_annual_statistics(2026, cast["coord"]["id"])
        # Same underlying rows, two views: frozen snapshot stays at zero
        # dismissals while the live view counts both.
        assert data["snapshot_counts"]["dismissed"] == 0
        live = stats_live_counts(data)
        assert live["dismissed"] == 2
        assert data["snapshot_counts"]["reports_received"] == 2
        assert live["reports_received"] == 2


class TestStatisticsGuards:
    def test_statistics_year_guards(self, api):
        """PRD 3.8: "Publishing — a coordinator act, with the `year` required to
        lie within 2000 through 2100 inclusive, failing as
        `ERR_STATISTICS_YEAR_INVALID` (422) — freezes the live computation into
        `snapshot_counts` on a new `AnnualStatistic` row in `PUBLISHED` status
        with `published_at` stamped; a year row that already exists makes the
        publish a duplicate, `ERR_DUPLICATE_RESOURCE`."
        PRD 3.8: "against an existing `PUBLISHED` or `AMENDED` row (amending a
        year with no published row fails `ERR_STATISTICS_YEAR_INVALID`)".

        Design: Corner/validations/statistics_year_guards
        """
        cast = make_cast("coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        validate_success(api.publish_annual_statistics(2026, coord_h), 201)

        bad_year = api.publish_annual_statistics(1999, coord_h)
        validate_error(bad_year, ApiErrorId.ERR_STATISTICS_YEAR_INVALID)

        unpublished = api.amend_annual_statistics(2027, coord_h)
        validate_error(unpublished, ApiErrorId.ERR_STATISTICS_YEAR_INVALID)

        duplicate = api.publish_annual_statistics(2026, coord_h)
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RESOURCE)
