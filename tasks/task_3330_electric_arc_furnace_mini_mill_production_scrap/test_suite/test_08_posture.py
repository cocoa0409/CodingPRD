"""Mill posture gate and the interruption cascade (PRD §2.9, §3.10)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    validate_paginated, set_clock, make_mill, make_grade, make_heat, apply_charge,
    setup_supply_pool, setup_charged_heat, make_sheet, confirm_sheet,
    make_event, activate_event, release_event, grant_waiver,
    get_heat, get_lot, get_mill, get_event,
)

PM = TEST_USERS["plant_manager_headers"]
MO = TEST_USERS["mill_operator_headers"]
MET = TEST_USERS["metallurgist_headers"]


def _setup_two_heats_one_waivered():
    """Mill + contract/lot + grade; H-NO-WAIVER and H-WAIVERED PLANNED; event ACTIVE."""
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": 50, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GR40")
    heat_nw = make_heat(mill["id"], grade["id"], target_tap_weight_tons=8,
                        planned_tap_at="2026-09-15T12:00:00Z")
    heat_w = make_heat(mill["id"], grade["id"], target_tap_weight_tons=8,
                       planned_tap_at="2026-09-15T14:00:00Z")
    event = make_event(mill["id"], called_at="2026-09-10T12:00:00Z",
                       released_at="2026-09-10T14:00:00Z")
    activate_event(mill["id"], event["id"])
    grant_waiver(mill["id"], scope="HEAT", scope_id=heat_w["id"],
                 reason="grid-critical automotive order")
    return mill, lots[0], heat_nw, heat_w, event


def test_charge_apply_unwaivered_heat_rejected_when_interrupted():
    """PRD §2.9: "Three operations are posture-gated and refuse to run while the mill
    is `INTERRUPTED` unless a covering waiver applies: applying a charge line to a
    heat, tapping a heat, and confirming an order."
    PRD §2.9: "A gated operation refused by posture fails with `ERR_MILL_INTERRUPTED`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/charge_apply_gated_by_mill_posture
    """
    mill, lot, heat_nw, heat_w, event = _setup_two_heats_one_waivered()

    resp = api_client.apply_charge(mill["id"], heat_nw["id"],
                                   {"scrap_lot_id": lot["id"], "tons": 8}, MO)
    validate_error(resp, ApiErrorId.ERR_MILL_INTERRUPTED, 409)
    assert get_heat(mill["id"], heat_nw["id"])["status"] == "PLANNED"


def test_charge_apply_waivered_heat_escapes_posture_gate():
    """PRD §2.9: "For charge lines and taps, the gate is lifted when the heat is
    covered by a waiver with `scope` HEAT targeting that heat, or by a waiver with
    `scope` EVENT targeting the mill's `ACTIVE` event."

    Design: Difficulty/cross_entity_state_dependency/charge_apply_gated_by_mill_posture
    """
    mill, lot, heat_nw, heat_w, event = _setup_two_heats_one_waivered()

    line = validate_success(
        api_client.apply_charge(mill["id"], heat_w["id"],
                                {"scrap_lot_id": lot["id"], "tons": 8}, MO), 201)
    assert line["id"]
    assert get_heat(mill["id"], heat_w["id"])["status"] == "CHARGED"
    # The waiver exempts one heat; it does not change the mill's derived posture.
    assert get_mill(mill["id"])["posture"] == "INTERRUPTED"


def _setup_posture_and_infeasible_candidate():
    """Heat CHARGED with a clean 3t line; a high-Cu candidate that would breach the
    blend ceiling; event ACTIVE so the mill is INTERRUPTED with no waiver."""
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[
            {"received_on": "2026-09-03", "tons_received": 5, "moisture_pct": 0.0,
             "cu_pct": 0.002, "mn_pct": 0.004},
            {"received_on": "2026-09-04", "tons_received": 5, "moisture_pct": 0.0,
             "cu_pct": 0.0045, "mn_pct": 0.004},
        ],
    )
    grade = make_grade(mill["id"], grade_code="GR60-TIGHT", cu_max_pct=0.0028,
                       mn_min_pct=0.002, mn_max_pct=0.012)
    heat = make_heat(mill["id"], grade["id"], target_tap_weight_tons=5,
                     planned_tap_at="2026-09-15T12:00:00Z")
    apply_charge(mill["id"], heat["id"], lots[0]["id"], 3)
    event = make_event(mill["id"], called_at="2026-09-10T12:00:00Z",
                       released_at="2026-09-10T14:00:00Z")
    activate_event(mill["id"], event["id"])
    return mill, lots, heat, event


def test_posture_gate_beats_blend_ceiling_on_charge_apply():
    """PRD §2.7: "(7) the mill-interruption gate yields `ERR_MILL_INTERRUPTED`"
    PRD §2.7: "(8) blend feasibility yields `ERR_BLEND_INFEASIBLE`"
    PRD §2.7: "A request failing two checks at different priorities surfaces the
    earlier one."

    Design: Difficulty/priority_pair_validation_conflict/posture_state_beats_blend_safety_on_charge_apply
    """
    mill, lots, heat, event = _setup_posture_and_infeasible_candidate()

    # The candidate would fail both gates: posture INTERRUPTED (priority 7) and
    # blend (3*0.002 + 2*0.0045)/5 = 0.003 > cu_max 0.0028 (priority 8).
    resp = api_client.apply_charge(mill["id"], heat["id"],
                                   {"scrap_lot_id": lots[1]["id"], "tons": 2}, MO)
    validate_error(resp, ApiErrorId.ERR_MILL_INTERRUPTED, 409)


def test_posture_rejection_leaves_charge_mix_and_lot_untouched():
    """PRD §2.9: "A gated operation refused by posture fails with
    `ERR_MILL_INTERRUPTED` (HTTP 409)."
    PRD §2.10: "Every mutation, including every cascade it triggers, commits
    atomically within the request."

    Design: Difficulty/priority_pair_validation_conflict/posture_state_beats_blend_safety_on_charge_apply
    """
    mill, lots, heat, event = _setup_posture_and_infeasible_candidate()

    resp = api_client.apply_charge(mill["id"], heat["id"],
                                   {"scrap_lot_id": lots[1]["id"], "tons": 2}, MO)
    validate_error(resp, ApiErrorId.ERR_MILL_INTERRUPTED, 409)

    rows, meta = validate_paginated(api_client.list_charges(mill["id"], heat["id"], MO))
    assert meta["total_count"] == 1, "the refused candidate must not append a line"
    assert get_heat(mill["id"], heat["id"])["status"] == "CHARGED"
    assert get_lot(mill["id"], lots[1]["id"])["remaining_tons"] == 5


def test_event_release_aborts_heat_and_restores_lot():
    """PRD §3.10: "Releasing an `ACTIVE` event recomputes the mill's posture — back
    to `NORMAL` unless another active event or containing window keeps it interrupted
    — and triggers the interruption cascade at depth three: every heat of the mill
    sitting in `CHARGED` or `MELTDOWN_LOCKED` that is not waiver-covered aborts, and
    each abort runs the compensating release that returns charged tonnage to its
    scrap lots with lot statuses recomputed."

    Design: Difficulty/transitive_cascade/event_release_aborts_heat_restores_lot
    """
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": 10, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GR40")
    heat = make_heat(mill["id"], grade["id"], target_tap_weight_tons=8,
                     planned_tap_at="2026-09-15T12:00:00Z")
    apply_charge(mill["id"], heat["id"], lots[0]["id"], 8)
    sheet = make_sheet(mill["id"], heat["id"], cu_pct=0.002, mn_pct=0.006)
    confirm_sheet(mill["id"], heat["id"], sheet["id"])
    event = make_event(mill["id"], called_at="2026-09-10T12:00:00Z",
                       released_at="2026-09-10T14:00:00Z")
    activate_event(mill["id"], event["id"])
    assert get_heat(mill["id"], heat["id"])["status"] == "MELTDOWN_LOCKED"

    released = validate_success(
        api_client.release_event(mill["id"], event["id"],
                                 TEST_USERS["energy_dispatcher_headers"]), 200)
    assert released["status"] == "RELEASED"
    assert get_heat(mill["id"], heat["id"])["status"] == "ABORTED"
    lot = get_lot(mill["id"], lots[0]["id"])
    assert lot["remaining_tons"] == 10
    assert lot["status"] == "RECEIVED"
    assert get_mill(mill["id"])["posture"] == "NORMAL"


def test_event_release_skips_waivered_heat():
    """PRD §3.10: "A heat is waiver-covered when it has its own `HEAT` waiver or when
    the mill's `ACTIVE` event has an `EVENT` waiver; covered heats escape both the
    posture gate and the release cascade."

    Design: Difficulty/transitive_cascade/event_release_aborts_heat_restores_lot
    """
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": 20, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GR40")
    heat = make_heat(mill["id"], grade["id"], target_tap_weight_tons=8,
                     planned_tap_at="2026-09-15T12:00:00Z")
    apply_charge(mill["id"], heat["id"], lots[0]["id"], 8)
    event = make_event(mill["id"], called_at="2026-09-10T12:00:00Z",
                       released_at="2026-09-10T14:00:00Z")
    activate_event(mill["id"], event["id"])
    grant_waiver(mill["id"], scope="HEAT", scope_id=heat["id"],
                 reason="grid-critical automotive order")

    released = validate_success(
        api_client.release_event(mill["id"], event["id"],
                                 TEST_USERS["energy_dispatcher_headers"]), 200)
    assert released["status"] == "RELEASED"
    # The covered heat escapes the release cascade: still CHARGED, lot untouched.
    assert get_heat(mill["id"], heat["id"])["status"] == "CHARGED"
    assert get_lot(mill["id"], lots[0]["id"])["remaining_tons"] == 12
