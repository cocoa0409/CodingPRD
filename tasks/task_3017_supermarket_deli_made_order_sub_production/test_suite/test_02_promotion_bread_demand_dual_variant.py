"""Promotion bread demand: the provisional forecast against the settled one."""

from test_helpers import (
    api_client,
    create_promotion_payload,
    get_success_data,
    manager_headers,
    platform_admin_headers,
    set_clock,
    setup_deli_master_data,
    validate_success,
)


def _setup_high_uplift_promotion():
    """Store + featured sub + one 1.65-uplift promotion activated for its week."""
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two", slicer_count=0)
    promotion = get_success_data(
        api_client.create_promotion(
            create_promotion_payload(
                promo_code="FEAT-0914",
                deli_item_id=master.j1["id"],
                week_start_date="2026-09-07T00:00:00Z",
                week_end_date="2026-09-14T00:00:00Z",
                forecast_uplift_pct=1.65,
                trailing_baseline_units=240,
            ),
            platform_admin_headers(),
        )
    )
    # PRD §3.5 requires the clock to sit inside the half-open week to activate.
    set_clock("2026-09-07T00:00:00Z")
    activated = get_success_data(
        api_client.activate_promotion(promotion["id"], manager_headers(master.a2["id"]))
    )
    return master, activated


def test_active_promotion_forecasts_with_the_full_uplift():
    """PRD §3.5: "The raw uplift is the promotion's `forecast_uplift_pct` under the
    provisional variant, and the smaller of that figure and a cap of 0.35 under
    the settled variant."
    PRD §3.5: "The provisional variant, written to `required_bread_units`,
    applies the full uplift and therefore over-orders bread for a promotion whose
    uplift sits above the settlement cap."

    Design: Difficulty/dual_variant_calc/bread_demand_dual_variant_on_promotion
    """
    _, promotion = _setup_high_uplift_promotion()
    assert promotion["status"] == "ACTIVE"
    assert promotion["required_bread_units"] == 720, (
        "a 1.65 uplift over 240 baseline units forecasts 720 case-rounded units"
    )


def test_settlement_caps_the_uplift_and_shrinks_the_bread_demand():
    """PRD §3.5: "The settled variant, written to `settled_bread_units` at
    settlement, caps the uplift at 0.35 first, so identical input data yields a
    smaller bread demand."

    Design: Difficulty/dual_variant_calc/bread_demand_dual_variant_on_promotion
    """
    master, promotion = _setup_high_uplift_promotion()
    set_clock("2026-09-15T00:00:00Z")
    sett = validate_success(
        api_client.settle_promotion(promotion["id"], manager_headers(master.a2["id"]))
    )
    assert sett["status"] == "SETTLED"
    assert sett["required_bread_units"] == 720, (
        "the provisional write is not one of the terms settlement clears"
    )
    assert sett["settled_bread_units"] == 372, (
        "the settled variant caps the uplift at 0.35 before forecasting"
    )
    assert sett["settled_bread_units"] != sett["required_bread_units"], (
        "identical input data must yield a smaller settled demand"
    )