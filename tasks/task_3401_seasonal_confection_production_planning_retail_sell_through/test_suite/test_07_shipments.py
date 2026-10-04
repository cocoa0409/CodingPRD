"""Shipments: entity-specific 404, terminal DELIVERED, the dual ship-window
gate, and the cumulative allocation cap.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_BASELINE,
    CLOCK_DELIVER_TIME,
    ShipmentStatus,
    TEST_USERS,
    api_client,
    assert_shipment,
    create_planned_shipment,
    create_shipment_payload,
    get_lot_for_run,
    get_shipment,
    set_clock,
    setup_allocated_program,
    setup_delivered_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]


def test_shipment_get_with_unknown_id_returns_shipment_not_found(api):
    """PRD §2.8 priority 3: "identifiers in the URL path resolve to existing
    resources, validated left to right ... The first miss produces that
    entity's not-found error, one of `ERR_PROGRAM_NOT_FOUND`, ...,
    `ERR_SHIPMENT_NOT_FOUND`, ..., each at HTTP 404."

    Design: Corner/entities/shipment_get_with_unknown_id_returns_shipment_not_found
    """
    set_clock(CLOCK_BASELINE)
    resp = api_client.get_shipment(
        "00000000-0000-4000-8000-000000000000", LOGISTICS,
    )
    error = validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_FOUND)
    assert error["message"], "error data must carry a human-readable message"


def test_shipment_deliver_twice_returns_invalid_state(api):
    """PRD §3.6: "Delivery is a single act by a `LogisticsCoordinator`: a
    `PLANNED` shipment becomes `DELIVERED`, `delivered_on` is set from the
    logical clock, and the shipment's `version` increments." PRD §2.8 priority
    7 rejects transitions from a state where they are not defined with
    `ERR_INVALID_STATE` (HTTP 409).

    Design: Corner/state_machines/shipment_deliver_twice_returns_invalid_state
    """
    world = setup_delivered_shipment(
        commitment_units=10, ship_units=5, temp_controlled=True,
    )
    shipment = world["shipment"]
    assert shipment["status"] == ShipmentStatus.DELIVERED.value
    assert shipment["delivered_on"] == CLOCK_DELIVER_TIME

    resp = api_client.deliver_shipment(shipment["id"], LOGISTICS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_shipment(shipment["id"])
    assert after["status"] == ShipmentStatus.DELIVERED.value
    assert after["delivered_on"] == CLOCK_DELIVER_TIME, "delivered_on must not move"


def test_shipment_outside_commitment_window_rejected_inside_accepted(api):
    """PRD §3.6: "The `ship_on` must lie inside **both** the commitment's own
    ship window and the program's ship window — no earlier than either open
    date and no later than either close date, with close dates inclusive — or
    the create is rejected with `ERR_SHIP_WINDOW_VIOLATION` (HTTP 422)."

    Design: Corner/validations/shipment_outside_commitment_window_rejected_inside_accepted
    """
    world = setup_allocated_program()  # commitment 10 ALLOCATED, window [08-01, 09-10]
    commitment = world["commitment"]
    warehouse = world["warehouse"]

    # 2027-07-20 is inside the program ship window [07-15, 09-15] but before
    # the commitment window open 08-01.
    early = api_client.create_shipment(
        create_shipment_payload(
            commitment_id=commitment["id"], warehouse_id=warehouse["id"],
            units=2, ship_on="2027-07-20T00:00:00Z",
        ),
        LOGISTICS,
    )
    validate_error(early, ApiErrorId.ERR_SHIP_WINDOW_VIOLATION)

    # Exactly at the commitment window open: the lower bound is inclusive.
    ok = api_client.create_shipment(
        create_shipment_payload(
            commitment_id=commitment["id"], warehouse_id=warehouse["id"],
            units=2, ship_on="2027-08-01T00:00:00Z",
        ),
        LOGISTICS,
    )
    data = validate_success(ok, 201)
    assert_shipment(data)
    assert data["status"] == ShipmentStatus.PLANNED.value

    rows, _meta = validate_paginated(api_client.list_shipments(
        ADMIN, params={"commitment_id": commitment["id"]},
    ))
    assert len(rows) == 1


def test_shipment_past_allocated_units_returns_shipment_exceeds_allocation(api):
    """PRD §3.6: "The cumulative `units` over the commitment's shipments in
    `PLANNED` or `DELIVERED` status, plus the new shipment's `units`, must not
    exceed the commitment's `allocated_units`, or the create is rejected with
    `ERR_SHIPMENT_EXCEEDS_ALLOCATION` (HTTP 422)"."

    Design: Corner/errors/shipment_past_allocated_units_returns_shipment_exceeds_allocation
    """
    world = setup_allocated_program(
        commitment_specs=[{"tier": "GOLD", "units": 10, "use_default_retailer": True}],
        produced_units=20,
    )
    commitment = world["commitment"]
    warehouse = world["warehouse"]

    full = create_planned_shipment(commitment, warehouse, units=10)
    assert full["status"] == ShipmentStatus.PLANNED.value  # cumulative 10 == 10

    over = api_client.create_shipment(
        create_shipment_payload(
            commitment_id=commitment["id"], warehouse_id=warehouse["id"],
            units=1, ship_on="2027-08-02T00:00:00Z",
        ),
        LOGISTICS,
    )
    validate_error(over, ApiErrorId.ERR_SHIPMENT_EXCEEDS_ALLOCATION)

    # The warehouse still holds stock; only the allocation cap fired.
    lot = get_lot_for_run(world["run"]["id"])
    assert lot["units_on_hand"] == 10
