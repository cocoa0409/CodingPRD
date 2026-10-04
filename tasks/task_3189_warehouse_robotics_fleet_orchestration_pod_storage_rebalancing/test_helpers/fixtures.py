"""Composite setup helpers for multi-step warehouse scenarios.

Every fixture builds its preconditions from scratch against a freshly
restarted server using only PRD-declared endpoints. Setup calls use the
lenient get_success_data() validator so failures surface as clear
"Setup failed" errors.

Roles used (all identities are opaque per PRD §2.1):
- FleetAdmin: topology (zones, units, chargers, pods, SKUs, stations),
  clock, shift plans, release promotion.
- FlowController: orders, pick tasks, stow tasks, charging sessions.
- StationOperator: stow confirmation, begin/complete picks.
- FloorSupervisor: exceptions, triage, permit requests.
- SafetyOfficer: permit grant/release, record-validation. The shared
  safety officer id differs from the shared supervisor / engineer ids,
  so segregation of duties passes by default.
- MaintenanceTech: maintenance windows.
- ReleaseEngineer: release authoring/validation loop.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_zone_payload,
    create_drive_unit_payload,
    create_charger_payload,
    create_pod_payload,
    create_sku_payload,
    create_pick_station_payload,
    create_customer_order_payload,
    create_pick_task_payload,
    create_stow_task_payload,
    create_charging_session_payload,
    create_maintenance_window_payload,
    create_floor_exception_payload,
    create_human_entry_permit_payload,
    create_shift_plan_payload,
    create_software_release_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["fleet_admin_headers"]
FLOW = TEST_USERS["flow_controller_headers"]
OPERATOR = TEST_USERS["station_operator_headers"]
SUPERVISOR = TEST_USERS["floor_supervisor_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]
ENGINEER = TEST_USERS["release_engineer_headers"]

CLOCK_0800 = "2026-09-01T08:00:00Z"
DEFAULT_CUTOFF = "2026-09-02T00:00:00Z"


def set_clock(to_iso8601=CLOCK_0800):
    """Advance the logical clock. Returns the response data."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_zone(**overrides):
    return get_success_data(api_client.create_zone(create_zone_payload(**overrides), ADMIN))


def create_drive_unit(zone_id, **overrides):
    return get_success_data(
        api_client.create_drive_unit(create_drive_unit_payload(zone_id, **overrides), ADMIN)
    )


def create_charger(zone_id, **overrides):
    return get_success_data(
        api_client.create_charger(create_charger_payload(zone_id, **overrides), ADMIN)
    )


def create_pod(zone_id, **overrides):
    return get_success_data(
        api_client.create_pod(create_pod_payload(zone_id, **overrides), ADMIN)
    )


def create_sku(**overrides):
    return get_success_data(api_client.create_sku(create_sku_payload(**overrides), ADMIN))


def create_pick_station(zone_id, **overrides):
    return get_success_data(
        api_client.create_pick_station(
            create_pick_station_payload(zone_id, **overrides), ADMIN
        )
    )


def get_station_version(station_id):
    station = get_success_data(api_client.get_pick_station(station_id, FLOW))
    return station["version"]


def get_sku_version(sku_id):
    sku = get_success_data(api_client.get_sku(sku_id, FLOW))
    return sku["version"]


def get_sku(sku_id):
    return get_success_data(api_client.get_sku(sku_id, FLOW))


def get_zone(zone_id):
    return get_success_data(api_client.get_zone(zone_id, ADMIN))


def get_drive_unit(unit_id):
    return get_success_data(api_client.get_drive_unit(unit_id, ADMIN))


def get_pick_task(task_id):
    return get_success_data(api_client.get_pick_task(task_id, FLOW))


def get_order(order_id):
    return get_success_data(api_client.get_customer_order(order_id, FLOW))


def get_station(station_id):
    return get_success_data(api_client.get_pick_station(station_id, FLOW))


def get_pod(pod_id):
    return get_success_data(api_client.get_pod(pod_id, ADMIN))


