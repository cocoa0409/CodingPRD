"""Demand forecasts: triple uniqueness, lifecycle ordering, and the
inclusive -20.00 percent miss boundary (PRD section 3.8)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS,
    validate_error, validate_success,
    create_demand_forecast_payload, forecast_transition_payload,
    create_bare_product, create_forecast, create_locked_forecast,
    actualize_forecast, fetch_forecast,
)

_DP = TEST_USERS["demand_planner_headers"]


def test_forecast_triple_is_unique(api):
    """PRD section 3.8: "that triple is unique: a second forecast for the
    same product, channel, and week is refused with
    `ERR_UNIQUE_CONSTRAINT`" — a different `forecast_cases` does not make it
    a different triple.

    Design: Corner/validations/cn_val_forecast_unique_conflict
    """
    product = create_bare_product(product_code="PROD-K-20")
    create_forecast(product["id"], channel="RETAIL_FROZEN",
                    week_start="2026-09-07T00:00:00Z", forecast_cases=200)
    resp = api.create_demand_forecast(
        create_demand_forecast_payload(
            product["id"], channel="RETAIL_FROZEN",
            week_start="2026-09-07T00:00:00Z", forecast_cases=300),
        _DP)
    validate_error(resp, ApiErrorId.ERR_UNIQUE_CONSTRAINT)


def test_forecast_actualize_before_lock_rejected(api):
    """PRD section 3.8: "Forecasts walk `PROVISIONAL` → `LOCKED` →
    `ACTUALIZED`" — skipping LOCKED fails the state cascade of PRD section
    2.8 (`ERR_INVALID_STATE`, 409), and "Until actualization, `actual_cases`,
    `variance_pct`, and `is_miss` are null."

    Design: Corner/state_machines/cn_sm_forecast_actualize_before_lock_returns_409
    """
    product = create_bare_product(product_code="PROD-K-7")
    forecast = create_forecast(product["id"], channel="RETAIL_FROZEN",
                               week_start="2026-09-07T00:00:00Z",
                               forecast_cases=200)
    resp = api.demand_forecast_transition(
        forecast["id"],
        forecast_transition_payload("ACTUALIZED", actual_cases=150),
        _DP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = fetch_forecast(forecast["id"])
    assert after["status"] == "PROVISIONAL"
    assert after["variance_pct"] is None


def test_variance_exactly_minus_20_is_a_miss(api):
    """PRD section 3.8: "`variance_pct` is the gap between actual and
    forecast cases expressed as a percentage of the forecast, rounded half-up
    to two decimal places, and `is_miss` is true when that variance reaches
    negative 20.00 percent or worse — a variance of exactly -20.00 percent is
    a miss." 160 of 200 is -20.00 (miss); 161 of 200 is -19.50 (not a miss).

    Design: Corner/calculations/cn_calc_variance_miss_boundary
    """
    product = create_bare_product(product_code="PROD-K-13")
    f1 = create_locked_forecast(product["id"], channel="RETAIL_FROZEN",
                                week_start="2026-09-07T00:00:00Z",
                                forecast_cases=200)
    f2 = create_locked_forecast(product["id"], channel="RETAIL_FROZEN",
                                week_start="2026-09-14T00:00:00Z",
                                forecast_cases=200)
    f1 = actualize_forecast(f1["id"], 160)
    assert f1["variance_pct"] == pytest.approx(-20.00, abs=1e-9)
    assert f1["is_miss"] is True
    f2 = actualize_forecast(f2["id"], 161)
    assert f2["variance_pct"] == pytest.approx(-19.50, abs=1e-9)
    assert f2["is_miss"] is False
