"""SIFL rate-period publication rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_default_rate_period,
    reset_clock,
    validate_error,
)

FINANCE = TEST_USERS["finance_headers"]


class TestRatePeriodOverlap:
    def test_overlapping_rate_period_rejected(self, api):
        """PRD §3.1: "Two rate periods covering the same lookup date must not
        overlap: a new period whose half-open interval intersects an existing one
        is rejected with `ERR_OVERLAPPING_RATE_PERIOD` (HTTP 422)."

        Design: Corner/errors/error_overlapping_rate_period
        """
        reset_clock()
        create_default_rate_period()  # 2026-08-01 .. 2027-02-01
        resp = api.create_sifl_rate_period(
            {
                "period_start_utc": "2027-01-01T00:00:00Z",
                "period_end_utc": "2027-08-01T00:00:00Z",
                "terminal_charge_cents": 9999,
                "rate_band_1_cents_per_mile": 30,
                "rate_band_2_cents_per_mile": 20,
                "rate_band_3_cents_per_mile": 10,
                "control_employee_multiplier_pct": 400,
            },
            FINANCE,
        )
        validate_error(resp, ApiErrorId.ERR_OVERLAPPING_RATE_PERIOD)