def create_order_with_line(sku_id, quantity=1, **overrides):
    """Create a customer order with a single line; returns (order, line).

    `quantity` is the ORDER LINE's demanded quantity (PRD 3.3: each OrderLine
    carries "a `quantity` of at least 1"); it must be routed into the line,
    not the order envelope.
    """
    overrides.setdefault("lines", [{"sku_id": sku_id, "quantity": quantity}])
    order = get_success_data(
        api_client.create_customer_order(
            create_customer_order_payload(sku_id, **overrides), FLOW
        )
    )
    lines, _meta = validate_paginated(
        api_client.list_order_lines_of_order(order["id"], FLOW)
    )
    assert len(lines) >= 1, f"order {order['id']} must carry at least one line"
    return order, lines[0]


def stow_units(sku, pod_zone_has_pod=True, quantity=5, sku_version=None):
    """Create a stow task for `quantity` units of sku, place it, and confirm
    it so the units land on some pod. Returns the confirmed StowTask.

    Caller must guarantee at least one eligible pod exists with capacity.
    """
    stow = get_success_data(
        api_client.create_stow_task(create_stow_task_payload(sku["id"], quantity=quantity), FLOW)
    )
    ver = sku_version if sku_version is not None else get_sku_version(sku["id"])
    placed = get_success_data(api_client.place_stow_task(stow["id"], ver, FLOW))
    confirmed = get_success_data(api_client.confirm_stow_task(stow["id"], OPERATOR))
    return confirmed


def create_and_sequence_pick_task(order, line, pod, station, quantity=1):
    """Create a pick task and sequence it into the station queue.
    Returns the QUEUED pick task."""
    task = get_success_data(
        api_client.create_pick_task(
            create_pick_task_payload(
                order["id"], line["id"], pod["id"], station["id"], quantity=quantity
            ),
            FLOW,
        )
    )
    ver = get_station_version(station["id"])
    return get_success_data(api_client.sequence_pick_task(task["id"], ver, FLOW))


def create_and_dispatch_pick_task(order, line, pod, station, quantity=1):
    """Create -> sequence -> dispatch. Returns the DISPATCHED pick task."""
    queued = create_and_sequence_pick_task(order, line, pod, station, quantity)
    return get_success_data(api_client.dispatch_pick_task(queued["id"], FLOW))


def setup_stocked_station(
    quantity=5,
    station_zone=None,
    sku_velocity="LOW",
    pod_capacity=5,
    max_queue=5,
):
    """Zone Z1 with a stocked pod, a pick station (in Z1 unless station_zone
    supplied), and `quantity` units of a SKU stowed onto the pod.

    Returns dict(zone, pod, sku, station, stow).
    """
    set_clock()
    zone = create_zone()
    pod = create_pod(zone["id"], slot_capacity=pod_capacity)
    sku = create_sku(velocity_class=sku_velocity)
    station_zone_id = station_zone["id"] if station_zone else zone["id"]
    station = create_pick_station(station_zone_id, max_queue=max_queue)
    stow = stow_units(sku, quantity=quantity)
    return {
        "zone": zone,
        "pod": pod,
        "sku": sku,
        "station": station,
        "stow": stow,
    }


def setup_dispatched_task(quantity=5):
    """Full happy path to a DISPATCHED pick task:
    zone(s), stocked pod, station, order, task CREATED->QUEUED->DISPATCHED.

    Pod in Z1 at (0,0), station in Z2 at (10,0); one drive unit homed in Z1.
    Returns dict with all entities.
    """
    set_clock()
    z1 = create_zone(zone_code="Z1", grid_x=0, grid_y=0)
    z2 = create_zone(zone_code="Z2", grid_x=10, grid_y=0)
    du = create_drive_unit(z1["id"], unit_code="DU1")
    pod = create_pod(z1["id"], pod_code="P1", slot_capacity=5)
    sku = create_sku(sku_code="SKU1", velocity_class="LOW")
    station = create_pick_station(z2["id"], station_code="ST1", max_queue=5)
    stow_units(sku, quantity=quantity)
    order, line = create_order_with_line(sku["id"], quantity=1)
    task = create_and_dispatch_pick_task(order, line, pod, station)
    return {
        "z1": z1, "z2": z2, "du": du, "pod": pod, "sku": sku,
        "station": station, "order": order, "line": line, "task": task,
    }


