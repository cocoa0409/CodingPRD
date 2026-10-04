"""Charge-apply referential guards: lot depletion and contract-open (PRD §3.4)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    make_mill, make_grade, make_heat, apply_charge, setup_supply_pool, get_lot,
)

PO = TEST_USERS["procurement_officer_headers"]
MO = TEST_USERS["mill_operator_headers"]


def test_lot_depleted_and_contract_not_open_referential_checks():
    """PRD §3.4: "The lot must be in `RECEIVED` or `PARTIALLY_CONSUMED` with enough
    remaining tonnage, and its contract must be `OPEN`: a draw against a closed or
    defaulted contract fails with `ERR_CONTRACT_NOT_OPEN` (HTTP 409), and a draw
    exceeding the lot's remaining tonnage fails with `ERR_LOT_DEPLETED` (HTTP 409)."

    Design: Corner/validations/lot_depleted_and_contract_not_open_referential_checks
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    c1, lots1 = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": 10, "moisture_pct": 0.0}],
    )
    c2, lots2 = setup_supply_pool(
        mill["id"], price=38000, committed=10, supplier_name="Closeout Scrap",
        lots=[{"received_on": "2026-09-03", "tons_received": 10, "moisture_pct": 0.0}],
    )
    validate_success(api_client.close_contract(mill["id"], c2["id"], PO), 200)

    grade = make_grade(mill["id"], grade_code="GR40")
    heat = make_heat(mill["id"], grade["id"], target_tap_weight_tons=8,
                     planned_tap_at="2026-09-15T12:00:00Z")
    apply_charge(mill["id"], heat["id"], lots1[0]["id"], 2)

    depleted = api_client.apply_charge(
        mill["id"], heat["id"], {"scrap_lot_id": lots1[0]["id"], "tons": 9}, MO)
    validate_error(depleted, ApiErrorId.ERR_LOT_DEPLETED, 409)

    closed_contract = api_client.apply_charge(
        mill["id"], heat["id"], {"scrap_lot_id": lots2[0]["id"], "tons": 1}, MO)
    validate_error(closed_contract, ApiErrorId.ERR_CONTRACT_NOT_OPEN, 409)

    assert get_lot(mill["id"], lots1[0]["id"])["remaining_tons"] == 8
