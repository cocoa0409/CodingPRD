"""Forecast submission, share-sum boundary, lock, and the reliability
requirement roll-up (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_forecast,
    create_zone,
    get_success_data,
    lock_forecast,
    setup_delivery_year_with_forecast,
    setup_delivery_year_with_zone,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["market_admin_headers"]


class TestPeakLoadRequirementRollup:
    def test_lock_computes_rto_requirement_and_locks_forecast(self, api):
        """PRD §3.1: "First, the installed capacity basis is the RTO peak load
        multiplied by one plus the reserve margin."
        PRD §3.1: "Second, that basis is converted to unforced capacity terms
        by multiplying by one minus the pool-wide average forced outage rate."
        PRD §3.1: "Fourth, the delivery year's `reliability_requirement_mw` is
        set to the RTO unforced requirement rounded to 3 decimals round half
        up."

        Design: Corner/calculations/peak_load_requirement_rto_rollup
        """
        dy, zone, forecast = setup_delivery_year_with_forecast(
            rto_peak_load_mw=150000.0,
            reserve_margin_pct=0.161,
            pool_wide_avg_eford=0.05,
            zonal_peak_shares={"RTO": 1.0},
        )
        locked = lock_forecast(dy["id"])
        # 150000 * 1.161 = 174150.0; 174150.0 * 0.95 = 165442.5
        assert locked["status"] == "FORECAST_LOCKED"
        assert locked["reliability_requirement_mw"] == pytest.approx(165442.5, abs=1e-6)
        assert locked["forecast_version"] == 1

        zone_after = get_success_data(api.get_zone(zone["id"], ADMIN))
        assert zone_after["zonal_requirement_mw"] == pytest.approx(165442.5, abs=1e-6)

        forecasts, meta = validate_paginated(
            api.list_forecasts(dy["id"], ADMIN)
        )
        assert forecasts[0]["status"] == "LOCKED"
        assert forecasts[0]["revision"] == 1


class TestForecastShareSumBoundary:
    def test_shares_summing_above_one_rejected(self, api):
        """PRD §3.1: "The map's keys must cover every top-level zone of the
        delivery year, and the fractions — each rounded to 3 decimal places
        round half up — must sum to exactly 1.000; otherwise submission fails
        with `ERR_FORECAST_SHARES_INVALID`."

        Design: Difficulty/boundary_precision_check/forecast_shares_sum_exactly_one_thousandth_boundary
        """
        dy, zone = setup_delivery_year_with_zone()
        create_zone(dy["id"], zone_code="B")
        create_zone(dy["id"], zone_code="C")
        resp = api.create_forecast(dy["id"], {
            "rto_peak_load_mw": 10.0,
            "reserve_margin_pct": 0.25,
            "pool_wide_avg_eford": 0.04,
            "zonal_peak_shares": {"RTO": 0.335, "B": 0.333, "C": 0.333},
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORECAST_SHARES_INVALID, expected_status=422)

    def test_shares_summing_exactly_one_accepted(self, api):
        """PRD §3.1: "The map's keys must cover every top-level zone of the
        delivery year, and the fractions — each rounded to 3 decimal places
        round half up — must sum to exactly 1.000; otherwise submission fails
        with `ERR_FORECAST_SHARES_INVALID`."

        Design: Difficulty/boundary_precision_check/forecast_shares_sum_exactly_one_thousandth_boundary
        """
        dy, zone = setup_delivery_year_with_zone()
        create_zone(dy["id"], zone_code="B")
        create_zone(dy["id"], zone_code="C")
        resp = api.create_forecast(dy["id"], {
            "rto_peak_load_mw": 10.0,
            "reserve_margin_pct": 0.25,
            "pool_wide_avg_eford": 0.04,
            "zonal_peak_shares": {"RTO": 0.334, "B": 0.333, "C": 0.333},
        }, ADMIN)
        forecast = validate_success(resp, expected_status=201)
        assert forecast["status"] == "DRAFT"
        assert forecast["revision"] == 1
