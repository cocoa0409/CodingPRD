"""Performance evaluation: streaks, delivery plan, actuals payback (PRD §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_lot_conservation,
    create_released_lot,
    create_retire_remove_payload,
    create_shipment_payload,
    evaluate_performance,
    get_placement,
    setup_active_placement,
    validate_error,
    validate_success,
)


def test_actuals_payback_diverges_from_proforma(api, placement_manager_headers):
    """PRD §3.6: "The two variants answer different questions with the same
    economics: at a snapshot cost of 399000 cents, a forecast of 200 units per
    week implies a 2.56-month pro-forma payback, while reported actuals of 100
    units per week imply 5.12 months."
    PRD §3.6: "The actuals payback, `payback_actuals_months`, reruns the
    payback calculation of §3.1 on `trailing_weekly_units` against the
    placement's snapshot `installed_quote_cents` — same pinned rounding order,
    same zero-velocity guard leaving the field null when rounded monthly units
    are zero."

    Design: Difficulty/dual_variant_calc/payback_proforma_vs_actuals_divergence
    """
    ctx = setup_active_placement()
    placement = ctx["placement"]
    assert placement["installed_quote_cents"] == 399250
    assert ctx["evaluation"]["payback_months"] == pytest.approx(2.56, abs=0.005)

    data = validate_success(
        api.evaluate_performance(placement["id"], {"trailing_weekly_units": 100}, placement_manager_headers),
        expected_status=200,
    )
    # round_half_up(100*13/3) = 433 monthly units; margin 433*180 = 77940; 399250/77940 = 5.12.
    assert data["payback_actuals_months"] == pytest.approx(5.12, abs=0.005)
    assert data["payback_actuals_months"] != ctx["evaluation"]["payback_months"], (
        "identical quote, different velocity basis: ACTUALS must diverge from PRO_FORMA"
    )


def test_actuals_payback_evaluation_side_effects(api, placement_manager_headers):
    """PRD §3.6: "at 40 or more the placement's `performance_status` becomes
    `PERFORMING` and its `underperforming_streak` resets to 0"
    PRD §3.6: "Every evaluation also records the report in
    `last_reported_weekly_units`, recomputes the delivery plan and the actuals
    payback, and increments the placement's `version`."

    Design: Difficulty/dual_variant_calc/payback_proforma_vs_actuals_divergence
    """
    ctx = setup_active_placement()
    placement = ctx["placement"]
    data = validate_success(
        api.evaluate_performance(placement["id"], {"trailing_weekly_units": 100}, placement_manager_headers),
        expected_status=200,
    )
    assert data["performance_status"] == "PERFORMING", "100 >= 40 velocity floor"
    assert data["underperforming_streak"] == 0
    assert data["last_reported_weekly_units"] == 100
    assert data["version"] == placement["version"] + 1
    assert data["payback_actuals_months"] == pytest.approx(5.12, abs=0.005)


def test_delivery_plan_initialized_from_forecast(api, placement_manager_headers):
    """PRD §3.6: "The delivery plan tiers standing frequency by velocity: 5
    deliveries per week at 300 or more units, 3 at 150 or more, 2 at 60 or
    more, 1 at 25 or more, and 0 below 25 — each tier boundary inclusive on its
    lower bound."
    PRD §3.6: "The `safety_stock_units` ceiling is the smaller of the chiller's
    `capacity_units` and the velocity times the 45-day shelf life divided by 7
    days and multiplied by the safety factor 1.25, rounded half up to whole
    units."

    Design: Difficulty/combinatorial_formula/delivery_frequency_tiered_capacity_floor
    """
    ctx = setup_active_placement()
    placement = ctx["placement"]
    assert placement["standing_deliveries_per_week"] == 3, "forecast 200 -> tier 150..299"
    assert placement["safety_stock_units"] == 240, "min(240, round_half_up(200*45/7*1.25) = 1607) floors at capacity"


def test_delivery_tier_boundary_300_inclusive(api, placement_manager_headers):
    """PRD §3.6: "The delivery plan tiers standing frequency by velocity: 5
    deliveries per week at 300 or more units, 3 at 150 or more, 2 at 60 or
    more, 1 at 25 or more, and 0 below 25 — each tier boundary inclusive on its
    lower bound."

    Design: Difficulty/combinatorial_formula/delivery_frequency_tiered_capacity_floor
    """
    ctx = setup_active_placement()
    placement = ctx["placement"]
    hi = validate_success(
        api.evaluate_performance(placement["id"], {"trailing_weekly_units": 300}, placement_manager_headers),
        expected_status=200,
    )
    assert hi["standing_deliveries_per_week"] == 5, "tier boundary 300 inclusive"
    assert hi["safety_stock_units"] == 240, "min(240, round_half_up(300*45/7*1.25) = 2411) floors at capacity"
    assert hi["performance_status"] == "PERFORMING"

    lo = validate_success(
        api.evaluate_performance(placement["id"], {"trailing_weekly_units": 299}, placement_manager_headers),
        expected_status=200,
    )
    assert lo["standing_deliveries_per_week"] == 3, "299 sits just below the inclusive boundary"
    assert lo["performance_status"] == "PERFORMING"


def test_derived_plan_fields_recompute_each_evaluation(api, placement_manager_headers):
    """PRD §3.6: "Every evaluation also records the report in
    `last_reported_weekly_units`, recomputes the delivery plan and the actuals
    payback, and increments the placement's `version`."
    PRD §3.6: "The delivery plan tiers standing frequency by velocity: 5
    deliveries per week at 300 or more units, 3 at 150 or more, 2 at 60 or
    more, 1 at 25 or more, and 0 below 25 — each tier boundary inclusive on its
    lower bound."

    Design: Corner/cross_cutting_layers/derived_plan_fields_recompute_each_evaluation
    """
    ctx = setup_active_placement()
    placement = ctx["placement"]
    assert placement["standing_deliveries_per_week"] == 3
    assert placement["safety_stock_units"] == 240

    steps = [
        (100, 2, 240),   # min(240, round_half_up(100*45/7*1.25) = 804)
        (300, 5, 240),   # min(240, 2411)
        (20, 0, 161),    # min(240, round_half_up(20*45/7*1.25) = 161)
    ]
    for units, expected_freq, expected_stock in steps:
        data = validate_success(
            api.evaluate_performance(placement["id"], {"trailing_weekly_units": units},
                                     placement_manager_headers),
            expected_status=200,
        )
        assert data["standing_deliveries_per_week"] == expected_freq, f"velocity {units}"
        assert data["safety_stock_units"] == expected_stock, f"velocity {units}"
        assert data["last_reported_weekly_units"] == units


def test_underperformance_streak_reset_then_insufficient(api, placement_manager_headers):
    """PRD §3.6: "at 40 or more the placement's `performance_status` becomes
    `PERFORMING` and its `underperforming_streak` resets to 0; below 40 it
    becomes `UNDERPERFORMING` and the streak advances — to 1 when arriving from
    `PERFORMING` or from a `PENDING` state whose streak is 0, and otherwise one
    more than the previous streak."
    PRD §3.6: "the reason `UNDERPERFORMANCE_REMOVAL` is gated on evidence: the
    placement's `performance_status` must be `UNDERPERFORMING` with an
    `underperforming_streak` of at least 2, otherwise 409
    `ERR_UNDERPERFORMANCE_STREAK_INSUFFICIENT`."

    Design: Corner/calculations/underperformance_streak_reset_then_insufficient
    """
    ctx = setup_active_placement()
    pid = ctx["placement"]["id"]
    r1 = validate_success(api.evaluate_performance(pid, {"trailing_weekly_units": 30}, placement_manager_headers))
    assert r1["performance_status"] == "UNDERPERFORMING" and r1["underperforming_streak"] == 1
    r2 = validate_success(api.evaluate_performance(pid, {"trailing_weekly_units": 45}, placement_manager_headers))
    assert r2["performance_status"] == "PERFORMING" and r2["underperforming_streak"] == 0, "PERFORMING resets"
    r3 = validate_success(api.evaluate_performance(pid, {"trailing_weekly_units": 20}, placement_manager_headers))
    assert r3["performance_status"] == "UNDERPERFORMING" and r3["underperforming_streak"] == 1, "streak restarts at 1"

    resp = api.retire_placement(pid, create_retire_remove_payload(), placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_UNDERPERFORMANCE_STREAK_INSUFFICIENT)
    assert resp.status_code == 409, "streak 1 < 2 blocks UNDERPERFORMANCE_REMOVAL"

    frozen = get_placement(pid)
    assert frozen["status"] == "ACTIVE"
    assert frozen["performance_status"] == "UNDERPERFORMING"
    assert frozen["underperforming_streak"] == 1


def test_frequency_zero_tier_blocks_shipments(api, placement_manager_headers, logistics_coordinator_headers):
    """PRD §3.6: "The delivery plan tiers standing frequency by velocity: ...
    and 0 below 25 — each tier boundary inclusive on its lower bound."
    PRD §3.7: "its `standing_deliveries_per_week` must be greater than 0
    (otherwise 409 `ERR_DELIVERY_ROUTE_INACTIVE`)"

    Design: Corner/calculations/frequency_zero_tier_blocks_shipments
    """
    ctx = setup_active_placement()
    lot = create_released_lot(quantity_units=100)
    data = validate_success(
        api.evaluate_performance(ctx["placement"]["id"], {"trailing_weekly_units": 10}, placement_manager_headers),
        expected_status=200,
    )
    assert data["standing_deliveries_per_week"] == 0, "10 < 25 lowest tier"
    assert data["safety_stock_units"] == 80, "min(240, round_half_up(10*45/7*1.25) = 80)"

    resp = api.create_shipment(
        create_shipment_payload(ctx["store"]["id"], lot["id"], 10), logistics_coordinator_headers
    )
    validate_error(resp, ApiErrorId.ERR_DELIVERY_ROUTE_INACTIVE)
    assert resp.status_code == 409


def test_evaluate_retired_placement_returns_409(api, placement_manager_headers):
    """PRD §3.6: "The placement must be `ACTIVE`, or the call fails with 409
    `ERR_PLACEMENT_NOT_ACTIVE`."
    PRD §3.6: "Retirement stamps `retired_reason`, returns the chiller from
    `INSTALLED`, `ACTIVE`, or `NEEDS_REPAIR` to `IN_STOCK` (chiller `version`
    increments), cancels that chiller's `OPEN` and `DISPATCHED` tickets, and
    increments the placement's `version` as it lands in terminal `RETIRED`."

    Design: Corner/state_machines/evaluate_retired_placement_returns_409
    """
    ctx = setup_active_placement()
    pid = ctx["placement"]["id"]
    evaluate_performance(pid, 10)
    retired_source = evaluate_performance(pid, 20)
    assert retired_source["underperforming_streak"] == 2
    resp = api.retire_placement(pid, create_retire_remove_payload(), placement_manager_headers)
    retired = validate_success(resp, expected_status=200)
    assert retired["status"] == "RETIRED"

    resp = api.evaluate_performance(pid, {"trailing_weekly_units": 90}, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_PLACEMENT_NOT_ACTIVE)
    assert resp.status_code == 409

    frozen = get_placement(pid)
    assert frozen["status"] == "RETIRED"
    assert frozen["performance_status"] == "UNDERPERFORMING", "retired dimension values stay frozen"
    assert frozen["underperforming_streak"] == 2
