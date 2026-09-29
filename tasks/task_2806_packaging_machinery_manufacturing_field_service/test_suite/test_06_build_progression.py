"""Committing the factory: confirming a slot, cutting metal and releasing.

Confirmation is where the money track gates the build track and where the order
first reaches SLOTTED. Starting the build additionally demands that every
long-lead part is physically in the building.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN,
    PLANNER,
    ApiErrorId,
    api_client,
    read_line,
    read_order,
    read_slot,
    reserve_slot,
    seed_component,
    setup_engineered_order,
    setup_order_in_build,
    setup_order_with_reserved_slot,
    setup_reference_data,
)


def test_confirming_the_slot_is_what_bubbles_the_order_to_slotted():
    """An order never reaches SLOTTED on its own; the confirmation cascades onto the
    parent order in the same request while the money track stays put.

    PRD: "Confirmation cascades: the order's `fulfillment_status` bubbles up from
    `ENGINEERED` to `SLOTTED` and the order's `version` increments by 1."

    Design: Corner/state_machines/slot_confirm_bubbles_order_fulfillment_to_slotted
    """
    env = setup_order_with_reserved_slot(setup_reference_data(line={}))

    data = validate_success(api_client.confirm_build_slot(env["slot"]["id"], PLANNER))

    assert data["status"] == "CONFIRMED"
    assert data["end_date"] == "2026-08-26"
    order = read_order(env["order"]["id"])
    assert order["fulfillment_status"] == "SLOTTED"
    assert order["commercial_status"] == "PO_RECEIVED"
    assert read_line(env["line"]["id"])["committed_slot_days"] == 20


def test_a_slot_cannot_be_confirmed_while_the_money_track_is_still_quoted():
    """Nothing about the slot itself explains the refusal: the parallel commercial
    dimension of the order is what blocks the factory commitment.

    PRD: "The order must still be `ENGINEERED`, the line must still be `OPEN`, and —
    this is the point where the parallel commercial dimension gates the build — the
    order's `commercial_status` must already be one of `PO_RECEIVED`, `INVOICED` or
    `PAID`; a confirmation attempted while the money track is still `QUOTED` is
    refused with `ERR_COMMERCIAL_STATUS_BLOCKS_CONFIRM`."

    Design: Difficulty/cross_entity_state_dependency/slot_confirm_blocked_by_order_commercial_dimension_returns_409
    """
    env = setup_order_with_reserved_slot(
        setup_reference_data(line={}), commercial_status=None
    )

    response = api_client.confirm_build_slot(env["slot"]["id"], PLANNER)

    validate_error(response, ApiErrorId.ERR_COMMERCIAL_STATUS_BLOCKS_CONFIRM.value, 409)
    assert read_slot(env["slot"]["id"])["status"] == "RESERVED"
    order = read_order(env["order"]["id"])
    assert order["fulfillment_status"] == "ENGINEERED"
    assert order["commercial_status"] == "QUOTED"
    assert read_line(env["line"]["id"])["committed_slot_days"] == 20


def test_the_same_confirmation_succeeds_once_the_purchase_order_is_booked():
    """Booking the purchase order is the only thing that changes, and the identical
    confirmation then commits the factory.

    PRD: "An order never reaches `SLOTTED` on its own — only through its slot."

    Design: Difficulty/cross_entity_state_dependency/slot_confirm_blocked_by_order_commercial_dimension_returns_409
    """
    env = setup_order_with_reserved_slot(
        setup_reference_data(line={}), commercial_status=None
    )
    blocked = api_client.confirm_build_slot(env["slot"]["id"], PLANNER)
    validate_error(blocked, ApiErrorId.ERR_COMMERCIAL_STATUS_BLOCKS_CONFIRM.value, 409)
    validate_success(
        api_client.commercial_advance_machine_order(env["order"]["id"], "PO_RECEIVED", ADMIN)
    )

    data = validate_success(api_client.confirm_build_slot(env["slot"]["id"], PLANNER))

    assert data["status"] == "CONFIRMED"
    assert read_order(env["order"]["id"])["fulfillment_status"] == "SLOTTED"


def test_a_line_taken_out_of_service_after_reservation_blocks_the_confirmation():
    """The guard sits on the line rather than the slot, so the confirmation re-reads
    the line's status instead of trusting the reservation.

    PRD: "Taking a line out of service moves `status` to `MAINTENANCE`, after which
    neither a fresh reservation nor a confirmation may touch it
    (`ERR_LINE_NOT_OPEN`)."

    Design: Corner/state_machines/slot_confirm_on_maintenance_hold_line_returns_line_not_open
    """
    env = setup_order_with_reserved_slot(setup_reference_data(line={}))
    validate_success(api_client.maintenance_hold_production_line(env["line"]["id"], ADMIN))

    response = api_client.confirm_build_slot(env["slot"]["id"], PLANNER)

    validate_error(response, ApiErrorId.ERR_LINE_NOT_OPEN.value, 409)
    assert read_slot(env["slot"]["id"])["status"] == "RESERVED"
    assert read_order(env["order"]["id"])["fulfillment_status"] == "ENGINEERED"
    line = read_line(env["line"]["id"])
    assert line["status"] == "MAINTENANCE"
    assert line["committed_slot_days"] == 20


def test_metal_cannot_be_cut_while_a_long_lead_part_is_still_on_order():
    """Slotting only needs the purchase order released, but starting the build needs
    the part in the building, so the confirmed slot stays where it is.

    PRD: "In both guises every long-lead component of the order must be `RECEIVED`
    (`ERR_COMPONENTS_NOT_RECEIVED`)."

    Design: Corner/errors/start_build_with_on_order_component_returns_409_components_not_received
    """
    env = seed_component(
        setup_engineered_order(setup_reference_data(line={})),
        part_number="SERVO-DRV-9",
        lead_time_days=10,
    )
    validate_success(api_client.release_po_long_lead_component(env["component"]["id"], PLANNER))
    validate_success(
        api_client.commercial_advance_machine_order(env["order"]["id"], "PO_RECEIVED", ADMIN)
    )
    env = reserve_slot(env, start_date="2026-08-11")
    validate_success(api_client.confirm_build_slot(env["slot"]["id"], PLANNER))

    response = api_client.start_build_build_slot(env["slot"]["id"], PLANNER)

    validate_error(response, ApiErrorId.ERR_COMPONENTS_NOT_RECEIVED.value, 409)
    assert read_slot(env["slot"]["id"])["status"] == "CONFIRMED"
    assert read_order(env["order"]["id"])["fulfillment_status"] == "SLOTTED"
    assert (
        validate_success(api_client.get_long_lead_component(env["component"]["id"], PLANNER))[
            "status"
        ]
        == "ON_ORDER"
    )


def test_a_slot_already_in_build_can_no_longer_be_released():
    """Release is available only before metal is cut, so once the build has started
    the slot is locked and the line keeps its committed days.

    PRD: "Any confirmation, build start or release addressed to a slot in the wrong
    state is refused with `ERR_INVALID_SLOT_STATE`."

    Design: Corner/endpoints/build_slot_release_from_in_build_returns_invalid_slot_state
    """
    env = setup_order_in_build(setup_reference_data(line={}))

    response = api_client.release_build_slot(env["slot"]["id"], PLANNER)

    validate_error(response, ApiErrorId.ERR_INVALID_SLOT_STATE.value, 409)
    assert read_slot(env["slot"]["id"])["status"] == "IN_BUILD"
    assert read_order(env["order"]["id"])["fulfillment_status"] == "IN_BUILD"
    assert read_line(env["line"]["id"])["committed_slot_days"] == 20
