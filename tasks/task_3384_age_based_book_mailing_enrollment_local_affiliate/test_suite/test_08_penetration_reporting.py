"""Affiliate penetration reporting: population selector, snapshot vs
trailing-12 variants (PRD §3.8)."""
import pytest

from test_helpers import (
    DEFAULT_CHILD_SPECS,
    EnrollmentStatus,
    TEST_USERS,
    api_client,
    assert_penetration_report,
    create_population_stat,
    create_wave,
    get_child,
    get_child_wave_item,
    manifest_wave,
    mark_item_returned,
    register_children,
    set_logical_clock,
    setup_manifested_wave,
    setup_month_supply,
    setup_operative_affiliate,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]


class TestPopulationSelector:
    def test_penetration_without_population_stats_returns_null_rates(self, api):
        """PRD §3.8: "if the affiliate has no stats at all,
        `eligible_population` is zero and both penetration rates are null."
        PRD §3.8: "The response body reports `affiliate_id`, `month`,
        `enrolled_count`, `eligible_population`, `population_stat_year`,
        `penetration_snapshot_bp`, `trailing_12_unique_children`, and
        `penetration_trailing_12_bp`."

        Design: Corner/calculations/penetration_without_population_stats_returns_null_rates
        """
        base = setup_operative_affiliate()
        affiliate = base["affiliate"]
        register_children(affiliate["id"], DEFAULT_CHILD_SPECS[:1])
        report = validate_success(
            api.get_affiliate_penetration(
                affiliate["id"], _ADMIN, params={"month": "2026-09"}
            )
        )
        assert_penetration_report(report)
        assert report["enrolled_count"] == 1
        assert report["eligible_population"] == 0
        assert report["population_stat_year"] is None
        assert report["penetration_snapshot_bp"] is None
        assert report["penetration_trailing_12_bp"] is None

    def test_population_stat_selector_prefers_greatest_year_leq(self, api):
        """PRD §3.8: "first selects the population baseline: the affiliate's
        stat with the greatest `effective_year` not later than the report
        month's year, falling back to the stat with the smallest
        `effective_year` when no year qualifies, with ties impossible because
        year is unique per affiliate".
        PRD §3.8: "`penetration_snapshot_bp` is that count times 10,000
        divided by `eligible_population`, rounded half up, when the population
        is positive, else null."

        Design: Corner/calculations/population_stat_selector_prefers_greatest_year_leq
        """
        base = setup_operative_affiliate(
            population_stat={"effective_year": 2024, "eligible_population": 8000}
        )
        affiliate = base["affiliate"]
        create_population_stat(
            affiliate["id"], effective_year=2026, eligible_population=10000
        )
        register_children(affiliate["id"], DEFAULT_CHILD_SPECS[:2])
        report_2025 = validate_success(
            api.get_affiliate_penetration(
                affiliate["id"], _ADMIN, params={"month": "2025-06"}
            )
        )
        assert_penetration_report(report_2025)
        assert report_2025["population_stat_year"] == 2024, (
            "2024 is the greatest effective_year not later than 2025"
        )
        assert report_2025["eligible_population"] == 8000
        # round_half_up(2 x 10000 / 8000) = round_half_up(2.5) = 3
        assert report_2025["penetration_snapshot_bp"] == 3
        assert report_2025["enrolled_count"] == 2
        report_2026 = validate_success(
            api.get_affiliate_penetration(
                affiliate["id"], _ADMIN, params={"month": "2026-06"}
            )
        )
        assert report_2026["population_stat_year"] == 2026
        assert report_2026["eligible_population"] == 10000
        assert report_2026["penetration_snapshot_bp"] == 2
        assert report_2026["enrolled_count"] == 2, (
            "the snapshot numerator is the live count in both reports"
        )

    def test_trailing_12_window_excludes_items_older_than_window(self, api):
        """PRD §3.8: "The trailing-twelve numerator,
        `trailing_12_unique_children`, counts distinct children with at least
        one mailing item of any status whose `mailing_month` falls inside the
        inclusive twelve-month window from eleven months before the report
        month through the report month itself".
        PRD §3.8: "The snapshot numerator is the live `enrolled_count` —
        children currently `ACTIVE` or `UNDELIVERABLE_HOLD`, regardless of
        which month was requested".

        Design: Corner/calculations/trailing_12_window_excludes_items_older_than_window
        """
        ctx = setup_manifested_wave(
            clock="2025-10-01T00:00:00Z",
            mailing_month="2025-11",
            child_specs=[
                {
                    "full_name": "Trailer Tot", "family_name": "Tot",
                    "birth_date": "2025-08-05T00:00:00Z",
                    "mailing_address": {
                        "line1": "1 Early Way", "city": "Nashville",
                        "region": "TN", "postal_code": "37201", "country": "US",
                    },
                }
            ],
            title_window=("2025-01", "2027-12"),
            agreement_overrides={"effective_from": "2025-01-01T00:00:00Z"},
            with_population_stat=True,
            population_overrides={"effective_year": 2025, "eligible_population": 5000},
        )
        affiliate = ctx["affiliate"]
        # Window [2025-11 .. 2026-10] includes the child's 2025-11 item.
        report_oct = validate_success(
            api.get_affiliate_penetration(
                affiliate["id"], _ADMIN, params={"month": "2026-10"}
            )
        )
        assert_penetration_report(report_oct)
        assert report_oct["trailing_12_unique_children"] == 1
        # round_half_up(1 x 10000 / 5000) = 2
        assert report_oct["penetration_trailing_12_bp"] == 2
        # Window [2025-12 .. 2026-11] excludes it.
        report_nov = validate_success(
            api.get_affiliate_penetration(
                affiliate["id"], _ADMIN, params={"month": "2026-11"}
            )
        )
        assert report_nov["trailing_12_unique_children"] == 0
        assert report_nov["penetration_trailing_12_bp"] == 0
        for report in (report_oct, report_nov):
            assert report["enrolled_count"] == 1
            assert report["penetration_snapshot_bp"] == 2, (
                "the snapshot does not move with the trailing window"
            )


