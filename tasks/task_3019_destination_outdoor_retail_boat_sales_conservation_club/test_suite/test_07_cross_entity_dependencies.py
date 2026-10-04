"""Depth tests: cross-entity state dependencies across different entity pairs."""
from test_helpers import (
    ATTRACTION_HOST,
    ApiErrorId,
    RECEIVING_MANAGER,
    SERVICE_TECHNICIAN,
    STORE_MANAGER,
    create_bay_booking,
    create_boat_unit,
    create_member,
    create_open_attraction,
    create_order_fulfillment,
    create_service_order,
    create_store,
    get_success_data,
    request_session,
    set_clock,
    validate_error,
)


# ===========================================================================
# fulfillment_release_requires_service_order_delivered  (queue A / cross_entity_state_dependency)
# ===========================================================================

def _fulfillment_ready_but_order_not_delivered(api):
    """A bay booking checked in and an oversize order COMPLETED but not DELIVERED."""
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_xs@x.com",
                           full_name="Xan Shore")
    unit = create_boat_unit(api, store["id"], stock_no="BU-XS", model_name="Bay 170",
                            unit_price_cents=4_000_000, unit_condition="NEW",
                            hull_id_no="HINXS0000001", motor_price_cents=0,
                            trailer_price_cents=0)
    order = create_service_order(api, store["id"], unit["id"],
                                 order_kind="OVERSIZE_LOADING", promised_lead_days=3)
    booking = create_bay_booking(api, store["id"], member["id"], order["id"])
    fulfillment = create_order_fulfillment(
        api, store["id"], member["id"], order["id"], booking["id"], booking["version"]
    )
    get_success_data(api.schedule_service_order(order["id"], SERVICE_TECHNICIAN), 200)
    get_success_data(api.start_service_order(order["id"], SERVICE_TECHNICIAN), 200)
    completed_order = get_success_data(
        api.complete_service_order(order["id"], SERVICE_TECHNICIAN), 200
    )
    checked_booking = get_success_data(
        api.check_in_bay_booking(booking["id"], RECEIVING_MANAGER), 200
    )
    return store, member, unit, completed_order, checked_booking, fulfillment


def test_release_is_blocked_while_the_pre_service_order_has_not_been_delivered(api):
    """PRD §3.6: "The pre-service order must actually be `DELIVERED`; a release
    attempted while it is not is refused with `ERR_FULFILLMENT_BLOCKED`
    (HTTP 409)."
    PRD §2.8.1: "An oversize carry-out must have its booking already
    `CHECKED_IN` or `COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/fulfillment_release_requires_service_order_delivered
    """
    store, member, unit, order, booking, fulfillment = (
        _fulfillment_ready_but_order_not_delivered(api)
    )
    assert order["status"] == "COMPLETED"
    assert booking["status"] == "CHECKED_IN"

    response = api.release_order_fulfillment(
        fulfillment["id"], {"rm_cross_check_code": "rm_7741"}, RECEIVING_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_FULFILLMENT_BLOCKED, 409)

    after = get_success_data(
        api.get_order_fulfillment(fulfillment["id"], RECEIVING_MANAGER), 200
    )
    assert after["status"] == "READY_FOR_RELEASE", (
        f"the rejection left the row untouched; got {after['status']}"
    )


