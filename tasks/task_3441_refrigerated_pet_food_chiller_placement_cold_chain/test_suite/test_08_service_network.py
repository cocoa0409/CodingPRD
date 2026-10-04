"""Service network: dispatch windows, resolution, and the shipment operational gate (PRD §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    create_dispatch_payload,
    create_released_lot,
    create_resolve_payload,
    create_service_ticket_payload,
    create_shipment_payload,
    get_placement,
    get_product_lot,
    list_service_tickets,
    setup_active_placement,
    setup_suspended_placement,
    validate_error,
    validate_success,
)


def _open_ticket(api, chiller_id, summary, headers):
    resp = api.create_service_ticket(create_service_ticket_payload(chiller_id, issue_summary=summary), headers)
    return validate_success(resp, expected_status=201)


def test_service_window_half_open_adjacency_legal(api, service_dispatcher_headers):
    """PRD §3.5: "The dispatch window is a half-open interval from
    `window_start` (inclusive) to `window_end` (exclusive): `window_end` must
    be strictly later than `window_start` (otherwise 400 `ERR_WINDOW_INVALID`),
    and the window must not overlap any other `DISPATCHED` ticket's window on
    the same chiller — touching endpoints are not an overlap, so an existing
    window ending exactly when the new one starts, or the new one ending
    exactly when an existing one starts, is allowed — otherwise 409
    `ERR_SERVICE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/service_calendar_half_open_adjacency
    """
    ctx = setup_active_placement()
    cid = ctx["chiller"]["id"]
    t1 = _open_ticket(api, cid, "t1 fan noise", service_dispatcher_headers)
    t2 = _open_ticket(api, cid, "t2 light flicker", service_dispatcher_headers)

    r1 = validate_success(
        api.dispatch_service_ticket(t1["id"], create_dispatch_payload(
            window_start="2026-09-03T09:00:00Z", window_end="2026-09-03T11:00:00Z"),
            service_dispatcher_headers),
        expected_status=200,
    )
    assert r1["status"] == "DISPATCHED"
    assert r1["window_start"] == "2026-09-03T09:00:00Z"
    assert r1["window_end"] == "2026-09-03T11:00:00Z"

    r2 = validate_success(
        api.dispatch_service_ticket(t2["id"], create_dispatch_payload(
            window_start="2026-09-03T11:00:00Z", window_end="2026-09-03T13:00:00Z"),
            service_dispatcher_headers),
        expected_status=200,
    )
    assert r2["status"] == "DISPATCHED", "half-open adjacency: existing.window_end == new.window_start is legal"


def test_service_window_one_minute_overlap_rejected(api, service_dispatcher_headers):
    """PRD §3.5: "the window must not overlap any other `DISPATCHED` ticket's
    window on the same chiller — touching endpoints are not an overlap, so an
    existing window ending exactly when the new one starts, or the new one
    ending exactly when an existing one starts, is allowed — otherwise 409
    `ERR_SERVICE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/service_calendar_half_open_adjacency
    """
    ctx = setup_active_placement()
    cid = ctx["chiller"]["id"]
    t1 = _open_ticket(api, cid, "t1 fan noise", service_dispatcher_headers)
    t3 = _open_ticket(api, cid, "t3 door seal", service_dispatcher_headers)

    validate_success(
        api.dispatch_service_ticket(t1["id"], create_dispatch_payload(
            window_start="2026-09-03T09:00:00Z", window_end="2026-09-03T11:00:00Z"),
            service_dispatcher_headers),
        expected_status=200,
    )
    resp = api.dispatch_service_ticket(t3["id"], create_dispatch_payload(
        window_start="2026-09-03T10:59:00Z", window_end="2026-09-03T12:00:00Z"),
        service_dispatcher_headers)
    validate_error(resp, ApiErrorId.ERR_SERVICE_WINDOW_OVERLAP)
    assert resp.status_code == 409, "10:59 start overlaps [09:00, 11:00) by one minute"


def test_dispatch_invalid_window_and_double_resolve_rejected(api, service_dispatcher_headers,
                                                             field_technician_headers):
    """PRD §3.5: "`window_end` must be strictly later than `window_start`
    (otherwise 400 `ERR_WINDOW_INVALID`)"
    PRD §3.5: "Resolution is the `FieldTechnician`'s exclusive action,
    available from either `OPEN` or `DISPATCHED`, and lands the ticket in the
    terminal `RESOLVED` state with the technician's `resolution_note` recorded
    and `version` incremented. Resolving a terminal ticket is rejected with 409
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/dispatch_invalid_window_and_double_resolve_rejected
    """
    ctx = setup_active_placement()
    ticket = _open_ticket(api, ctx["chiller"]["id"], "rattling fan", service_dispatcher_headers)

    resp = api.dispatch_service_ticket(ticket["id"], create_dispatch_payload(
        window_start="2026-09-03T11:00:00Z", window_end="2026-09-03T11:00:00Z"),
        service_dispatcher_headers)
    validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID)
    assert resp.status_code == 400, "zero-length window"
    tickets = list_service_tickets(ctx["chiller"]["id"])
    assert tickets[0]["status"] == "OPEN", "rejected dispatch leaves the ticket OPEN"

    resolved = validate_success(
        api.resolve_service_ticket(ticket["id"], create_resolve_payload(
            resolution_note="tightened fan mount without dispatch"), field_technician_headers),
        expected_status=200,
    )
    assert resolved["status"] == "RESOLVED", "dispatch is optional: OPEN -> RESOLVED is legal"
    assert resolved["resolution_note"] == "tightened fan mount without dispatch"

    resp = api.resolve_service_ticket(ticket["id"], create_resolve_payload(resolution_note="second attempt"),
                                      field_technician_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409, "RESOLVED is terminal"


def test_field_technician_cannot_dispatch(api, service_dispatcher_headers, field_technician_headers):
    """PRD §3.5: "Dispatching is the `ServiceDispatcher`'s exclusive action and
    moves `OPEN` to `DISPATCHED` — dispatching a ticket in any other state
    yields 409 `ERR_INVALID_STATE`."
    PRD §2.1: "an authenticated caller whose role is not in the endpoint's list
    is rejected with 403 `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/field_technician_cannot_dispatch
    """
    ctx = setup_active_placement()
    ticket = _open_ticket(api, ctx["chiller"]["id"], "fan rattle", service_dispatcher_headers)
    resp = api.dispatch_service_ticket(ticket["id"], create_dispatch_payload(
        window_start="2026-09-03T09:00:00Z", window_end="2026-09-03T10:00:00Z"),
        field_technician_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert resp.status_code == 403

    tickets = list_service_tickets(ctx["chiller"]["id"])
    assert tickets[0]["status"] == "OPEN"
    assert tickets[0]["window_start"] is None and tickets[0]["window_end"] is None


def test_shipment_blocked_while_placement_suspended(api, logistics_coordinator_headers):
    """PRD §3.7: "The destination store must have a placement with `status`
    `ACTIVE` (otherwise 409 `ERR_PLACEMENT_NOT_ACTIVE`), that placement's
    `operational_status` must be `OK` (otherwise 409
    `ERR_PLACEMENT_NOT_OPERATIONAL`), and its `standing_deliveries_per_week`
    must be greater than 0 (otherwise 409 `ERR_DELIVERY_ROUTE_INACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/shipment_requires_placement_operational
    """
    ctx = setup_suspended_placement()  # severe excursion -> placement SUSPENDED
    lot = create_released_lot(quantity_units=100)
    resp = api.create_shipment(create_shipment_payload(ctx["store"]["id"], lot["id"], 10),
                               logistics_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_PLACEMENT_NOT_OPERATIONAL)
    assert resp.status_code == 409, "shipment is gated on the PLACEMENT's operational axis"

    lot_after = get_product_lot(lot["id"])
    assert lot_after["unshipped_qty"] == 100 and lot_after["in_transit_qty"] == 0, (
        "rejected shipment must not move lot buckets"
    )


def test_shipment_allowed_after_repair_restores_ok(api, logistics_coordinator_headers,
                                                   field_technician_headers):
    """PRD §3.5: "the placement's `operational_status` lifts from `SUSPENDED`
    back to `OK` with its `version` incrementing."
    PRD §3.7: "The truck departs immediately: `departed_at` is stamped with the
    logical now at creation, the shipment is born `IN_TRANSIT`, and the lot's
    buckets move `quantity_units` from `unshipped_qty` to `in_transit_qty`."

    Design: Difficulty/cross_entity_state_dependency/shipment_requires_placement_operational
    """
    ctx = setup_suspended_placement()
    lot = create_released_lot(quantity_units=100)
    validate_success(
        api.resolve_service_ticket(ctx["auto_ticket"]["id"],
                                   create_resolve_payload(resolution_note="fixed thermostat"),
                                   field_technician_headers),
        expected_status=200,
    )
    assert get_placement(ctx["placement"]["id"])["operational_status"] == "OK"

    resp = api.create_shipment(create_shipment_payload(ctx["store"]["id"], lot["id"], 10),
                               logistics_coordinator_headers)
    shipment = validate_success(resp, expected_status=201)
    assert shipment["status"] == "IN_TRANSIT"

    lot_after = get_product_lot(lot["id"])
    assert lot_after["unshipped_qty"] == 90 and lot_after["in_transit_qty"] == 10
