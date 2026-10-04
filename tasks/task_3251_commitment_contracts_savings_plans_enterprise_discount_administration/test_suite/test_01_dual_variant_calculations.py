"""Tests for dual-variant calculations (coverage modes, forecast variants)."""
from test_helpers import (
    validate_error,
    validate_success,
    api_client,
    make_admin_headers,
    make_finance_headers,
    make_manager_headers,
    make_platform_headers,
    create_org,
    create_active_agreement,
    create_linked_account,
    create_plan,
    ingest_usage,
    period_close,
    ApiErrorId,
)

ADMIN = make_admin_headers()
FINANCE = make_finance_headers()
PLATFORM = make_platform_headers()


class TestCoverageDualVariant:
    """ACTUAL vs PROJECTED coverage modes diverge on under-utilized hours."""

    def _setup(self):
        org = create_org(name="Cov Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
            committed_spend_cents=1000000,
        )
        acct = create_linked_account(org["id"], name="acct-1", external_ref="ext-1")
        plan = create_plan(
            org["id"], agr["id"],
            type="SAVINGS_PLAN", instance_family="COMPUTE", units=0,
            hourly_commitment_cents=100, plan_discount_rate=0.30,
            term_start="2026-09-01T00:00:00Z", term_end="2026-10-01T00:00:00Z",
        )
        for hour, amount in (("2026-09-01T00:00:00Z", 150),
                             ("2026-09-01T01:00:00Z", 80),
                             ("2026-09-01T02:00:00Z", 100)):
            ingest_usage(acct["id"], usage_hour_start=hour, list_price_cents=amount)
        return org, agr, acct, plan

    def test_actual_mode_replays_real_usage_with_per_hour_min(self, api):
        """PRD section 3.4: "The `ACTUAL` mode replays real usage chronologically
        hour by hour, ordered by `usage_hour_start` ascending with ties broken by
        account creation order; within each hour the plan's remaining budget is
        exactly `hourly_commitment_cents`, and post-amendment usage of the plan's
        `instance_family` across all of the org's linked accounts is covered in
        account `created_at` ascending order until the hourly budget is exhausted,
        so the covered amount is the sum over hours of the smaller of that hour's
        family usage and the hourly commitment."

        Design: Difficulty/dual_variant_calc/savings_plan_coverage_projected_assumes_full_utilization_actual_replays
        """
        _, _, _, plan = self._setup()
        resp = api.get_plan_coverage(
            plan["id"], ADMIN,
            params={"mode": "ACTUAL",
                    "window_start": "2026-09-01T00:00:00Z",
                    "window_end": "2026-09-01T03:00:00Z"},
        )
        data = validate_success(resp)
        assert data["covered_cents"] == 280, (
            f"ACTUAL must be min(150,100)+min(80,100)+min(100,100)=280, "
            f"got {data['covered_cents']}"
        )
        assert data["mode"] == "ACTUAL"

    def test_projected_mode_assumes_full_utilization_and_diverges(self, api):
        """PRD section 3.4: "The `PROJECTED` mode is a purchase-time what-if that
        assumes full utilization: the covered amount is simply
        `hourly_commitment_cents` multiplied by the number of hours in the window.
        The two diverge precisely when any hour is under-utilized."

        Design: Difficulty/dual_variant_calc/savings_plan_coverage_projected_assumes_full_utilization_actual_replays
        """
        _, _, _, plan = self._setup()
        resp = api.get_plan_coverage(
            plan["id"], ADMIN,
            params={"mode": "PROJECTED",
                    "window_start": "2026-09-01T00:00:00Z",
                    "window_end": "2026-09-01T03:00:00Z"},
        )
        data = validate_success(resp)
        assert data["covered_cents"] == 300, (
            f"PROJECTED must be 100 x 3 = 300, got {data['covered_cents']}"
        )
        actual = validate_success(api.get_plan_coverage(
            plan["id"], ADMIN,
            params={"mode": "ACTUAL",
                    "window_start": "2026-09-01T00:00:00Z",
                    "window_end": "2026-09-01T03:00:00Z"},
        ))
        assert actual["covered_cents"] != data["covered_cents"], (
            "hour 1 is under-utilized (80 < 100) so the variants must diverge"
        )


class TestForecastDualVariant:
    """LINEAR vs COHORT_WEIGHTED renewal forecasts on identical history."""

    def _setup(self):
        org = create_org(name="Fc Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
            committed_spend_cents=1000000,
        )
        acct = create_linked_account(org["id"], name="acct-1", external_ref="ext-1")
        # closed-period usage: period 0 = 100000, period 1 = 120000, period 2 = 140000
        for i, amount in enumerate((100000, 120000, 140000)):
            ingest_usage(acct["id"],
                         usage_hour_start=f"2026-09-01T{i:02d}:00:00Z",
                         list_price_cents=amount)
            period_close(org["id"])
        return org, agr, acct

    def test_linear_variant_extrapolates_growth(self, api):
        """PRD section 3.10: "The `LINEAR` variant extrapolates average
        period-over-period growth from the window's endpoints: the forecast is the
        most recent period's spend plus the mean of the consecutive deltas, which
        equals the most recent spend plus the difference between the most recent
        and the oldest period in the window divided by one less than the window
        size."

        Design: Difficulty/dual_variant_calc/renewal_forecast_linear_extrapolates_growth_cohort_weights_recency
        """
        _, agr, _ = self._setup()
        resp = api.create_renewal_forecast(
            {"agreement_id": agr["id"], "variant": "LINEAR"}, FINANCE
        )
        data = validate_success(resp, expected_status=201)
        assert data["forecast_cents"] == 160000, (
            f"LINEAR = 140000 + (140000-100000)/2 = 160000, "
            f"got {data['forecast_cents']}"
        )

    def test_cohort_weighted_variant_weights_recency(self, api):
        """PRD section 3.10: "The `COHORT_WEIGHTED` variant pins the window to 3
        periods and ignores trend in favor of recency-weighted level: half of the
        most recent period's spend, plus three tenths of the period before it,
        plus one fifth of the period before that."

        Design: Difficulty/dual_variant_calc/renewal_forecast_linear_extrapolates_growth_cohort_weights_recency
        """
        _, agr, _ = self._setup()
        resp = api.create_renewal_forecast(
            {"agreement_id": agr["id"], "variant": "COHORT_WEIGHTED"}, FINANCE
        )
        data = validate_success(resp, expected_status=201)
        assert data["forecast_cents"] == 126000, (
            f"COHORT = 0.5*140000 + 0.3*120000 + 0.2*100000 = 126000, "
            f"got {data['forecast_cents']}"
        )
        lin = validate_success(
            api.create_renewal_forecast(
                {"agreement_id": agr["id"], "variant": "LINEAR"}, FINANCE
            ),
            expected_status=201,
        )
        assert data["forecast_cents"] - lin["forecast_cents"] == -34000, (
            "on identical history the variants differ by exactly 34000 cents"
        )
