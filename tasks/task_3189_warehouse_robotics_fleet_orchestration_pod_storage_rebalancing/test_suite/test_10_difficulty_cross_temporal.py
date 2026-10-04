"""Queue A (difficulty) translations: cross-entity state dependencies and
resource temporal overlap.

Covers rule_id cross_entity_state_dependency:
- pick_task_sequence_gated_by_pod_zone_posture (2 tests)
- maintenance_window_activation_gated_by_drive_unit_state (2 tests)
Covers rule_id resource_temporal_overlap:
- maintenance_window_buffer_adjacency (2 tests)
- human_entry_permit_closed_interval_capacity (2 tests)
"""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    validate_success,
    get_success_data,
    ApiErrorId,
    set_clock,
    create_zone,
    create_drive_unit,
    create_sku,
    create_pick_station,
    create_pod,
    create_order_with_line,
    create_pick_task_payload,
    create_maintenance_window_payload,
    create_human_entry_permit_payload,
    setup_triaged_human_exception,
    create_and_grant_permit,
    get_station_version,
    get_pick_task,
    get_drive_unit,
    stow_units,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
FLOW = TEST_USERS["flow_controller_headers"]
SUPERVISOR = TEST_USERS["floor_supervisor_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]


def _setup_frozen_pod_zone_scenario():
    """Pod P1 stocked in Z1; station ST1 in Z2; Z1 FROZEN via granted permit;
    a CREATED pick task referencing P1 ready to sequence."""
    set_clock("2026-09-01T08:00:00Z")
    z1 = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                     max_human_occupancy=1)
    z2 = create_zone(zone_code="Z2", grid_x=10, grid_y=0, width=10, height=10,
                     max_human_occupancy=1)
    create_drive_unit(z1["id"], unit_code="DU1")
    pod = create_pod(z1["id"], pod_code="P1", slot_capacity=5)
    sku = create_sku(sku_code="SKU1", velocity_class="LOW")
    station = create_pick_station(z2["id"], station_code="ST1", max_queue=5)
    stow_units(sku, quantity=5)
    exception = setup_triaged_human_exception(z1)
    create_and_grant_permit(
        z1, exception,
        starts_at="2026-09-01T08:30:00Z", ends_at="2026-09-01T09:30:00Z",
    )
    order, line = create_order_with_line(sku["id"], quantity=1)
    task = get_success_data(
        api_client.create_pick_task(
            create_pick_task_payload(
                order["id"], line["id"], pod["id"], station["id"], quantity=1
            ),
            FLOW,
        )
    )
    return {"z1": z1, "z2": z2, "pod": pod, "sku": sku,
            "station": station, "task": task}


def test_sequence_rejected_when_pod_zone_frozen(api):
    """PRD §3.3: "Sequencing is legal only while the station is `OPEN` with
    `queue_length` below `max_queue`, the pod is `IN_STORAGE` or `RESERVED` in
    a zone whose posture is not `FROZEN`, and the slot for the line's SKU on
    that pod has sufficient available units."

    Design: Difficulty/cross_entity_state_dependency/pick_task_sequence_gated_by_pod_zone_posture
    """
    env = _setup_frozen_pod_zone_scenario()
    resp = api.sequence_pick_task(
        env["task"]["id"], get_station_version(env["station"]["id"]), FLOW
    )
    body = resp.json()
    assert body.get("response_type") == "error", (
        f"sequencing against a FROZEN zone pod must fail, got {resp.status_code}"
    )
    assert body["data"]["error_id"] in (
        ApiErrorId.ERR_SAFETY_INTERLOCK.value,
        ApiErrorId.ERR_INVALID_STATE.value,
    ), (
        "frozen-zone sequence rejection must surface as ERR_SAFETY_INTERLOCK "
        f"or ERR_INVALID_STATE, got {body['data']['error_id']}"
    )


def test_sequence_rejected_when_pod_zone_frozen_task_stays_created(api):
    """PRD §3.3: "Sequencing is legal only while the station is `OPEN` with
    `queue_length` below `max_queue`, the pod is `IN_STORAGE` or `RESERVED` in
    a zone whose posture is not `FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/pick_task_sequence_gated_by_pod_zone_posture
    """
    env = _setup_frozen_pod_zone_scenario()
    resp = api.sequence_pick_task(
        env["task"]["id"], get_station_version(env["station"]["id"]), FLOW
    )
    assert resp.status_code >= 400
    task_after = get_pick_task(env["task"]["id"])
    assert task_after["status"] == "CREATED", (
        f"rejected sequence must leave the task CREATED, got {task_after['status']}"
    )


