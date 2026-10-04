"""Sell-through reports: the raw vs seasonally-adjusted cannibalization
variants and the reported-week window gate.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    SeasonalProgramStatus,
    TEST_USERS,
    api_client,
    assert_sell_through_report,
    compute_cannibalization_adjusted,
    compute_cannibalization_raw,
    create_sell_through_report_payload,
    get_program,
    make_retailer_headers,
    setup_on_shelf_program,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_cannibalization_raw_variant_divides_by_baseline(api):
    """PRD §3.7: "The **raw** variant, `cannibalization_raw`, is the week's
    `everyday_units_sold` divided by the retailer account's
    `everyday_baseline_weekly_units` — a reading of how the everyday shelf
    actually performed against its own baseline." Both variants are "rounded
    half-up to 4 decimal places" (PRD §3.7).

    Design: Difficulty/dual_variant_calc/cannibalization_raw_vs_seasonally_adjusted
    """
    world = setup_on_shelf_program(produced_units=10)
    retailer = world["retailer"]  # GOLD, everyday_baseline_weekly_units 1000
    resp = api_client.create_sell_through_report(
        create_sell_through_report_payload(
            retailer_id=retailer["id"], program_id=world["program"]["id"],
            week_of_on="2027-10-04T00:00:00Z",
            seasonal_units_sold=120, seasonal_units_on_hand=300,
            everyday_units_sold=880,
        ),
        make_retailer_headers(retailer["id"]),
    )
    data = validate_success(resp, 201)
    assert_sell_through_report(data)
    # 880 / 1000 = 0.8800 at 4dp round half-up.
    assert data["cannibalization_raw"] == pytest.approx(0.88, abs=1e-9)
    assert data["cannibalization_raw"] == pytest.approx(
        compute_cannibalization_raw(880, 1000), abs=1e-9,
    )
    # Reports do not mutate program state.
    assert get_program(world["program"]["id"])["status"] == (
        SeasonalProgramStatus.ON_SHELF.value
    )


def test_cannibalization_adjusted_variant_divides_by_lift_scaled_baseline(api):
    """PRD §3.7: "The **seasonally adjusted** variant,
    `cannibalization_adjusted`, divides the same `everyday_units_sold` by the
    baseline scaled up by the season's expected everyday lift: the lift
    constant is 1.10 for a `VALENTINES` program, 1.15 for `EASTER`, 1.25 for
    `HALLOWEEN`, and 1.20 for `CHRISTMAS`. Because every season's lift is
    greater than 1, identical report data always yields an adjusted value
    below the raw value."

    Design: Difficulty/dual_variant_calc/cannibalization_raw_vs_seasonally_adjusted
    """
    world = setup_on_shelf_program(produced_units=10)
    retailer = world["retailer"]
    resp = api_client.create_sell_through_report(
        create_sell_through_report_payload(
            retailer_id=retailer["id"], program_id=world["program"]["id"],
            week_of_on="2027-10-04T00:00:00Z",
            seasonal_units_sold=120, seasonal_units_on_hand=300,
            everyday_units_sold=880,
        ),
        make_retailer_headers(retailer["id"]),
    )
    data = validate_success(resp, 201)
    # 880 / (1000 x 1.25) = 0.7040 at 4dp round half-up.
    assert data["cannibalization_adjusted"] == pytest.approx(0.704, abs=1e-9)
    assert data["cannibalization_adjusted"] == pytest.approx(
        compute_cannibalization_adjusted(880, 1000, "HALLOWEEN"), abs=1e-9,
    )
    assert data["cannibalization_adjusted"] != data["cannibalization_raw"]
    assert data["cannibalization_adjusted"] < data["cannibalization_raw"]


def test_report_week_before_on_shelf_returns_week_out_of_window(api):
    """PRD §3.7: "`week_of_on`, the Monday of the reported week, which must
    lie inside the inclusive interval from the program's `on_shelf_on` to its
    `pull_on`; a week outside that interval is rejected with
    `ERR_REPORT_WEEK_OUT_OF_WINDOW` (HTTP 422)."

    Design: Corner/validations/report_week_before_on_shelf_returns_week_out_of_window
    """
    world = setup_on_shelf_program(produced_units=10)
    retailer = world["retailer"]
    # 2027-08-01 precedes the default program's on_shelf_on (2027-09-20); the
    # window binds the REPORTED week, not the filing instant.
    resp = api_client.create_sell_through_report(
        create_sell_through_report_payload(
            retailer_id=retailer["id"], program_id=world["program"]["id"],
            week_of_on="2027-08-01T00:00:00Z",
            seasonal_units_sold=10, seasonal_units_on_hand=90,
            everyday_units_sold=1000,
        ),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_WEEK_OUT_OF_WINDOW)
    rows, _meta = validate_paginated(api_client.list_sell_through_reports(
        ADMIN, params={"program_id": world["program"]["id"]},
    ))
    assert rows == []