class TestSnapshotTrailingDivergence:
    def _serve_then_unenroll_first_child(self, api):
        """Manifest October and November waves for three children; return the
        first child's item in both months so the second return auto-unenrolls
        them. Returns the manifest context."""
        ctx = setup_manifested_wave(with_population_stat=True)
        child = ctx["children"][0]
        mark_item_returned(get_child_wave_item(ctx["wave"]["id"], child["id"])["id"])
        set_logical_clock("2026-11-01T00:00:00Z")
        setup_month_supply("2026-11", titles=ctx["titles"])
        wave_nov = create_wave("2026-11")
        manifest_wave(wave_nov["id"])
        mark_item_returned(get_child_wave_item(wave_nov["id"], child["id"])["id"])
        return ctx

    def test_penetration_snapshot_vs_trailing_12_diverge(self, api):
        """PRD §3.8: "The snapshot numerator is the live `enrolled_count` —
        children currently `ACTIVE` or `UNDELIVERABLE_HOLD`, regardless of
        which month was requested" and "The trailing-twelve numerator,
        `trailing_12_unique_children`, counts distinct children with at least
        one mailing item of any status whose `mailing_month` falls inside the
        inclusive twelve-month window from eleven months before the report
        month through the report month itself — including children who have
        since graduated, transferred, or unenrolled". "The two diverge
        whenever a served child left the program within the window."

        Design: Difficulty/dual_variant_calc/penetration_snapshot_vs_trailing_12_diverge
        """
        ctx = self._serve_then_unenroll_first_child(api)
        affiliate = ctx["affiliate"]
        report = validate_success(
            api.get_affiliate_penetration(
                affiliate["id"], _ADMIN, params={"month": "2026-11"}
            )
        )
        assert_penetration_report(report)
        assert report["enrolled_count"] == 2
        assert report["eligible_population"] == 10000
        assert report["population_stat_year"] == 2026
        # round_half_up(2 x 10000 / 10000) = 2
        assert report["penetration_snapshot_bp"] == 2
        assert report["trailing_12_unique_children"] == 3
        # round_half_up(3 x 10000 / 10000) = 3
        assert report["penetration_trailing_12_bp"] == 3
        assert report["penetration_snapshot_bp"] != (
            report["penetration_trailing_12_bp"]
        ), "the variants diverge once a served child leaves the program"

    def test_trailing_12_counts_children_who_left_program(self, api):
        """PRD §3.8: "`trailing_12_unique_children`, counts distinct children
        with at least one mailing item of any status whose `mailing_month`
        falls inside the inclusive twelve-month window ... — including
        children who have since graduated, transferred, or unenrolled".
        PRD §3.4: "When the counter reaches two — the program's
        auto-unenrollment threshold — the same return that raised it fires
        hold-then-unenroll atomically, netting out at `UNENROLLED`".

        Design: Difficulty/dual_variant_calc/penetration_snapshot_vs_trailing_12_diverge
        """
        ctx = self._serve_then_unenroll_first_child(api)
        affiliate = ctx["affiliate"]
        child = ctx["children"][0]
        assert get_child(child["id"])["enrollment_status"] == (
            EnrollmentStatus.UNENROLLED.value
        )
        rows, meta = validate_paginated(
            api.list_items(_ADMIN, params={"child_id": child["id"], "limit": 100})
        )
        assert meta["total_count"] == 2, (
            "the unenrolled child was served in both 2026-10 and 2026-11"
        )
        report = validate_success(
            api.get_affiliate_penetration(
                affiliate["id"], _ADMIN, params={"month": "2026-11"}
            )
        )
        assert report["enrolled_count"] == 2, (
            "the live snapshot excludes the unenrolled child"
        )
        assert report["trailing_12_unique_children"] == 3, (
            "the trailing window still counts the unenrolled child"
        )