def _setup_en_route_window_scenario():
    """DU1 dispatched (EN_ROUTE) carrying PT1's pod; a CORRECTIVE window on
    DU1 for [09:00, 09:30) exists; clock then advances into the window."""
    set_clock("2026-09-01T08:00:00Z")
    z1 = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                     max_human_occupancy=2)
    z2 = create_zone(zone_code="Z2", grid_x=10, grid_y=0, width=10, height=10,
                     max_human_occupancy=2)
    du = create_drive_unit(z1["id"], unit_code="DU1")
    pod = create_pod(z1["id"], pod_code="P1", slot_capacity=5)
    sku = create_sku(sku_code="SKU1", velocity_class="LOW")
    station = create_pick_station(z2["id"], station_code="ST1", max_queue=5)
    stow_units(sku, quantity=5)
    order, line = create_order_with_line(sku["id"], quantity=1)
    task = get_success_data(
        api_client.create_pick_task(
            create_pick_task_payload(
                order["id"], line["id"], pod["id"], station["id"], quantity=1
            ),
            FLOW,
        )
    )
    get_success_data(
        api_client.sequence_pick_task(task["id"], get_station_version(station["id"]), FLOW)
    )
    dispatched = get_success_data(api_client.dispatch_pick_task(task["id"], FLOW))
    window = get_success_data(
        api_client.create_maintenance_window(
            create_maintenance_window_payload(
                du["id"],
                starts_at="2026-09-01T09:00:00Z",
                ends_at="2026-09-01T09:30:00Z",
                kind="CORRECTIVE",
            ),
            TECH,
        )
    )
    set_clock("2026-09-01T09:15:00Z")
    return {"du": du, "task": dispatched, "window": window}


def test_window_activates_while_unit_en_route(api):
    """PRD §3.5: "A window is born `SCHEDULED` and becomes `ACTIVE`
    automatically when the logical clock enters its half-open interval;
    activation pulls a unit in `ACTIVE` or `CHARGING` into `MAINTENANCE`."

    Activation is clock-driven (unconditional); only the unit pull is gated
    on ACTIVE/CHARGING, so an EN_ROUTE unit's window still activates while
    leaving the unit untouched.

    Design: Difficulty/cross_entity_state_dependency/maintenance_window_activation_gated_by_drive_unit_state
    """
    env = _setup_en_route_window_scenario()
    window_after = get_success_data(
        api_client.get_maintenance_window(env["window"]["id"], TECH)
    )
    assert window_after["status"] == "ACTIVE", (
        f"window must activate when the clock enters its interval even while "
        f"the unit is EN_ROUTE (the pull is gated, activation is not), "
        f"got {window_after['status']}"
    )


def test_en_route_unit_unaffected_by_window_interval(api):
    """PRD §3.5: "A window is born `SCHEDULED` and becomes `ACTIVE`
    automatically when the logical clock enters its half-open interval;
    activation pulls a unit in `ACTIVE` or `CHARGING` into `MAINTENANCE`."

    Design: Difficulty/cross_entity_state_dependency/maintenance_window_activation_gated_by_drive_unit_state
    """
    env = _setup_en_route_window_scenario()
    unit_after = get_drive_unit(env["du"]["id"])
    assert unit_after["status"] == "EN_ROUTE", (
        f"EN_ROUTE unit must be untouched by the window interval, got {unit_after['status']}"
    )


def _setup_existing_window():
    """Zone + unit + one PREVENTIVE window [10:00, 11:00)."""
    set_clock("2026-09-01T08:00:00Z")
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                       max_human_occupancy=2)
    du = create_drive_unit(zone["id"], unit_code="DU1")
    window = get_success_data(
        api_client.create_maintenance_window(
            create_maintenance_window_payload(
                du["id"],
                starts_at="2026-09-01T10:00:00Z",
                ends_at="2026-09-01T11:00:00Z",
                kind="PREVENTIVE",
            ),
            TECH,
        )
    )
    return du, window