def open_charging_session(zone, drive_unit, slot_count=1):
    """Create a charger in zone and open a session for drive_unit.
    Returns (charger, session)."""
    charger = create_charger(zone["id"], slot_count=slot_count)
    session = get_success_data(
        api_client.create_charging_session(
            create_charging_session_payload(charger["id"], drive_unit["id"]), FLOW
        )
    )
    return charger, session


def setup_triaged_human_exception(zone, supervisor_headers=None):
    """Report a BLOCKED_PATH exception in zone and triage it HUMAN.
    Returns the TRIAGED_HUMAN FloorException."""
    exc = get_success_data(
        api_client.create_floor_exception(
            create_floor_exception_payload(zone["id"]),
            supervisor_headers or SUPERVISOR,
        )
    )
    return get_success_data(
        api_client.triage_floor_exception(
            exc["id"], "HUMAN", supervisor_headers or SUPERVISOR
        )
    )


def create_and_grant_permit(
    zone,
    exception,
    starts_at="2026-09-01T08:30:00Z",
    ends_at="2026-09-01T09:30:00Z",
    supervisor_headers=None,
    safety_headers=None,
):
    """Request a HumanEntryPermit and grant it. Returns the ACTIVE permit.

    Segregation of duties: the granting SafetyOfficer's X-User-ID differs
    from the triaging FloorSupervisor's X-User-ID (distinct shared ids).
    """
    permit = get_success_data(
        api_client.create_human_entry_permit(
            create_human_entry_permit_payload(
                zone["id"], exception["id"], starts_at=starts_at, ends_at=ends_at
            ),
            supervisor_headers or SUPERVISOR,
        )
    )
    return get_success_data(
        api_client.grant_human_entry_permit(
            permit["id"], safety_headers or SAFETY
        )
    )


def setup_release_in_status(target_status):
    """Drive a SoftwareRelease to DRAFT / VALIDATING / VALIDATED / FAILED.

    Validation initiation uses the shared ReleaseEngineer id and the
    record-validation uses the shared SafetyOfficer id, so the
    segregation-of-duties check passes (distinct ids).
    Returns the SoftwareRelease dict in the requested status.
    """
    release = get_success_data(
        api_client.create_software_release(create_software_release_payload(), ENGINEER)
    )
    if target_status == "DRAFT":
        return release
    release = get_success_data(
        api_client.validate_software_release(release["id"], ENGINEER)
    )
    if target_status == "VALIDATING":
        return release
    if target_status == "VALIDATED":
        return get_success_data(
            api_client.record_validation(release["id"], {"outcome": "PASS"}, SAFETY)
        )
    if target_status == "FAILED":
        return get_success_data(
            api_client.record_validation(
                release["id"],
                {"outcome": "FAIL", "defect_notes": "vibration sensor regressed"},
                SAFETY,
            )
        )
    if target_status == "FLOOR_LIVE":
        release = get_success_data(
            api_client.record_validation(release["id"], {"outcome": "PASS"}, SAFETY)
        )
        return get_success_data(
            api_client.promote_software_release(release["id"], ADMIN)
        )
    raise ValueError(f"unsupported target_status: {target_status}")


def setup_frozen_zone(max_human_occupancy=1):
    """Zone Z1 whose posture is FROZEN via a granted HumanEntryPermit.

    Steps: clock 08:00 -> zone -> BLOCKED_PATH exception -> triage HUMAN ->
    permit [08:30, 09:30] -> grant (zone FROZEN).
    Returns dict(zone, exception, permit).
    """
    set_clock()
    zone = create_zone(max_human_occupancy=max_human_occupancy)
    exception = setup_triaged_human_exception(zone)
    permit = create_and_grant_permit(zone, exception)
    return {"zone": zone, "exception": exception, "permit": permit}


def setup_maintenance_window(drive_unit, starts_at, ends_at, kind="PREVENTIVE"):
    return get_success_data(
        api_client.create_maintenance_window(
            create_maintenance_window_payload(
                drive_unit["id"], starts_at=starts_at, ends_at=ends_at, kind=kind
            ),
            TECH,
        )
    )
