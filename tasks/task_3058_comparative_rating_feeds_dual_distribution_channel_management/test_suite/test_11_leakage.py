"""Quote-to-bind leakage analytics: count vs premium-weighted bases, half-open
cohort windows, and the defined empty-cohort rule."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    bind_direct_quote,
    create_active_product,
    create_consumer,
    create_direct_quote,
    get_success_data,
    make_consumer_headers,
    set_clock,
    submit_direct_quote,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["carrier_admin_headers"]
RM = TEST_USERS["rating_manager_headers"]

DUAL_PRODUCT = {
    "coverage_rates": {
        "LIABILITY": {"BASIC": 50000, "STANDARD": 70000},
        "COLLISION": {"STANDARD": 90000, "PLUS": 120000},
    },
    "direct_discount_pct": 0.10,
    "agent_load_pct": 0.15,
    "bundle_credit_pct": 0.05,
    "min_premium_cents": 40000,
}

SIMPLE_PRODUCT = {
    "coverage_rates": {"LIABILITY": {"BASIC": 50000}},
    "direct_discount_pct": 0.10,
    "min_premium_cents": 0,
}


def _channels_index(report: dict) -> dict:
    channels = report["channels"]
    if isinstance(channels, dict):
        return channels
    return {entry["channel"]: entry for entry in channels}


class TestLeakageBases:
    def _setup_march_funnel(self, api):
        set_clock("2026-03-01T00:00:00Z")
        product = create_active_product(**DUAL_PRODUCT)
        consumer = create_consumer()
        coverages_full = [
            {"coverage_code": "LIABILITY", "tier": "BASIC"},
            {"coverage_code": "COLLISION", "tier": "STANDARD"},
        ]
        # Q1: full coverages, bound (126000)
        q1 = create_direct_quote(consumer, product["id"], coverages=coverages_full)
        submit_direct_quote(consumer, q1["id"])
        bind_direct_quote(consumer, q1["id"])
        # Q2: full coverages, bound (126000)
        q2 = create_direct_quote(consumer, product["id"], coverages=coverages_full)
        submit_direct_quote(consumer, q2["id"])
        bind_direct_quote(consumer, q2["id"])
        # Q3: single coverage, withdrawn (45000)
        q3 = create_direct_quote(
            consumer, product["id"],
            coverages=[{"coverage_code": "LIABILITY", "tier": "BASIC"}],
        )
        submit_direct_quote(consumer, q3["id"])
        validate_success(
            api.withdraw_quote(q3["id"], make_consumer_headers(consumer["id"]))
        )

    def test_leakage_count_basis_counts_unbound_quotes(self, api):
        """PRD §3.10: "On the `COUNT` basis, leakage is the leaked count divided
        by the cohort count, with an empty cohort defined as 0.0000."
        PRD §3.10: "A cohort member has leaked when it did not reach `BOUND`
        with a bind before `period_end` — that is, it is `EXPIRED`, `WITHDRAWN`,
        or still sitting in `QUOTED`, `REFERRED_TO_AGENT`, or `AGENT_QUOTED`."

        Design: Difficulty/dual_variant_calc/quote_to_bind_leakage_count_vs_premium_weighted_basis_on_quote_domain
        """
        self._setup_march_funnel(api)
        report = get_success_data(api.get_leakage_report(
            RM,
            params={
                "period_start": "2026-03-01T00:00:00Z",
                "period_end": "2026-04-01T00:00:00Z",
                "basis": "COUNT",
                "channel": "DIRECT",
            },
        ))
        direct = _channels_index(report)["DIRECT"]
        assert direct["cohort_count"] == 3
        assert direct["leaked_count"] == 1
        assert direct["leakage"] == pytest.approx(0.3333, abs=1e-9)

    def test_leakage_premium_weighted_basis_differs_from_count(self, api):
        """PRD §3.10: "On the `PREMIUM_WEIGHTED` basis, leakage is the sum of the
        leaked quotes' **latest** `quoted_premium_cents` divided by the sum over
        the whole cohort, with a zero premium total defined as 0.0000. Both
        variants round half-up at 4 decimal places, and the two bases yield
        different leakage for the same funnel whenever the leaked quotes are not
        premium-average."

        Design: Difficulty/dual_variant_calc/quote_to_bind_leakage_count_vs_premium_weighted_basis_on_quote_domain
        """
        self._setup_march_funnel(api)
        report = get_success_data(api.get_leakage_report(
            RM,
            params={
                "period_start": "2026-03-01T00:00:00Z",
                "period_end": "2026-04-01T00:00:00Z",
                "basis": "PREMIUM_WEIGHTED",
                "channel": "DIRECT",
            },
        ))
        direct = _channels_index(report)["DIRECT"]
        assert direct["cohort_premium_cents"] == 297000
        assert direct["leaked_premium_cents"] == 45000
        assert direct["leakage"] == pytest.approx(0.1515, abs=1e-9)


class TestLeakageWindow:
    def test_leakage_window_is_half_open_on_period_end(self, api):
        """PRD §3.10: "The report is parameterized by a half-open window from
        `period_start` to `period_end`, a `basis` of `COUNT` or
        `PREMIUM_WEIGHTED`, and an optional `channel` filter. The cohort for a
        channel is the quotes of that channel whose `quoted_at` falls within the
        window — a quote must have reached `QUOTED` or `AGENT_QUOTED` at least
        once to count, which is exactly what a non-null `quoted_at` certifies."

        Design: Corner/calculations/leakage_window_is_half_open_on_period_end
        """
        set_clock("2026-03-01T00:00:00Z")
        product = create_active_product(**SIMPLE_PRODUCT)
        consumer = create_consumer()
        q_in = create_direct_quote(consumer, product["id"])
        submit_direct_quote(consumer, q_in["id"])

        set_clock("2026-04-01T00:00:00Z")
        q_out = create_direct_quote(consumer, product["id"])
        submit_direct_quote(consumer, q_out["id"])

        report = get_success_data(api.get_leakage_report(
            RM,
            params={
                "period_start": "2026-03-01T00:00:00Z",
                "period_end": "2026-04-01T00:00:00Z",
                "basis": "COUNT",
                "channel": "DIRECT",
            },
        ))
        direct = _channels_index(report)["DIRECT"]
        # q_out quoted exactly at period_end is excluded from the cohort
        assert direct["cohort_count"] == 1
        assert direct["leaked_count"] == 1
        assert direct["leakage"] == pytest.approx(1.0000, abs=1e-9)


class TestLeakageEmptyCohort:
    def test_leakage_report_lists_zero_cohort_channel_as_zero(self, api):
        """PRD §3.10: "On the `COUNT` basis, leakage is the leaked count divided
        by the cohort count, with an empty cohort defined as 0.0000."

        Design: Corner/endpoints/leakage_report_lists_zero_cohort_channel_as_zero
        """
        set_clock("2026-03-01T00:00:00Z")
        product = create_active_product(**SIMPLE_PRODUCT)
        consumer = create_consumer()
        q1 = create_direct_quote(consumer, product["id"])
        submit_direct_quote(consumer, q1["id"])
        validate_success(
            api.withdraw_quote(q1["id"], make_consumer_headers(consumer["id"]))
        )

        report = get_success_data(api.get_leakage_report(
            ADMIN,
            params={
                "period_start": "2026-03-01T00:00:00Z",
                "period_end": "2026-04-01T00:00:00Z",
                "basis": "COUNT",
            },
        ))
        channels = _channels_index(report)
        assert "DIRECT" in channels
        assert "AGENT" in channels
        assert channels["DIRECT"]["cohort_count"] == 1
        assert channels["DIRECT"]["leakage"] == pytest.approx(1.0000, abs=1e-9)
        assert channels["AGENT"]["cohort_count"] == 0
        assert channels["AGENT"]["leakage"] == pytest.approx(0.0000, abs=1e-9)
