"""Difficulty-design translations: dual volume doctrines and loss aggregation.

Every barrel carries two volume figures that answer different questions
(PRD §3.3), and bonded reports carry two loss figures computed by rival
doctrines over the same barrel set (PRD §3.7). Expected literals below were
computed by executing the PRD formulas with decimal arithmetic: the ledger
rounds half-up to two decimals after every event, the statutory projection
carries full precision through each 90-day block and rounds once at the end,
and report losses round per barrel before summing (PRD §2.6).
"""
from test_helpers import (
    assert_barrel,
    assert_bonded_period_report,
    create_commissioned_rickhouse,
    create_report,
    fill_barrels_on_slots,
    fill_placed_barrel,
    reconcile_report,
    record_evaporation_reading,
    record_quality_sample,
    set_clock,
    validate_success,
)


def test_barrel_ledger_and_statutory_volumes_diverge(api, warehouse_manager_headers):
    """PRD §3.3: "an `EVAPORATION_READING` assessment resets the running volume
    outright to its `measured_volume_liters` — an authoritative measurement of
    what is actually in the barrel, not a delta; a `QUALITY_SAMPLE` subtracts
    its `sample_draw_liters`".
    PRD §3.3: "On identical data the two diverge, deliberately."

    Design: Difficulty/dual_variant_calc/barrel_volume_ledger_vs_statutory_divergence
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-DV",
    )
    barrel = fill_placed_barrel(ctx["slots"][0]["id"])

    set_clock("2029-03-01T00:00:00Z")
    record_evaporation_reading(barrel["id"], 190.0)
    set_clock("2029-04-01T00:00:00Z")
    record_quality_sample(barrel["id"], sample_draw_liters=2.0, quality_score=88)
    set_clock("2029-09-01T00:00:00Z")

    data = validate_success(api.get_barrel(barrel["id"], warehouse_manager_headers))
    assert_barrel(data)
    # Ledger replay: 200.00 -> reading resets to 190.00 -> sample subtracts 2.00.
    assert data["current_volume_ledger_liters"] == 188.00
    # Statutory projection at 2029-09-01: four fully elapsed 90-day blocks at
    # rates 0.012, 0.012, 0.0084, 0.012 (base 0.01 x heat 1.00 x season x age
    # 1.2; seasoning 12 earns no discount) -> 200 x 0.988^3 x 0.9916 = 191.27.
    assert data["current_volume_statutory_liters"] == 191.27
    assert data["current_volume_ledger_liters"] != data["current_volume_statutory_liters"]


def test_report_loss_actual_vs_statutory_divergence(api):
    """PRD §3.7: "For `loss_actual_liters`, the ledger of §3.3 is replayed at
    both window boundaries using only events strictly before each, and the drop
    between the two replayed volumes is reduced by what was legitimately drawn
    inside the window".
    PRD §3.7: "`reported_loss_liters` — the loss reported to the tax authority —
    is pinned equal to `loss_actual_liters`; the statutory figure stands
    disclosed alongside for comparison only."
    PRD §3.7: "`closing_inventory_liters` is the opening inventory plus the
    period's fills, minus the period's withdrawals, minus the reported loss."

    Design: Difficulty/dual_variant_calc/report_loss_actual_vs_statutory_divergence
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=2, name="RH-RL",
    )
    barrel_a = fill_placed_barrel(ctx["slots"][0]["id"])
    barrel_b = fill_placed_barrel(ctx["slots"][1]["id"])

    set_clock("2029-06-01T00:00:00Z")
    record_evaporation_reading(barrel_a["id"], 198.995)
    record_evaporation_reading(barrel_b["id"], 197.995)

    report = create_report("2029-03-01T00:00:00Z", "2029-09-01T00:00:00Z")
    reconciled = reconcile_report(report["id"])  # clock -> period_end, then reconcile

    assert_bonded_period_report(reconciled)
    # Actual doctrine: the ledger rounds after every event (PRD §2.6), so the
    # readings land as 199.00 and 198.00; per-barrel losses 1.00 and 2.00 are
    # each rounded, then summed -> 3.00.
    assert reconciled["loss_actual_liters"] == 3.00
    # Statutory doctrine: per-barrel projection 195.23 at the window start and
    # 191.27 at the window end -> loss 3.96 per barrel, twice -> 7.92.
    assert reconciled["loss_statutory_liters"] == 7.92
    assert reconciled["loss_actual_liters"] != reconciled["loss_statutory_liters"]
    assert reconciled["reported_loss_liters"] == reconciled["loss_actual_liters"]
    assert reconciled["opening_inventory_liters"] == 400.00
    assert reconciled["closing_inventory_liters"] == 397.00


