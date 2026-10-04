"""Heat tap/cast/abort lifecycle corners (PRD §3.6, §2.10)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    make_mill, make_grade, setup_supply_pool, setup_charged_heat, make_sheet,
    confirm_sheet, get_heat, get_lot,
)

MO = TEST_USERS["mill_operator_headers"]
MET = TEST_USERS["metallurgist_headers"]
PO = TEST_USERS["procurement_officer_headers"]


def _setup_charged(lot_tons=20, charge_tons=8):
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": lot_tons, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GR40")
    heat, _line = setup_charged_heat(mill["id"], grade["id"], lots[0]["id"], charge_tons)
    return mill, lots[0], grade, heat


def test_cast_from_charged_returns_invalid_state():
    """PRD §3.6: "Casting moves a `TAPPED` heat to `CAST` — the terminal success
    state"
    PRD §2.7: "(5) source-state validity yields `ERR_INVALID_STATE`"

    Design: Corner/state_machines/heat_invalid_transition_cast_from_charged_returns_invalid_state
    """
    mill, lot, grade, heat = _setup_charged()
    resp = api_client.cast_heat(mill["id"], heat["id"], MO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_heat(mill["id"], heat["id"])["status"] == "CHARGED"
    # No compensating release on a rejected cast: the 8t draw stays drawn.
    assert get_lot(mill["id"], lot["id"])["remaining_tons"] == 12


def test_heat_abort_restores_lot_tonnage_and_status():
    """PRD §3.6: "The abort performs a compensating release: every charge line's
    tons are credited back to their source lots' `remaining_tons`, and each lot's
    status is recomputed from the restored remainder — a `CONSUMED` lot returns to
    `PARTIALLY_CONSUMED` or, when fully restored, to `RECEIVED`, and a
    `PARTIALLY_CONSUMED` lot fully restored returns to `RECEIVED`."

    Design: Difficulty/compensating_invariant/heat_abort_restores_lot_tonnage
    """
    mill, lot, grade, heat = _setup_charged()
    assert get_lot(mill["id"], lot["id"])["remaining_tons"] == 12

    aborted = validate_success(api_client.abort_heat(mill["id"], heat["id"], MO), 200)
    assert aborted["status"] == "ABORTED"
    lot_after = get_lot(mill["id"], lot["id"])
    assert lot_after["remaining_tons"] == 20
    assert lot_after["status"] == "RECEIVED"


def test_abort_compensation_leaves_inventory_as_if_charge_never_happened():
    """PRD §3.6: "The abort performs a compensating release: every charge line's
    tons are credited back to their source lots' `remaining_tons`, and each lot's
    status is recomputed from the restored remainder"
    PRD §2.10: "Every mutation, including every cascade it triggers, commits
    atomically within the request."

    Design: Difficulty/compensating_invariant/heat_abort_restores_lot_tonnage
    """
    mill, lot, grade, heat = _setup_charged()
    # Available inventory before the charge equals available inventory after the
    # abort: the 8t draw is compensated exactly, status and counter both restored.
    drawn = get_lot(mill["id"], lot["id"])
    assert drawn["remaining_tons"] == 12
    assert drawn["status"] == "PARTIALLY_CONSUMED"

    validate_success(api_client.abort_heat(mill["id"], heat["id"], MO), 200)
    restored = get_lot(mill["id"], lot["id"])
    assert restored["remaining_tons"] == 20
    assert restored["status"] == "RECEIVED"
    assert get_heat(mill["id"], heat["id"])["status"] == "ABORTED"


def test_heat_abort_immediate_visibility_across_entities():
    """PRD §2.10: "Every mutation, including every cascade it triggers, commits
    atomically within the request."
    PRD §3.6: "The heat lands in `ABORTED`, its other terminal state, with `version`
    incremented."

    Design: Corner/complexity_layers/charge_tap_abort_immediate_visibility
    """
    mill, lot, grade, heat = _setup_charged()
    aborted = validate_success(api_client.abort_heat(mill["id"], heat["id"], MO), 200)
    assert aborted["status"] == "ABORTED"

    # The follow-up read agrees in the same request cycle — no lag.
    lot_after = validate_success(api_client.flat_get_lot(lot["id"], PO), 200)
    assert lot_after["remaining_tons"] == 20
    assert lot_after["status"] == "RECEIVED"
    assert get_heat(mill["id"], heat["id"])["status"] == "ABORTED"
