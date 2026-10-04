"""Routes, stops, and shipments: window adjacency/overlap, lockability,
vehicle capacity, duplicate sequences, late arrival, cross-scope batches."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    add_route_stop,
    commit_batch,
    create_batch,
    create_completed_batch,
    create_dispatched_route,
    create_door,
    create_route,
    setup_hub_with_line,
    stage_shipment,
)

NA = TEST_USERS["network_admin_headers"]
RP = TEST_USERS["route_planner_headers"]
RD = TEST_USERS["route_driver_headers"]
HM = TEST_USERS["hub_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/route_stop_windows_adjacency_allowed_overlap_rejected
# ---------------------------------------------------------------------------

def test_route_stop_adjacent_windows_allowed(api):
    """PRD §3.5: "the half-open convention means adjacency — one window's
    `window_end` equal to the next stop's `window_start` — is allowed."

    Design: Difficulty/resource_temporal_overlap/route_stop_windows_adjacency_allowed_overlap_rejected
    """
    network, hub, _line = setup_hub_with_line(network_code="N15", hub_code="H15", region="R15")
    door = create_door(
        network["id"], door_kind="SPOKE", ownership="FRANCHISE", region="R15", hub_id=hub["id"]
    )
    route = create_route(network["id"], hub["id"], route_code="RT15")
    add_route_stop(
        network["id"], hub["id"], route["id"], door["id"], sequence_no=1,
        window_start="2026-09-01T08:00:00Z", window_end="2026-09-01T10:00:00Z",
    )
    # Adjacent window [10:00, 12:00) does not overlap [08:00, 10:00).
    resp = api.add_route_stop(
        network["id"], hub["id"], route["id"],
        {
            "door_id": door["id"], "sequence_no": 2,
            "window_start": "2026-09-01T10:00:00Z", "window_end": "2026-09-01T12:00:00Z",
        },
        RP,
    )
    stop = validate_success(resp, expected_status=201)
    assert stop["sequence_no"] == 2


def test_route_stop_overlapping_window_rejected(api):
    """PRD §3.5: "Two stops on the same route that share a door must not have
    overlapping windows ... An overlap is rejected with
    `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/route_stop_windows_adjacency_allowed_overlap_rejected
    """
    network, hub, _line = setup_hub_with_line(network_code="N15B", hub_code="H15B", region="R15")
    door = create_door(
        network["id"], door_kind="SPOKE", ownership="FRANCHISE", region="R15", hub_id=hub["id"]
    )
    route = create_route(network["id"], hub["id"], route_code="RT15")
    add_route_stop(
        network["id"], hub["id"], route["id"], door["id"], sequence_no=1,
        window_start="2026-09-01T08:00:00Z", window_end="2026-09-01T10:00:00Z",
    )
    resp = api.add_route_stop(
        network["id"], hub["id"], route["id"],
        {
            "door_id": door["id"], "sequence_no": 2,
            "window_start": "2026-09-01T09:00:00Z", "window_end": "2026-09-01T11:00:00Z",
        },
        RP,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


# ---------------------------------------------------------------------------
# Corner/state_machines/route_lock_without_stops_rejected
# ---------------------------------------------------------------------------

def test_route_lock_without_stops_rejected(api):
    """PRD §3.5: "Locking the route (`PLANNING` → `LOCKED`) requires at least
    one stop and requires the stops' window spans to total at least 30
    minutes; a route failing either condition is rejected with
    `ERR_ROUTE_NOT_LOCKABLE` (HTTP 422)."

    Design: Corner/state_machines/route_lock_without_stops_rejected
    """
    network, hub, _line = setup_hub_with_line(network_code="NRL", hub_code="HRL", region="RRL")
    route = create_route(
        network["id"], hub["id"], route_code="RRL", vehicle_capacity_dozens=100
    )

    resp = api.lock_route(network["id"], hub["id"], route["id"], RP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_LOCKABLE)

    after = validate_success(api.get_route(network["id"], hub["id"], route["id"], RP))
    assert after["route_status"] == "PLANNING"


# ---------------------------------------------------------------------------
# Corner/state_machines/route_dispatch_blocked_over_vehicle_capacity
# ---------------------------------------------------------------------------

def test_route_dispatch_blocked_over_vehicle_capacity(api):
    """PRD §3.5: "the route's `loaded_dozens` — the sum of `dozens_shipped`
    across its shipments — must not exceed `vehicle_capacity_dozens`
    (`ERR_CAPACITY_EXCEEDED` otherwise)".

    Design: Corner/state_machines/route_dispatch_blocked_over_vehicle_capacity
    """
    network, hub, line = setup_hub_with_line(network_code="NRC", hub_code="HRC", region="RRC")
    door = create_door(
        network["id"], door_kind="GROCERY", ownership="COMPANY", region="RRC", hub_id=hub["id"]
    )
    batch = create_completed_batch(network["id"], hub["id"], line["id"], planned_dozens=100)
    route = create_route(
        network["id"], hub["id"], route_code="RRC", vehicle_capacity_dozens=30
    )
    stop = add_route_stop(
        network["id"], hub["id"], route["id"], door["id"],
        window_start="2026-09-01T08:00:00Z", window_end="2026-09-01T10:00:00Z",
    )
    stage_shipment(network["id"], hub["id"], route["id"], stop["id"], batch["id"], 40)
    validate_success(api.lock_route(network["id"], hub["id"], route["id"], RP))

    resp = api.dispatch_route(network["id"], hub["id"], route["id"], RP)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    after = validate_success(api.get_route(network["id"], hub["id"], route["id"], RP))
    assert after["route_status"] == "LOCKED"


# ---------------------------------------------------------------------------
# Corner/state_machines/duplicate_sequence_no_rejected
# ---------------------------------------------------------------------------

def test_duplicate_sequence_no_rejected(api):
    """PRD §3.5: "a `sequence_no` that must be at least 1 and unique within
    the route — duplicates are rejected with `ERR_DUPLICATE_SEQUENCE`".

    Design: Corner/state_machines/duplicate_sequence_no_rejected
    """
    network, hub, _line = setup_hub_with_line(network_code="NDQ", hub_code="HDQ", region="RDQ")
    door1 = create_door(
        network["id"], door_kind="GROCERY", ownership="COMPANY", region="RDQ", hub_id=hub["id"]
    )
    door2 = create_door(
        network["id"], door_kind="PARTNER", ownership="COMPANY", region="RDQ", hub_id=hub["id"]
    )
    route = create_route(network["id"], hub["id"], route_code="RDQ", vehicle_capacity_dozens=100)
    add_route_stop(
        network["id"], hub["id"], route["id"], door1["id"], sequence_no=1,
        window_start="2026-09-01T08:00:00Z", window_end="2026-09-01T09:00:00Z",
    )
    resp = api.add_route_stop(
        network["id"], hub["id"], route["id"],
        {
            "door_id": door2["id"], "sequence_no": 1,
            "window_start": "2026-09-01T09:00:00Z", "window_end": "2026-09-01T10:00:00Z",
        },
        RP,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SEQUENCE)


# ---------------------------------------------------------------------------
# Corner/validations/arrive_after_window_end_rejected
# ---------------------------------------------------------------------------

def test_arrive_after_window_end_rejected(api):
    """PRD §3.5: "arrival attempted after `window_end`, when the stop is not
    late-arrival-eligible, is rejected with `ERR_STOP_WINDOW_PASSED`."

    Design: Corner/validations/arrive_after_window_end_rejected
    """
    network, hub, line = setup_hub_with_line(network_code="NAW", hub_code="HAW", region="RAW")
    door = create_door(
        network["id"], door_kind="GROCERY", ownership="COMPANY", region="RAW", hub_id=hub["id"]
    )
    batch = create_completed_batch(network["id"], hub["id"], line["id"], planned_dozens=30)
    route, stop, _shipment = create_dispatched_route(
        network["id"], hub["id"], door["id"], batch["id"], dozens_shipped=30,
        window_start="2026-09-01T08:00:00Z", window_end="2026-09-01T10:00:00Z",
        vehicle_capacity_dozens=100, route_code="RAW",
    )
    get_success_data(api.set_clock("2026-09-01T11:00:00Z", NA))

    resp = api.arrive_stop(network["id"], hub["id"], route["id"], stop["id"], RD)
    validate_error(resp, ApiErrorId.ERR_STOP_WINDOW_PASSED)


# ---------------------------------------------------------------------------
# Corner/errors/cross_scope_reference_rejected
# ---------------------------------------------------------------------------

def test_cross_scope_reference_rejected(api):
    """PRD §2.10: "The cross-scope rule applies to every endpoint that takes
    an entity reference in its request body ... a shipment's batch must come
    from the same hub as the route it is staged on."
    PRD §5: `ERR_CROSS_SCOPE_REFERENCE` (422).

    Design: Corner/errors/cross_scope_reference_rejected
    """
    network, hub_a, line_a = setup_hub_with_line(network_code="NCS2", hub_code="HCSA", region="RCS")
    hub_b = get_success_data(
        api.create_hub(
            network["id"],
            {"hub_code": "HCSB", "daily_capacity_dozens": 500, "territory_region": "RCS"},
            NA,
        )
    )
    door_b = create_door(
        network["id"], door_kind="GROCERY", ownership="COMPANY", region="RCS", hub_id=hub_b["id"]
    )
    batch_a = create_completed_batch(network["id"], hub_a["id"], line_a["id"], planned_dozens=30)

    route_b = create_route(network["id"], hub_b["id"], route_code="RCSB", vehicle_capacity_dozens=100)
    stop_b = add_route_stop(
        network["id"], hub_b["id"], route_b["id"], door_b["id"],
        window_start="2026-09-01T08:00:00Z", window_end="2026-09-01T10:00:00Z",
    )

    resp = api.stage_shipment(
        network["id"], hub_b["id"], route_b["id"], stop_b["id"],
        {"production_batch_id": batch_a["id"], "dozens_shipped": 10},
        RP,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_SCOPE_REFERENCE)
