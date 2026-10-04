"""Production forecasts and the weekly settlement: variants, rounding, fill judging."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_active_farm,
    create_commitment,
    create_forecast,
    create_retailer,
    create_settlement_run,
    finalize_settlement,
    get_commitment,
    get_settlement_run,
    setup_collected_lot,
    setup_commitment_scenario,
    setup_packed_week,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers import MIN_FILL_RATE

NM = TEST_USERS["network_manager_headers"]


def _forecast_2000_bird_farm():
    """ACTIVE farm declaring 2000 birds with effective capacity exactly 2000."""
    return create_active_farm(
        name="Big Sky Layers",
        region="MO",
        pasture_sqft=216000,
        barn_sqft=2400,
        nest_box_count=400,
        declared_bird_count=2000,
    )["farm"]


def test_forecast_optimistic_variant_uses_p50_factors(api):
    """PRD §3.7: "For each variant, the weekly egg count is the bird count
    multiplied by the season's lay rate, multiplied by the variant's weather
    factor for the declared severity, multiplied by 7 days; dividing that
    product by 12 eggs per dozen and flooring — with no intermediate rounding
    anywhere in the chain — yields the variant's dozens."
    PRD §3.7: "The optimistic variant — the P50 planning view shown to network
    planners — applies weather factors of 1.00 for `NONE`, 0.95 for `MODERATE`,
    and 0.88 for `SEVERE`."

    Design: Difficulty/dual_variant_calc/forecast_optimistic_vs_conservative_weather_hedge
    """
    farm = _forecast_2000_bird_farm()
    forecast = create_forecast(farm["id"], "2026-09-07", "SPRING", "MODERATE")
    assert forecast["optimistic_dozens"] == 908, (
        f"floor(2000 x 0.82 x 0.95 x 7 / 12) == 908, got {forecast['optimistic_dozens']}"
    )


def test_forecast_conservative_variant_uses_p90_factors(api):
    """PRD §3.7: "The conservative variant — the P90 weather-hedged view that is
    the sole basis for commitment caps — applies 0.98 for `NONE`, 0.88 for
    `MODERATE`, and 0.75 for `SEVERE`."
    PRD §3.7: "the conservative figure is strictly lower than the optimistic one
    whenever `weather_severity` is not `NONE`"

    Design: Difficulty/dual_variant_calc/forecast_optimistic_vs_conservative_weather_hedge
    """
    farm = _forecast_2000_bird_farm()
    forecast = create_forecast(farm["id"], "2026-09-07", "SPRING", "MODERATE")
    assert forecast["conservative_dozens"] == 841, (
        f"floor(2000 x 0.82 x 0.88 x 7 / 12) == 841, got {forecast['conservative_dozens']}"
    )
    assert forecast["optimistic_dozens"] != forecast["conservative_dozens"], (
        "identical inputs yield divergent variants under the tiered factors"
    )


def _tiered_winter_scenario():
    """ACTIVE farm (1500 birds, capacity exactly 1500) + retailer + a
    WINTER/SEVERE forecast for week 2026-12-07."""
    farm = create_active_farm(
        name="Frost Hollow Farm",
        region="MN",
        pasture_sqft=162000,
        barn_sqft=1800,
        nest_box_count=300,
        declared_bird_count=1500,
    )["farm"]
    retailer = create_retailer()
    forecast = create_forecast(farm["id"], "2026-12-07", "WINTER", "SEVERE")
    return farm, retailer, forecast


def test_forecast_tiered_factor_interaction_variants(api):
    """PRD §3.7: "The lay rates are 0.82 eggs per bird per day in `SPRING`, 0.78
    in `SUMMER`, 0.72 in `AUTUMN`, and 0.61 in `WINTER`."
    PRD §3.7: "Because the three lookups multiply, the ratio between variants is
    not constant across severity levels"

    Design: Difficulty/combinatorial_formula/forecast_tiered_factor_interaction
    """
    _, _, forecast = _tiered_winter_scenario()
    assert forecast["optimistic_dozens"] == 469, (
        f"floor(1500 x 0.61 x 0.88 x 7 / 12) == 469, got {forecast['optimistic_dozens']}"
    )
    assert forecast["conservative_dozens"] == 400, (
        f"floor(1500 x 0.61 x 0.75 x 7 / 12) == 400, got {forecast['conservative_dozens']}"
    )


def test_commitment_cap_honored_at_exact_equality(api):
    """PRD §3.7: "the sum of `committed_dozens` over all of the farm's
    commitments for that week in `ACTIVE`, `FILLED`, or `SHORTFALL` status —
    cancelled commitments release their room — plus the new `committed_dozens`
    must not exceed the farm's conservative forecast for the week scaled down by
    nine-tenths and floored to whole dozens. Equality with the cap is permitted;
    exceeding it is rejected with `ERR_COMMITMENT_EXCEEDS_FORECAST` (HTTP 422)."

    Design: Difficulty/combinatorial_formula/forecast_tiered_factor_interaction
    """
    farm, retailer, _ = _tiered_winter_scenario()
    # cap == floor(400 x 0.9) == 360; a commitment of exactly 360 is accepted.
    commitment = create_commitment(retailer["id"], farm["id"], "2026-12-07", 360)
    assert commitment["committed_dozens"] == 360
    assert commitment["status"] == "ACTIVE"


def _settlement_scenario_single_grade():
    """ACTIVE farm (140 birds, contract 150+90) with 50 grade-A dozens packed at
    2026-09-08T10:00:00Z, then a settlement run for week 2026-09-07."""
    farm = create_active_farm(name="Prairie Sun Farm")["farm"]
    setup_packed_week(farm["id"], [(90, 50, "LARGE")])
    run = create_settlement_run("2026-09-07")
    return farm, run


def test_farmer_payment_provisional_uses_contract_base(api):
    """PRD §3.8: "the provisional pass uses the contract's own
    `commodity_base_cents_per_dozen` plus its `premium_cents_per_dozen`"
    PRD §3.8: "The quality multipliers are 1.10 for `AA`, 1.00 for `A`, and 0.85
    for `B`."

    Design: Difficulty/dual_variant_calc/farmer_payment_provisional_vs_final_commodity_base
    """
    farm, run = _settlement_scenario_single_grade()
    assert run["status"] == "CALCULATED"
    assert run["provisional_total_cents"] == 12000, (
        f"50 A-dozens x (150 + 90)c x 1.00 == 12000, got {run['provisional_total_cents']}"
    )
    line = next(l for l in run["lines"] if l["farm_id"] == farm["id"])
    assert line["dozens_a"] == 50
    assert line["provisional_cents"] == 12000
    assert line["final_cents"] is None


def test_farmer_payment_final_uses_actual_base(api):
    """PRD §3.8: "the final pass uses the published actual commodity base plus
    the same `premium_cents_per_dozen`. The two variants therefore differ for
    identical packed data whenever the actual base differs from the contract's
    base."
    PRD §3.8: "Finalization recomputes every line on the final basis and writes
    `final_cents` per line and `final_total_cents` on the run, records the
    actual base on the run, stamps `finalized_at`, moves the run `CALCULATED →
    FINALIZED` (its terminal state), and increments its `version` by one."

    Design: Difficulty/dual_variant_calc/farmer_payment_provisional_vs_final_commodity_base
    """
    farm, run = _settlement_scenario_single_grade()
    finalized = finalize_settlement(run["id"], 165)
    assert finalized["status"] == "FINALIZED"
    assert finalized["provisional_total_cents"] == 12000
    assert finalized["final_total_cents"] == 12750, (
        f"50 A-dozens x (165 + 90)c x 1.00 == 12750, got {finalized['final_total_cents']}"
    )
    assert finalized["final_total_cents"] - finalized["provisional_total_cents"] == 750


def _settlement_scenario_three_grades():
    """ACTIVE farm with 3 AA + 17 B + 10 A dozens packed inside week
    2026-09-07, then the settlement run for that week."""
    farm = create_active_farm(name="Clover Bend Farm", region="AR")["farm"]
    setup_packed_week(
        farm["id"],
        [(96, 3, "LARGE"), (75, 17, "MEDIUM"), (90, 10, "EXTRA_LARGE")],
    )
    run = create_settlement_run("2026-09-07")
    return farm, run


def test_payment_rounding_order_provisional_breakdown(api):
    """PRD §3.8: "for each grade, the subline amount is that grade's dozens
    multiplied by the per-dozen rate in cents multiplied by the grade's quality
    multiplier, rounded half up to whole cents; the line total is the sum of the
    three grade sublines."

    Design: Difficulty/combinatorial_formula/payment_per_grade_subline_rounding_order
    """
    farm, run = _settlement_scenario_three_grades()
    line = next(l for l in run["lines"] if l["farm_id"] == farm["id"])
    assert line["dozens_aa"] == 3
    assert line["dozens_a"] == 10
    assert line["dozens_b"] == 17
    # rate 240c: 3x240x1.10=792 + 10x240x1.00=2400 + 17x240x0.85=3468
    assert run["provisional_total_cents"] == 6660, (
        f"792 + 2400 + 3468 == 6660, got {run['provisional_total_cents']}"
    )


def test_payment_rounding_order_final_pins_subline_first(api):
    """PRD §2.10: "Per-grade payment sublines are rounded half up to whole cents
    individually, before any summation, and only then summed into line and run
    totals — the rounding order is pinned and must not be reversed."

    Design: Difficulty/combinatorial_formula/payment_per_grade_subline_rounding_order
    """
    farm, run = _settlement_scenario_three_grades()
    finalized = finalize_settlement(run["id"], 165)
    # rate 255c: round_half_up(3x255x1.10)=842 + 2550 + round_half_up(17x255x0.85)=3685
    # -> 7077 (sum-then-round would yield 7076)
    assert finalized["final_total_cents"] == 7077, (
        f"per-grade-subline rounding order yields 7077, got "
        f"{finalized['final_total_cents']}"
    )


def _fill_scenario(packed_dozens):
    """Commitment of 40 dozen for week 2026-09-07 plus `packed_dozens` cartons
    packed inside that week; settlement finalized with actual base 165."""
    ctx = setup_commitment_scenario(week_start="2026-09-07", season="AUTUMN",
                                    weather_severity="NONE", committed_dozens=40,
                                    farm_name="Fill Boundary Farm")
    setup_packed_week(ctx["farm"]["id"], [(90, packed_dozens, "LARGE")])
    run = create_settlement_run("2026-09-07")
    finalize_settlement(run["id"], 165)
    return ctx


def test_fill_threshold_inclusive_boundary_filled(api):
    """PRD §3.8: "The fill threshold is the `committed_dozens` multiplied by
    0.85 and floored to whole dozens; a commitment whose `delivered_dozens`
    meets or exceeds that threshold is marked `FILLED`, and one that falls short
    is marked `SHORTFALL`."
    PRD §3.8: "its `fill_rate` is recorded as the delivered dozens divided by
    the committed dozens, rounded half up to exactly 4 decimal places."

    Design: Corner/calculations/fill_threshold_inclusive_boundary_filled
    """
    ctx = _fill_scenario(34)
    commitment = get_commitment(ctx["commitment"]["id"])
    assert commitment["status"] == "FILLED", (
        "delivered 34 >= floor(40 x 0.85) == 34 — the inclusive boundary fills"
    )
    assert commitment["delivered_dozens"] == 34
    assert commitment["fill_rate"] == pytest.approx(MIN_FILL_RATE, abs=1e-9)


def test_fill_below_threshold_marks_shortfall(api):
    """PRD §3.8: "The fill threshold is the `committed_dozens` multiplied by
    0.85 and floored to whole dozens; a commitment whose `delivered_dozens`
    meets or exceeds that threshold is marked `FILLED`, and one that falls short
    is marked `SHORTFALL`."

    Design: Corner/calculations/fill_below_threshold_marks_shortfall
    """
    ctx = _fill_scenario(33)
    commitment = get_commitment(ctx["commitment"]["id"])
    assert commitment["status"] == "SHORTFALL", "33 < 34 flips the outcome to SHORTFALL"
    assert commitment["delivered_dozens"] == 33
    assert commitment["fill_rate"] == pytest.approx(0.825, abs=1e-9)


def test_payment_ignores_farms_without_packed_cartons(api):
    """PRD §3.8: "one line per farm that had cartons packed with `packed_at`
    inside the week"

    Design: Corner/calculations/payment_ignores_farms_without_packed_cartons
    """
    farm_a = create_active_farm(name="Packing Farm A")["farm"]
    farm_b = create_active_farm(
        name="Idle Farm B", audit_complete_at="2026-09-03T10:00:00Z"
    )["farm"]
    setup_packed_week(farm_a["id"], [(90, 10, "LARGE")])

    run = create_settlement_run("2026-09-07")
    assert len(run["lines"]) == 1, (
        f"only the farm with packed cartons earns a line, got {len(run['lines'])}"
    )
    assert run["lines"][0]["farm_id"] == farm_a["id"]
    assert run["lines"][0]["farm_id"] != farm_b["id"]
    assert run["provisional_total_cents"] == 2400, "10 A-dozens x 240c x 1.00"


def test_settlement_duplicate_week_rejected(api):
    """PRD §3.8: "only one settlement run may exist per week, and a second
    opening for the same `week_start` is rejected with `ERR_DUPLICATE_SETTLEMENT`
    (HTTP 409)."

    Design: Corner/state_machines/settlement_duplicate_week_rejected
    """
    create_settlement_run("2026-09-07")
    resp = api.create_settlement_run({"week_start": "2026-09-07"}, NM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SETTLEMENT, 409)


def test_settlement_finalize_twice_returns_invalid_state(api):
    """PRD §3.8: "a `NetworkManager` finalizes the run — legal only from
    `CALCULATED`, otherwise `ERR_INVALID_STATE`"

    Design: Corner/state_machines/settlement_finalize_twice_returns_invalid_state
    """
    run = create_settlement_run("2026-09-07")
    first = finalize_settlement(run["id"], 165)
    assert first["status"] == "FINALIZED"

    resp = api.finalize_settlement(
        run["id"], {"actual_commodity_base_cents_per_dozen": 170}, NM
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    reread = get_settlement_run(run["id"])
    assert reread["status"] == "FINALIZED"
    assert reread["final_total_cents"] == 0, (
        "the rejected re-finalize recomputes nothing on this empty run"
    )


def test_lots_list_pagination_and_status_filter(api):
    """PRD §2.3: "Paginated list responses carry the fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."
    PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, and any value below 1 or above 100 is rejected
    — 1 is the minimum and 100 is the maximum."

    Design: Corner/endpoints/lots_list_pagination_and_status_filter
    """
    farm = create_active_farm(name="Pagination Farm")["farm"]
    for day, laid_start, laid_end in (
        ("2026-09-08", "2026-09-06", "2026-09-07"),
        ("2026-09-09", "2026-09-07", "2026-09-08"),
        ("2026-09-10", "2026-09-08", "2026-09-09"),
    ):
        setup_collected_lot(
            farm["id"], route_date=day, collected_cases=1,
            collect_at=f"{day}T10:00:00Z", laid_start_date=laid_start,
            laid_end_date=laid_end, capacity_cases=4,
        )

    page1, meta1 = validate_paginated(
        api.list_lots(NM, params={"farm_id": farm["id"], "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_lots(NM, params={"farm_id": farm["id"], "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    filtered, meta3 = validate_paginated(
        api.list_lots(NM, params={"farm_id": farm["id"], "status": "RECEIVED"})
    )
    assert meta3["total_count"] == 3 and len(filtered) == 3
