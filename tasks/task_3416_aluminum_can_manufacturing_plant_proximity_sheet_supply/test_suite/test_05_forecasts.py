"""Forecasts: accuracy dual variants, zero boundaries, duplicate periods,
terminal close (PRD §3.1, §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    set_clock, create_plant, create_customer, create_active_agreement,
    create_forecast, close_forecast, publish_index,
    make_customer_planner_headers, manager, admin, api_client,
)


def _active_agreement(api, committed=12_000_000, pass_through=0.9):
    set_clock()
    plant = create_plant()
    customer = create_customer()
    agreement = create_active_agreement(plant["id"], customer["id"],
                                        committed_annual_units=committed,
                                        pass_through_pct=pass_through)
    return plant, customer, agreement


class TestForecastAccuracyDualVariant:
    def test_forecast_accuracy_per_forecast_values(self, api):
        """PRD §3.7: "Closing stamps the forecast's `accuracy_pct`: defined as
        100 when both the forecast and the actual are 0, and otherwise 100 times
        one minus the absolute gap between `forecast_qty` and `actual_qty`
        divided by the larger of the two, rounded half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/forecast_accuracy_rolling_mean_vs_lifetime_ratio
        """
        _plant, _cust, agr = _active_agreement(api)
        f1 = create_forecast(agr, "2026-06", 100000)
        f2 = create_forecast(agr, "2026-07", 120000)
        f3 = create_forecast(agr, "2026-08", 110000)
        c1 = close_forecast(agr, f1["id"], 90000)
        c2 = close_forecast(agr, f2["id"], 150000)
        c3 = close_forecast(agr, f3["id"], 110000)
        assert c1["accuracy_pct"] == pytest.approx(90.00, abs=0.005)
        assert c2["accuracy_pct"] == pytest.approx(80.00, abs=0.005)
        assert c3["accuracy_pct"] == pytest.approx(100.00, abs=0.005)

    def test_forecast_accuracy_rolling_mean_vs_lifetime_ratio(self, api):
        """PRD §3.7: "The `rolling_accuracy_pct` is a mean of ratios: the mean
        of `accuracy_pct` over the up-to-three most recent closed forecasts...
        The `lifetime_accuracy_pct` is a ratio of aggregates: 100 times one
        minus the absolute difference between the summed `forecast_qty` and the
        summed `actual_qty` across all closed forecasts, divided by the larger
        of the two sums".

        Design: Difficulty/dual_variant_calc/forecast_accuracy_rolling_mean_vs_lifetime_ratio
        """
        _plant, _cust, agr = _active_agreement(api)
        f1 = create_forecast(agr, "2026-06", 100000)
        f2 = create_forecast(agr, "2026-07", 120000)
        f3 = create_forecast(agr, "2026-08", 110000)
        close_forecast(agr, f1["id"], 90000)
        close_forecast(agr, f2["id"], 150000)
        close_forecast(agr, f3["id"], 110000)
        data = validate_success(api.get_agreement(agr["id"], manager()))
        # mean-of-ratios: (90.00 + 80.00 + 100.00) / 3
        assert data["rolling_accuracy_pct"] == pytest.approx(90.00, abs=0.005)
        # ratio-of-aggregates: 100 * (1 - |330000 - 350000| / 350000)
        assert data["lifetime_accuracy_pct"] == pytest.approx(94.29, abs=0.005)
        assert data["rolling_accuracy_pct"] != pytest.approx(
            data["lifetime_accuracy_pct"], abs=0.005)


class TestForecastZeroBoundary:
    def test_forecast_zero_forecast_zero_actual_accuracy_defined_100(self, api):
        """PRD §3.7: "Closing stamps the forecast's `accuracy_pct`: defined as
        100 when both the forecast and the actual are 0".

        Design: Difficulty/boundary_precision_check/forecast_zero_forecast_zero_actual_accuracy_defined_100
        """
        _plant, _cust, agr = _active_agreement(api)
        fz = create_forecast(agr, "2026-06", 0)
        closed = close_forecast(agr, fz["id"], 0)
        assert closed["status"] == "CLOSED"
        assert closed["accuracy_pct"] == pytest.approx(100.00, abs=0.005)

    def test_forecast_zero_actual_with_positive_forecast_yields_zero(self, api):
        """PRD §3.7: "otherwise 100 times one minus the absolute gap between
        `forecast_qty` and `actual_qty` divided by the larger of the two".

        Design: Difficulty/boundary_precision_check/forecast_zero_forecast_zero_actual_accuracy_defined_100
        """
        _plant, _cust, agr = _active_agreement(api)
        fn = create_forecast(agr, "2026-07", 5000)
        closed = close_forecast(agr, fn["id"], 0)
        # 100 * (1 - 5000 / max(5000, 0)) == 0
        assert closed["accuracy_pct"] == pytest.approx(0.00, abs=0.005)


class TestForecastTerminalAndDuplicate:
    def test_forecast_close_twice_returns_invalid_state(self, api):
        """PRD §3.7: "`CLOSED` is terminal." PRD §2.7 gate 6: "the target
        resource's own from-state for the requested transition
        (`ERR_INVALID_STATE`, HTTP 409, including attempts made from terminal
        states)".

        Design: Corner/state_machines/forecast_close_twice_returns_invalid_state
        """
        _plant, _cust, agr = _active_agreement(api)
        f = create_forecast(agr, "2026-06", 100000)
        close_forecast(agr, f["id"], 90000)
        resp = api.close_forecast(f["id"], {"actual_qty": 99999},
                                  make_customer_planner_headers(agr["customer_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data = validate_paginated(api.list_forecasts(agr["id"], manager()))[0]
        assert len(data) == 1
        assert data[0]["actual_qty"] == 90000
        assert data[0]["accuracy_pct"] == pytest.approx(90.00, abs=0.005)

    def test_duplicate_period_rejected_for_forecast_and_for_index(self, api):
        """PRD §3.7: "Periods are unique per agreement: a second forecast for a
        period the agreement already has is rejected with
        `ERR_DUPLICATE_PERIOD`." PRD §3.1: "Periods are globally unique — a
        second publication for a period that already exists is rejected with
        `ERR_DUPLICATE_PERIOD`."

        Design: Corner/entities/duplicate_period_rejected_for_forecast_and_for_index
        """
        set_clock()
        plant = create_plant()
        cust1 = create_customer(name="C1", home_region="US-SW")
        cust2 = create_customer(name="C2", home_region="US-NE")
        agr1 = create_active_agreement(plant["id"], cust1["id"])
        agr2 = create_active_agreement(plant["id"], cust2["id"],
                                       committed_annual_units=2_000_000)
        publish_index("2026-08", 128.0)
        create_forecast(agr1, "2026-06", 100000)
        resp_fc = api.create_forecast(agr1["id"],
                                      {"period": "2026-06", "forecast_qty": 50000},
                                      make_customer_planner_headers(cust1["id"]))
        validate_error(resp_fc, ApiErrorId.ERR_DUPLICATE_PERIOD)
        resp_idx = api.publish_index({"period": "2026-08",
                                      "index_cents_per_lb": 140.0}, admin())
        validate_error(resp_idx, ApiErrorId.ERR_DUPLICATE_PERIOD)
        # The same period on a DIFFERENT agreement is allowed.
        other = create_forecast(agr2, "2026-06", 70000)
        assert other["status"] == "OPEN"
        rows, _meta = validate_paginated(api.list_forecasts(agr1["id"], manager()))
        assert len(rows) == 1