def test_the_identical_release_payload_succeeds_one_the_order_reaches_delivered(api):
    """PRD §3.6: "A successful release stamps `fulfilled_at_utc`, moves the
    fulfilment from `READY_FOR_RELEASE` to `RELEASED`, and — when the service
    order the fulfilment consumed is now delivered — closes the booking from
    `CHECKED_IN` to `COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/fulfillment_release_requires_service_order_delivered
    """
    store, member, unit, order, booking, fulfillment = (
        _fulfillment_ready_but_order_not_delivered(api)
    )
    blocked = api.release_order_fulfillment(
        fulfillment["id"], {"rm_cross_check_code": "rm_7741"}, RECEIVING_MANAGER
    )
    validate_error(blocked, ApiErrorId.ERR_FULFILLMENT_BLOCKED, 409)

    get_success_data(
        api.deliver_service_order(order["id"], SERVICE_TECHNICIAN), 200
    )
    released = get_success_data(
        api.release_order_fulfillment(
            fulfillment["id"], {"rm_cross_check_code": "rm_7741"}, RECEIVING_MANAGER
        ),
        200,
    )
    assert released["status"] == "RELEASED", (
        "the identical release payload succeeds once the order is delivered; got "
        f"{released['status']}"
    )
    assert released["fulfilled_at_utc"] is not None, (
        "a successful release stamps fulfilled_at_utc"
    )

    closed_booking = get_success_data(
        api.get_bay_booking(booking["id"], RECEIVING_MANAGER), 200
    )
    assert closed_booking["status"] == "COMPLETED", (
        "the booking also advanced as a consequence of the release; got "
        f"{closed_booking['status']}"
    )


# ===========================================================================
# attraction_session_confirmation_requires_open_posture  (queue A / cross_entity_state_dependency)
# ===========================================================================

def _over_budget_store(api):
    """A 60-minute budget store with a 40-seat aquarium."""
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api, dwell_capacity_minutes=60)
    member = create_member(api, store["id"], email="m_po@x.com",
                           full_name="Poe Strand")
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=40, dwell_cost_minutes=30)
    return store, member, attraction


def test_a_session_that_overshoots_the_budget_tips_the_store_into_the_frozen_posture(api):
    """PRD §2.7: "A store is `FROZEN` when its free minutes have fallen below
    zero, or when at least one of its venues is over capacity."
    Design: Difficulty/cross_entity_state_dependency/attraction_session_confirmation_requires_open_posture
    """
    store, member, attraction = _over_budget_store(api)

    response = request_session(api, store["id"], attraction["id"], member["id"],
                               party_size=13,
                               slot_start_utc="2026-11-01T10:00:00Z",
                               slot_end_utc="2026-11-01T11:00:00Z")
    session = get_success_data(response, 201)
    assert session["status"] == "CONFIRMED"
    assert session["dwell_charge_minutes"] > 60, (
        "the single confirmed party must overshoot the 60-minute budget for the "
        f"aggregate gate to close; got {session['dwell_charge_minutes']}"
    )

    summary = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert summary["attraction_posture"] == "FROZEN", (
        "free minutes have fallen below zero, so the aggregate gate closed as a "
        f"consequence of the first session; got {summary['attraction_posture']}"
    )
    assert summary["dwell_free_minutes"] < 0, (
        f"60 minus the commit leaves a negative remainder; got "
        f"{summary['dwell_free_minutes']}"
    )


def test_the_frozen_posture_rejects_the_next_session_before_its_capacity_is_consulted(api):
    """PRD §2.7: "A `FROZEN` store blocks any operation that moves an attraction
    session toward `CONFIRMED` or `IN_PROGRESS` with `ERR_POSTURE_FROZEN`
    (HTTP 409)."
    PRD §2.7: "When a store that had gone `RESTRICTED` releases enough capacity
    it returns to `OPEN` on the next derivation."

    Design: Difficulty/cross_entity_state_dependency/attraction_session_confirmation_requires_open_posture
    """
    store, member, attraction = _over_budget_store(api)
    first = get_success_data(
        request_session(api, store["id"], attraction["id"], member["id"], party_size=13,
                        slot_start_utc="2026-11-01T10:00:00Z",
                        slot_end_utc="2026-11-01T11:00:00Z"),
        201,
    )

    response = request_session(api, store["id"], attraction["id"], member["id"],
                               party_size=2,
                               slot_start_utc="2026-11-02T10:00:00Z",
                               slot_end_utc="2026-11-02T11:00:00Z")
    validate_error(response, ApiErrorId.ERR_POSTURE_FROZEN, 409)

    unchanged = get_success_data(api.get_session(first["id"], ATTRACTION_HOST), 200)
    assert unchanged["status"] == "CONFIRMED", (
        "the gate rejects the new booking rather than rolling back the session "
        f"that closed it; got {unchanged['status']}"
    )