def test_statutory_evaporation_multi_factor_rate(api, warehouse_manager_headers):
    """PRD §3.3: "The season of the block's first day: December, January, or
    February is WINTER with a multiplier of 0.7; March, April, or May is SPRING
    at 1.0; June, July, or August is SUMMER at 1.5; September, October, or
    November is AUTUMN at 1.0."
    PRD §3.3: "The block's rate is the base rate multiplied by the heat factor,
    the season multiplier, and the age multiplier; when the barrel's
    `seasoning_months` is at least eighteen, the result is further multiplied
    by 0.95, the well-seasoned-wood discount; and the final rate is capped at
    0.05, so no block ever removes more than five percent of the running volume."
    PRD §3.1: "Each slot's `heat_factor` is one plus five one-hundredths for
    every floor above ground — one plus 0.05 multiplied by the slot's
    `floor_index` minus one — rounded to two decimal places: exactly 1.00 on
    the ground floor, 1.05 on the second floor, 1.10 on the third, and so on."

    Design: Difficulty/combinatorial_formula/statutory_evaporation_multi_factor_rate
    """
    ctx = create_commissioned_rickhouse(
        floors=2, rows_per_floor=1, positions_per_row=1,
        name="RH-MF", region_code="TN", planned_annual_distillation_liters=60000,
    )
    slot_floor2 = ctx["slots"][1]  # (floor, row, position) order: second entry is (2,1,1)
    barrel = fill_placed_barrel(
        slot_floor2["id"],
        wood_origin="FRENCH_OAK",
        seasoning_months=24,
        char_level=2,
        spirit_type="RYE",
        fill_proof=110.0,
    )

    set_clock("2030-09-01T00:00:00Z")
    data = validate_success(api.get_barrel(barrel["id"], warehouse_manager_headers))
    assert_barrel(data)
    # Eight fully elapsed blocks at rates 0.01197 x5, 0.008379 x2, 0.017955 x1
    # (base 0.01 x heat 1.05 x season multiplier x age multiplier 1.2, then the
    # x0.95 well-seasoned-wood discount for seasoning 24), full precision
    # through every block and rounded once at the end -> 181.85.
    assert data["current_volume_statutory_liters"] == 181.85
    # No assessments recorded: the ledger variant ignores the rate table.
    assert data["current_volume_ledger_liters"] == 200.00

    slot_data = validate_success(api.get_warehouse_slot(slot_floor2["id"], warehouse_manager_headers))
    assert slot_data["floor_index"] == 2
    assert slot_data["heat_factor"] == 1.05


def test_report_loss_round_per_barrel_then_sum(api):
    """PRD §2.6: "Bonded reports round per barrel, then sum."
    PRD §3.7: "Both doctrines pin the same rounding order: each barrel's loss
    is rounded to two decimal places, round half up, individually, and only
    then summed — round per barrel, then sum; summing first and rounding once
    is a rejected alternative that yields different cents."

    Design: Difficulty/combinatorial_formula/report_loss_round_per_barrel_then_sum
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=3, name="RH-RO",
    )
    barrels = fill_barrels_on_slots([s["id"] for s in ctx["slots"]])

    set_clock("2029-06-01T00:00:00Z")
    record_evaporation_reading(barrels[0]["id"], 198.995)
    record_evaporation_reading(barrels[1]["id"], 197.995)
    record_evaporation_reading(barrels[2]["id"], 199.985)

    report = create_report("2029-03-01T00:00:00Z", "2029-09-01T00:00:00Z")
    reconciled = reconcile_report(report["id"])

    assert_bonded_period_report(reconciled)
    # The ledger rounds every event to two decimals half-up (PRD §2.6), so the
    # readings become 199.00, 198.00 and 199.99; the per-barrel losses 1.00,
    # 2.00 and 0.01 are each rounded first and only then summed -> 3.01.
    assert reconciled["loss_actual_liters"] == 3.01
    assert reconciled["opening_inventory_liters"] == 600.00
    assert reconciled["closing_inventory_liters"] == 596.99
