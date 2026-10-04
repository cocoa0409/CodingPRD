"""Difficulty queue: dual-variant calculations — melt charge cost (planned vs
actual rounding) and production-order unit cost (provisional vs final)."""
from test_helpers import (
    charge_melt,
    complete_order,
    expected_planned_charge_cost_cents,
    get_melt,
    get_order,
    setup_charging_melt,
    setup_seasoned_units,
)


def test_planned_charge_cost_single_rounding_at_creation(api):
    """PRD §3.3: "At creation the system computes `planned_charge_cost_cents` with
    a single rounding over the whole planned mix: multiply `planned_iron_lbs` by the
    weighted percentage-price sum — `planned_pig_iron_pct` times 38 cents per pound,
    `planned_scrap_steel_pct` times 12, `planned_returns_pct` times 6, and
    `planned_alloy_pct` times 145 — divide by 100, and round half-up once to integer
    cents."
    2000 lbs at 40/40/15/5 -> round_half_up(2000 * 2815 / 100) == 56300.

    Design: Difficulty/dual_variant_calc/melt_charge_cost_planned_vs_actual_rounding
    """
    ctx = setup_charging_melt()
    melt = ctx["melt"]
    assert melt["planned_charge_cost_cents"] == 56300, (
        f"planned cost at creation: {melt['planned_charge_cost_cents']} != 56300")
    assert melt["planned_charge_cost_cents"] == expected_planned_charge_cost_cents(
        2000, 40, 40, 15, 5)
    # A fresh read returns the same stored creation-time value.
    reread = get_melt(melt["id"])
    assert reread["planned_charge_cost_cents"] == 56300


def test_actual_charge_cost_per_line_rounding_diverges(api):
    """PRD §3.3: "The charge cost is accumulated into `actual_charge_cost_cents` with
    a pinned rounding order: for the single call, each component line is first
    rounded half-up to integer cents — the pig-iron pounds times 38, the scrap-steel
    pounds times 12, the returns pounds times 6, and the alloy pounds times 145 —
    and only then are the four integer lines summed and added to the accumulator."
    810/790/320/90 lbs -> 30780 + 9480 + 1920 + 13050 == 55230, which differs from
    the planned variant's 56300 on the same batch.

    Design: Difficulty/dual_variant_calc/melt_charge_cost_planned_vs_actual_rounding
    """
    ctx = setup_charging_melt()
    charged = charge_melt(ctx["melt"]["id"])
    assert charged["state"] == "MELTING"
    assert charged["actual_charge_cost_cents"] == 55230, (
        f"actual charge cost: {charged['actual_charge_cost_cents']} != 55230")
    assert charged["planned_charge_cost_cents"] == 56300
    assert charged["actual_charge_cost_cents"] != charged["planned_charge_cost_cents"]


def test_provisional_unit_cost_during_production(api):
    """PRD §3.2: "The `unit_cost_provisional_cents` is the sum of
    `actual_charge_cost_cents` over all of the order's melt batches whose state is
    not `CANCELLED`, divided by `planned_quantity`, rounded half-up to integer cents,
    plus a flat standard conversion allowance of 1450 cents per unit."
    PRD §3.2: "and `labor_hours_actual`, `energy_kwh_actual`, and
    `unit_cost_final_cents` remain null until completion, while `margin_flag` reads
    false until it is computed at completion."
    Material 55230 over planned 10 -> 5523 + 1450 == 6973.

    Design: Difficulty/dual_variant_calc/unit_cost_provisional_vs_final_at_completion
    """
    ctx = setup_charging_melt(order_overrides={"planned_quantity": 10})
    charge_melt(ctx["melt"]["id"])  # 55230 cents of actual material
    order = get_order(ctx["order"]["id"])
    assert order["unit_cost_provisional_cents"] == 6973, (
        f"provisional: {order['unit_cost_provisional_cents']} != 6973")
    assert order["unit_cost_final_cents"] is None
    assert order["margin_flag"] is False


def test_final_unit_cost_and_margin_flag_at_completion(api):
    """PRD §3.2: "completion computes `unit_cost_final_cents` as follows: take the
    same non-`CANCELLED` material sum used by the provisional figure, add labor
    computed as `labor_hours_actual` multiplied by 3200 cents per hour rounded
    half-up, add energy computed as `energy_kwh_actual` multiplied by 14 cents per
    kilowatt-hour rounded half-up, add overhead computed as 185 cents multiplied by
    `poured_units`, divide the total by `good_units`, and round half-up to integer
    cents."
    PRD §3.2: "the order's `margin_flag` is set to true when the wholesale margin —
    the difference between the product's `wholesale_price_cents` and
    `unit_cost_final_cents`, divided by `wholesale_price_cents` — falls below 0.30,
    and false otherwise."

    Re-derivation note: the design YAML literal 19678 is a transposition error;
    PRD §3.2's formula on this instance's own inputs uniquely derives
    (55230 + 128000 + 12600 + 1850) / 10 = 19768, which is asserted here.

    Design: Difficulty/dual_variant_calc/unit_cost_provisional_vs_final_at_completion
    """
    ctx = setup_seasoned_units(num_units=10)
    order = complete_order(ctx["order"]["id"],
                           labor_hours_actual=40, energy_kwh_actual=900)
    assert order["state"] == "COMPLETE"
    assert order["good_units"] == 10
    assert order["unit_cost_final_cents"] == 19768, (
        f"final cost: {order['unit_cost_final_cents']} != 19768 "
        "(PRD-derived (55230+128000+12600+1850)/10)")
    assert order["unit_cost_provisional_cents"] == 6973
    assert order["unit_cost_provisional_cents"] != order["unit_cost_final_cents"]
    # (2400 - 19768) / 2400 < 0.30 -> margin flag set.
    assert order["margin_flag"] is True
