"""Logical clock monotonicity."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_clock_result,
    set_clock_payload,
    validate_error,
    validate_success,
)

WM = TEST_USERS["workshop_manager_headers"]


def test_clock_regression_rejected(api):
    """PRD section 2.4: "The clock may only move forward: a `to_iso8601` earlier
    than the current logical clock is rejected with `ERR_CLOCK_REGRESSION`
    (HTTP 422), while a value equal to the current clock is accepted."

    Design: Corner/validations/clock_regression_rejected
    """
    moved = validate_success(api.set_clock(set_clock_payload("2027-01-01T00:00:00Z"), WM), 200)
    assert_clock_result(moved)
    assert moved["current_utc"] == "2027-01-01T00:00:00Z"
    backwards = api.set_clock(set_clock_payload("2026-12-01T00:00:00Z"), WM)
    validate_error(backwards, ApiErrorId.ERR_CLOCK_REGRESSION)
    same = validate_success(api.set_clock(set_clock_payload("2027-01-01T00:00:00Z"), WM), 200)
    assert same["current_utc"] == "2027-01-01T00:00:00Z"
