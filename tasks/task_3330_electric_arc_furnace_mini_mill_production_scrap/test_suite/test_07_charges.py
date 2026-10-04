"""Charge-line costing and blend feasibility (PRD §3.4, §2.6, §2.7)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    validate_paginated, set_clock, make_mill, make_grade, make_heat,
    setup_supply_pool, get_heat, get_lot,
)

MO = TEST_USERS["mill_operator_headers"]


def test_charge_line_cost_rounds_half_up_per_line():
    """PRD §3.4: "The line's `line_cost_cents` is the unit price times the line's tons,
    rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/charge_cost_round_per_line_then_sum
    """
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Hertford Bar Mill", division="CONSTRUCTION")
    contract, lots = setup_supply_pool(
        mill["id"], price=39001, committed=50,
        lots=[{"received_on": "2026-09-03", "tons_received": 10, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GR40")
    heat = make_heat(mill["id"], grade["id"], target_tap_weight_tons=2,
                     planned_tap_at="2026-09-15T12:00:00Z")

    line1 = validate_success(
        api_client.apply_charge(mill["id"], heat["id"],
                                {"scrap_lot_id": lots[0]["id"], "tons": 0.667}, MO), 201)
    line2 = validate_success(
        api_client.apply_charge(mill["id"], heat["id"],
                                {"scrap_lot_id": lots[0]["id"], "tons": 0.667}, MO), 201)
    # round_half_up(39001 * 0.667) = round_half_up(26013.667) = 26014
    assert line1["line_cost_cents"] == 26014
    assert line2["line_cost_cents"] == 26014


def test_heat_charge_cost_freeze_sums_rounded_lines_at_tap():
    """PRD §3.6: "At tap, the heat's `charge_cost_cents` is frozen as the sum of its
    charge lines' `line_cost_cents` — each line already rounded half-up to whole cents
    at apply time, summed as integers; summing exact values and rounding once would be
    the wrong variant."
    PRD §3.5: "Confirming the sheet — from either `RECORDED` or `REVISED`, with the
    heat still `CHARGED` — requires `chem_ok` true"

    Design: Difficulty/combinatorial_formula/charge_cost_round_per_line_then_sum
    """
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Hertford Bar Mill", division="CONSTRUCTION")
    contract, lots = setup_supply_pool(
        mill["id"], price=39001, committed=50,
        lots=[{"received_on": "2026-09-03", "tons_received": 10, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GR40")
    heat = make_heat(mill["id"], grade["id"], target_tap_weight_tons=2,
                     planned_tap_at="2026-09-15T12:00:00Z")
    validate_success(api_client.apply_charge(
        mill["id"], heat["id"], {"scrap_lot_id": lots[0]["id"], "tons": 0.667}, MO), 201)
    validate_success(api_client.apply_charge(
        mill["id"], heat["id"], {"scrap_lot_id": lots[0]["id"], "tons": 0.667}, MO), 201)

    sheet = validate_success(api_client.create_sheet(
        mill["id"], heat["id"], {"cu_pct": 0.002, "mn_pct": 0.006},
        TEST_USERS["metallurgist_headers"]), 201)
    validate_success(api_client.confirm_sheet(
        mill["id"], heat["id"], sheet["id"], TEST_USERS["metallurgist_headers"]), 200)
    validate_success(api_client.tap_heat(mill["id"], heat["id"], MO), 200)

    tapped = get_heat(mill["id"], heat["id"])
    # round-then-sum pinned order: 26014 + 26014 = 52028; the forbidden
    # sum-then-round variant would give round_half_up(52027.334) = 52027.
    assert tapped["charge_cost_cents"] == 52028


def test_blend_feasibility_mn_floor_violation():
    """PRD §3.4: "The blend is feasible when the blended copper is at most the grade's
    `cu_max_pct` and the blended manganese is at least the grade's `mn_min_pct`;
    otherwise the candidate line is rejected with `ERR_BLEND_INFEASIBLE` (HTTP 422)."

    Design: Corner/calculations/blend_feasibility_mn_floor_violation
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[
            {"received_on": "2026-09-03", "tons_received": 10, "moisture_pct": 0.0,
             "cu_pct": 0.001, "mn_pct": 0.0021},
            {"received_on": "2026-09-04", "tons_received": 10, "moisture_pct": 0.0,
             "cu_pct": 0.001, "mn_pct": 0.0005},
        ],
    )
    grade = make_grade(mill["id"], grade_code="GR-MN", mn_min_pct=0.002)
    heat = make_heat(mill["id"], grade["id"], target_tap_weight_tons=10,
                     planned_tap_at="2026-09-15T12:00:00Z")
    validate_success(api_client.apply_charge(
        mill["id"], heat["id"], {"scrap_lot_id": lots[0]["id"], "tons": 2}, MO), 201)

    # Candidate 8t from the low-Mn lot: mn_blend = (2*0.0021 + 8*0.0005)/10 = 0.00082
    # — strictly below the 0.002 floor while Cu (0.001) stays inside the ceiling.
    resp = api_client.apply_charge(
        mill["id"], heat["id"], {"scrap_lot_id": lots[1]["id"], "tons": 8}, MO)
    validate_error(resp, ApiErrorId.ERR_BLEND_INFEASIBLE, 422)

    rows, meta = validate_paginated(api_client.list_charges(
        mill["id"], heat["id"], TEST_USERS["mill_operator_headers"]))
    assert meta["total_count"] == 1
    assert get_lot(mill["id"], lots[1]["id"])["remaining_tons"] == 10