def test_maintenance_window_gap_below_buffer_rejected(api):
    """PRD §2.6: "8. **Temporal validity** — interval endpoints valid per
    §2.4, and a new maintenance window must leave at least 15 minutes of gap
    to any existing non-cancelled window for the same unit under half-open
    semantics (adjacency with an exactly 15-minute gap is allowed)
    (`ERR_TEMPORAL_CONFLICT`, 422)."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_buffer_adjacency
    """
    du, _window = _setup_existing_window()
    resp = api.create_maintenance_window(
        create_maintenance_window_payload(
            du["id"],
            starts_at="2026-09-01T11:10:00Z",
            ends_at="2026-09-01T12:00:00Z",
            kind="PREVENTIVE",
        ),
        TECH,
    )
    validate_error(resp, ApiErrorId.ERR_TEMPORAL_CONFLICT)


def test_maintenance_window_exact_buffer_adjacency_allowed(api):
    """PRD §2.6: "a new maintenance window must leave at least 15 minutes of
    gap to any existing non-cancelled window for the same unit under half-open
    semantics (adjacency with an exactly 15-minute gap is allowed)."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_buffer_adjacency
    """
    du, _window = _setup_existing_window()
    created = get_success_data(
        api_client.create_maintenance_window(
            create_maintenance_window_payload(
                du["id"],
                starts_at="2026-09-01T11:15:00Z",
                ends_at="2026-09-01T12:00:00Z",
                kind="PREVENTIVE",
            ),
            TECH,
        )
    )
    assert created["status"] == "SCHEDULED", (
        f"a window starting exactly 15 minutes after the prior window's end "
        f"must be accepted, got status {created['status']}"
    )


def _setup_permit_capacity_scenario():
    """Zone (occupancy 1) with TRIAGED_HUMAN exception and two REQUESTED
    permits P1 [08:00, 09:00] and P2 [09:00, 10:00] (touching endpoints).
    Clock at 08:30 (inside both? P1 spans it; P2 starts at 09:00)."""
    set_clock("2026-09-01T08:30:00Z")
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                       max_human_occupancy=1)
    exception = setup_triaged_human_exception(zone)
    p1 = get_success_data(
        api_client.create_human_entry_permit(
            create_human_entry_permit_payload(
                zone["id"], exception["id"],
                starts_at="2026-09-01T08:00:00Z",
                ends_at="2026-09-01T09:00:00Z",
            ),
            SUPERVISOR,
        )
    )
    p2 = get_success_data(
        api_client.create_human_entry_permit(
            create_human_entry_permit_payload(
                zone["id"], exception["id"],
                starts_at="2026-09-01T09:00:00Z",
                ends_at="2026-09-01T10:00:00Z",
            ),
            SUPERVISOR,
        )
    )
    return zone, exception, p1, p2


def test_permit_closed_interval_touching_counts_as_overlap(api):
    """PRD §2.4: "`HumanEntryPermit.starts_at` and `HumanEntryPermit.ends_at`
    describe a **closed** interval — both endpoints inclusive."
    PRD §3.6: "grants a `REQUESTED` permit provided the exception is
    `TRIAGED_HUMAN` and the count of `ACTIVE` permits for the zone with
    overlapping closed intervals is below the zone's `max_human_occupancy`
    (`ERR_CAPACITY_EXCEEDED`)."

    Design: Difficulty/resource_temporal_overlap/human_entry_permit_closed_interval_capacity
    """
    _zone, _exception, p1, p2 = _setup_permit_capacity_scenario()
    get_success_data(api_client.grant_human_entry_permit(p1["id"], SAFETY))
    resp = api.grant_human_entry_permit(p2["id"], SAFETY)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


def test_permit_capacity_rejection_is_422(api):
    """PRD §3.6: "grants a `REQUESTED` permit provided the exception is
    `TRIAGED_HUMAN` and the count of `ACTIVE` permits for the zone with
    overlapping closed intervals is below the zone's `max_human_occupancy`
    (`ERR_CAPACITY_EXCEEDED`)."

    Design: Difficulty/resource_temporal_overlap/human_entry_permit_closed_interval_capacity
    """
    _zone, _exception, p1, p2 = _setup_permit_capacity_scenario()
    get_success_data(api_client.grant_human_entry_permit(p1["id"], SAFETY))
    resp = api.grant_human_entry_permit(p2["id"], SAFETY)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    assert resp.status_code == 422
