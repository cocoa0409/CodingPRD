"""Delivery routing and confirmation: stop-sequence ranking within a route,
confirmation overfill and state guards, and delivery not-found handling."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_certified_delivery,
    create_confirm_delivery_payload,
    create_customer,
    create_tank,
    create_tank_with_telemetry_delivery,
    list_tank_deliveries,
    post_telemetry,
    set_logical_clock,
    validate_error,
    validate_success,
)


def test_stop_sequence_urgency_then_created_at_tiebreak(api):
    """PRD section 3.6: "Whenever a delivery is created for a route date,
    `stop_sequence` is recomputed across every `SCHEDULED` delivery of that
    date: deliveries are ordered by their tank's weighted-moving-average
    runout, earliest runout first, with deliveries whose tank has no computable
    runout placed after all tanks that have one; ties break by the tank's
    creation time, then by the delivery's own creation time. Ranks are then
    assigned as a dense sequence starting at 1."
    PRD section 3.6: "the logical `route_date` of its creation, and a
    `route_code` formed by prefixing that date with `RT-` — deliveries sharing
    a `route_date` form a single route."

    Design: Corner/calculations/stop_sequence_urgency_then_created_at_tiebreak
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    tank_a = create_tank(customer["id"], required_purity_percent=99.9,
                         max_impurity_ppm=50)
    tank_b = create_tank(customer["id"], required_purity_percent=99.9,
                         max_impurity_ppm=50)
    tank_c = create_tank(customer["id"], required_purity_percent=99.9,
                         max_impurity_ppm=50)
    # Tank A: two readings -> burn 1000 L/h, wma 500 L/h, runout +30h.
    post_telemetry(tank_a["id"], "2026-10-01T00:00:00Z", 30000)
    post_telemetry(tank_a["id"], "2026-10-01T10:00:00Z", 20000)
    # Tanks B and C: one reading each -> no computable runout.
    post_telemetry(tank_b["id"], "2026-10-01T00:00:00Z", 19000)
    post_telemetry(tank_c["id"], "2026-10-01T00:00:00Z", 19000)

    del_a = list_tank_deliveries(tank_a["id"])
    del_b = list_tank_deliveries(tank_b["id"])
    del_c = list_tank_deliveries(tank_c["id"])
    assert len(del_a) == 1 and len(del_b) == 1 and len(del_c) == 1
    for delivery in del_a + del_b + del_c:
        assert delivery["route_code"] == "RT-2026-09-01", (
            f"route_date is the logical clock date at creation, got {delivery['route_code']}"
        )
    assert del_a[0]["stop_sequence"] == 1, (
        "the tank with a concrete WMA runout ranks first"
    )
    assert del_b[0]["stop_sequence"] == 2 and del_c[0]["stop_sequence"] == 3, (
        "null-runout tanks follow, tie-broken by tank creation time "
        f"(B={del_b[0]['stop_sequence']}, C={del_c[0]['stop_sequence']})"
    )


def test_delivery_not_found_on_confirm(api):
    """PRD section 2.8: "Existence: path identifiers resolve, validated left to
    right — customer, then evaluation, contract, plant, network, connection,
    tank, delivery, certificate, turnaround — each failure producing its
    resource-specific 404 (`ERR_CUSTOMER_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`,
    `ERR_CONTRACT_NOT_FOUND`, `ERR_PLANT_NOT_FOUND`, `ERR_NETWORK_NOT_FOUND`,
    `ERR_CONNECTION_NOT_FOUND`, `ERR_TANK_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`,
    `ERR_CERTIFICATE_NOT_FOUND`, or `ERR_TURNAROUND_NOT_FOUND`)."

    Design: Corner/errors/delivery_not_found_on_confirm
    """
    set_logical_clock()
    response = api_client.confirm_delivery(
        NON_EXISTENT_UUID,
        create_confirm_delivery_payload(1000),
        TEST_USERS["pipeline_dispatcher_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DELIVERY_NOT_FOUND)


def test_confirm_overfill_rejected(api):
    """PRD section 3.6: "The delivered quantity must be at least 1 liter and no
    more than the tank's headroom at that moment — capacity minus current level
    — or the confirmation is rejected with `ERR_DELIVERY_OVERFILL`."

    Design: Corner/validations/confirm_overfill_rejected
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    tank, delivery = create_tank_with_telemetry_delivery(customer["id"])
    headroom = tank["capacity_liters"] - tank["current_level_liters"]
    assert headroom == 30000
    response = api_client.confirm_delivery(
        delivery["id"],
        create_confirm_delivery_payload(headroom + 1),
        TEST_USERS["pipeline_dispatcher_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DELIVERY_OVERFILL)
    after = validate_success(api_client.get_delivery(
        delivery["id"], TEST_USERS["pipeline_dispatcher_headers"]
    ))
    assert after["transport_status"] == "SCHEDULED", (
        "a rejected confirmation must not move the delivery"
    )


def test_delivery_completed_lockdown(api):
    """PRD section 3.6: "Physical confirmation is the `PipelineDispatcher`'s
    act, and it is legal only from `SCHEDULED` — any other transport state is
    refused with `ERR_INVALID_STATE_TRANSITION`."
    PRD section 3.6: "A `CERTIFIED` outcome moves the certificate to
    `CERTIFIED` and the delivery to `COMPLETED` with `CERTIFIED` quality."

    Design: Corner/state_machines/delivery_completed_lockdown
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    _, delivery, _ = create_certified_delivery(customer["id"])
    response = api_client.confirm_delivery(
        delivery["id"],
        create_confirm_delivery_payload(100),
        TEST_USERS["pipeline_dispatcher_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    after = validate_success(api_client.get_delivery(
        delivery["id"], TEST_USERS["pipeline_dispatcher_headers"]
    ))
    assert after["delivered_quantity_liters"] == 30000, (
        "the recorded quantity is unchanged by the rejected second confirmation"
    )
