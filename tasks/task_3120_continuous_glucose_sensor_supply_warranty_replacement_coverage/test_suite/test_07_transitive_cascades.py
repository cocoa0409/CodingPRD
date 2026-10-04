"""Difficulty queue A: transitive cascades — AER substantiation to lot HOLD,
and warranty approval to replacement shipment and unit compensation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_verification,
    create_order,
    create_payer,
    create_prescriber,
    create_prescription,
    file_and_close_aer,
    setup_claim_in_data_review,
    setup_lot_with_substantiated_complaints,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
FULFILL = TEST_USERS["fulfillment_agent_headers"]
WARRANTY = TEST_USERS["warranty_reviewer_headers"]


def _lot_hold_setup():
    """Lot at complaint_count == 6 (WATCH); a PENDING_PICK order on the lot;
    a 7th unit ready for the substantiated closure that crosses to HOLD."""
    ctx = setup_lot_with_substantiated_complaints(6)
    prescriber = create_prescriber()
    payer = create_payer()
    patient = ctx["patient"]
    rx = create_prescription(patient, prescriber, ctx["product"], quantity_per_fill=1)
    cv = create_approved_verification(rx, payer)
    order = create_order(patient, rx, cv, ctx["lot"])
    seventh_unit = ctx["units"][6]
    return ctx, order, seventh_unit


def test_aer_substantiated_close_pushes_lot_to_hold(api):
    """PRD §3.11: "A substantiated closure moves the report to
    `CLOSED_SUBSTANTIATED` and increments the parent lot's `complaint_count` by
    one, then recomputes the lot's `complaint_posture` per the threshold rule"
    PRD §3.2: "once the count reaches at least seven, the posture becomes
    `HOLD`"

    Design: Difficulty/transitive_cascade/aer_substantiated_cascades_to_lot_hold_blocks_pick
    """
    ctx, order, seventh_unit = _lot_hold_setup()
    file_and_close_aer(
        ctx["lot"], seventh_unit, ctx["patient"]["id"],
        outcome="SUBSTANTIATED", severity="CRITICAL", event_type="INACCURACY_HARM",
    )
    lot = validate_success(api.get_sensor_lot(ctx["lot"]["id"], ADMIN))
    assert lot["complaint_count"] == 7
    assert lot["complaint_posture"] == "HOLD"


def test_lot_on_hold_blocks_pending_pick_order(api):
    """PRD §3.2: "While a lot sits at `HOLD`, any order sitting in
    `PENDING_PICK` against that lot cannot be picked — the pick attempt is
    rejected with `ERR_LOT_ON_HOLD` — until a `QualityEngineer` remediates and
    steps the posture back down."

    Design: Difficulty/transitive_cascade/aer_substantiated_cascades_to_lot_hold_blocks_pick
    """
    ctx, order, seventh_unit = _lot_hold_setup()
    file_and_close_aer(
        ctx["lot"], seventh_unit, ctx["patient"]["id"],
        outcome="SUBSTANTIATED", severity="CRITICAL", event_type="INACCURACY_HARM",
    )
    resp = api.pick_sensor_order(order["id"], FULFILL)
    validate_error(resp, ApiErrorId.ERR_LOT_ON_HOLD, expected_status=409)
    order_after = validate_success(api.get_sensor_order(order["id"], ADMIN))
    assert order_after["fulfillment_status"] == "PENDING_PICK"


def _approve_claim(api, claim_id):
    return validate_success(
        api.decide_warranty_claim(
            claim_id,
            {"decision": "APPROVED", "review_notes": "approved; replacement cascades"},
            WARRANTY,
        )
    )


def test_warranty_approval_creates_replacement_shipment_and_allocates_unit(api):
    """PRD §3.8: "In the same operation, a `ReplacementShipment` is created in
    `PENDING_SHIP`, and a replacement unit is allocated from a lot of the
    **same product** whose `complaint_posture` is `NORMAL`, selected by
    earliest `manufacture_date` and then `serial_number` ascending. The
    replacement unit transitions `IN_STOCK → ALLOCATED` with `patient_id` set
    to the claim's patient, and the shipment's `replacement_sensor_unit_id` is
    stamped at this moment."

    Design: Difficulty/transitive_cascade/warranty_approval_cascades_to_replacement_shipment_and_old_unit
    """
    ctx = setup_claim_in_data_review(failure_day_index=3, num_units=2)
    claim = ctx["claim"]
    approved = _approve_claim(api, claim["id"])
    assert approved["status"] == "APPROVED"
    shipments, _meta = validate_paginated(api.list_claim_replacement_shipments(claim["id"], ADMIN))
    assert len(shipments) == 1
    shipment = shipments[0]
    assert shipment["status"] == "PENDING_SHIP"
    replacement_unit_id = shipment["replacement_sensor_unit_id"]
    assert replacement_unit_id != ctx["unit"]["id"]
    replacement_unit = validate_success(api.get_sensor_unit(replacement_unit_id, ADMIN))
    assert replacement_unit["status"] == "ALLOCATED"
    assert replacement_unit["patient_id"] == ctx["patient"]["id"]


def test_replacement_deliver_closes_compensation_loop_on_original_unit(api):
    """PRD §3.9: "Delivery moves the shipment to `DELIVERED`, transitions the
    replacement unit `SHIPPED → IN_HAND`, and — closing the compensation loop —
    transitions the original failed unit from `FAILED_EARLY` to `REPLACED`."

    Design: Difficulty/transitive_cascade/warranty_approval_cascades_to_replacement_shipment_and_old_unit
    """
    ctx = setup_claim_in_data_review(failure_day_index=3, num_units=2)
    claim = ctx["claim"]
    _approve_claim(api, claim["id"])
    shipments, _meta = validate_paginated(api.list_claim_replacement_shipments(claim["id"], ADMIN))
    shipment = shipments[0]
    replacement_unit_id = shipment["replacement_sensor_unit_id"]
    validate_success(api.ship_replacement_shipment(shipment["id"], FULFILL))
    delivered = validate_success(api.deliver_replacement_shipment(shipment["id"], FULFILL))
    assert delivered["status"] == "DELIVERED"
    replacement_unit = validate_success(api.get_sensor_unit(replacement_unit_id, ADMIN))
    assert replacement_unit["status"] == "IN_HAND"
    original_unit = validate_success(api.get_sensor_unit(ctx["unit"]["id"], ADMIN))
    assert original_unit["status"] == "REPLACED"
