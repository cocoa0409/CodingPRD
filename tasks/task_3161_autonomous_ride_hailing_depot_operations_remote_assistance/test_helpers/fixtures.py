"""Composite setup builders for the fleet interface.

Every builder drives the public API only — there is no database access
anywhere in this suite.  Builders use ``get_success_data`` so a setup step
the PRD allows to answer 200 or 201 is not pinned to one of the two at
each call site.

The harness kills the API server process and re-launches it before every
individual test, so each test starts against an empty database and must
rebuild its world from scratch.  The central builders are:

* ``active_territory_with_depot`` — an ACTIVE territory plus one depot
* ``serve_vehicle`` — register, stage, run one depot service cycle and read
  the vehicle back, the four-call preamble every readiness claim needs
* ``in_service_vehicle`` — the same, plus the return-to-service step
* ``ready_ride_stack`` — territory + depot + IN_SERVICE vehicle + curb +
  curb rule + REQUESTED ride, the preamble most ride workflows share

Identity is opaque for all six roles, so ownership is never threaded
through ``X-User-ID``; the shared role header constants are used directly.
"""

import pytest

from . import constants as c
from . import factories as f
from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .test_users import (
    ASSIST,
    DEPOT,
    FLEET,
    MAPPING,
    PLANNER,
    SAFETY,
)


# ─── pytest fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def client():
    """A client bound to the service under test."""
    return ApiClient()


@pytest.fixture
def api(client):
    """Alias kept so a test can read either name."""
    return client


# ─── Logical clock ────────────────────────────────────────────────────────


def set_clock(client, to=c.BASE_INSTANT):
    """Set the logical clock; the response carries the new instant."""
    return get_success_data(client.set_clock(to, headers=PLANNER))


def read_clock_default(client):
    """Read the clock's startup default through the liveness probe."""
    return get_success_data(client.health(headers=FLEET))


# ─── Single-entity builders ───────────────────────────────────────────────


def create_territory(client, **overrides):
    """Create a territory exactly as specified (posture is never supplied)."""
    resp = client.create_territory(f.create_territory_payload(**overrides), headers=PLANNER)
    return get_success_data(resp, expected_status=201)


def create_active_territory(client, **overrides):
    """Create a territory that satisfies the ACTIVE posture gates."""
    resp = client.create_territory(f.create_active_territory_payload(**overrides), headers=PLANNER)
    return get_success_data(resp, expected_status=201)


def create_depot(client, territory_id, **overrides):
    resp = client.create_depot(territory_id, f.create_depot_payload(**overrides), headers=PLANNER)
    return get_success_data(resp, expected_status=201)


def register_vehicle(client, territory_id, **overrides):
    resp = client.create_vehicle(
        territory_id, f.create_vehicle_payload(**overrides), headers=FLEET
    )
    return get_success_data(resp, expected_status=201)


def stage_vehicle(client, vehicle_id, depot_id):
    resp = client.stage_vehicle(vehicle_id, {"depot_id": depot_id}, headers=FLEET)
    return get_success_data(resp)


def read_vehicle(client, vehicle_id):
    return get_success_data(client.get_vehicle(vehicle_id, headers=FLEET))


def read_depot(client, depot_id):
    return get_success_data(client.get_depot(depot_id, headers=DEPOT))


def read_territory(client, territory_id):
    return get_success_data(client.get_territory(territory_id, headers=FLEET))


def read_ride(client, territory_id, ride_id):
    return get_success_data(
        client.get_territory_ride(territory_id, ride_id, headers=FLEET)
    )


def run_service_cycle(
    client,
    depot_id,
    vehicle_id,
    service_kind=c.KIND_CALIBRATION,
    bay_index=1,
    start_utc=c.BASE_INSTANT,
    duration_seconds=3600,
    complete_payload=None,
):
    """Create a cycle, reserve a bay, schedule, start and complete it.

    Returns the cycle payload from the completion call.
    """
    cycle = get_success_data(
        client.create_cycle(
            depot_id, f.create_cycle_payload(vehicle_id=vehicle_id, service_kind=service_kind),
            headers=DEPOT,
        ),
        expected_status=201,
    )
    slot = get_success_data(
        client.create_bay_slot(
            depot_id,
            f.create_bay_slot_payload(
                service_type=service_kind,
                bay_index=bay_index,
                start_utc=start_utc,
                duration_seconds=duration_seconds,
                vehicle_id=vehicle_id,
                cycle_id=cycle["id"],
            ),
            headers=DEPOT,
        ),
        expected_status=201,
    )
    get_success_data(
        client.schedule_cycle(
            depot_id, cycle["id"], {"bay_slot_id": slot["id"]}, headers=DEPOT
        )
    )
    get_success_data(client.start_cycle(depot_id, cycle["id"], headers=DEPOT))
    payload = dict(complete_payload or {})
    if service_kind == c.KIND_CALIBRATION and "signed_off" not in payload:
        payload["signed_off"] = True
    return get_success_data(
        client.complete_cycle(depot_id, cycle["id"], payload, headers=DEPOT)
    )


def serve_vehicle(
    client,
    depot_id,
    territory_id,
    vin,
    service_kind=c.KIND_CALIBRATION,
    bay_index=1,
    start_utc=c.BASE_INSTANT,
    duration_seconds=3600,
    battery_pct=90,
    cleanliness_score=90,
    software_version=f.DEFAULTS["SOFTWARE_VERSION"],
    target_software_version=f.DEFAULTS["TARGET_SOFTWARE_VERSION"],
    extra=None,
    complete_payload=None,
):
    """Register, stage and service a vehicle; return the refreshed payload.

    The vehicle ends ``AT_DEPOT`` with one completed cycle applied.  With a
    ``CALIBRATION`` cycle it therefore satisfies all four readiness
    predicates and reads ``AVAILABLE``.
    """
    payload = {
        "vin": vin,
        "battery_pct": battery_pct,
        "cleanliness_score": cleanliness_score,
        "software_version": software_version,
        "target_software_version": target_software_version,
    }
    if extra:
        payload.update(extra)
    vehicle = register_vehicle(client, territory_id, **payload)
    stage_vehicle(client, vehicle["id"], depot_id)
    run_service_cycle(
        client,
        depot_id,
        vehicle["id"],
        service_kind=service_kind,
        bay_index=bay_index,
        start_utc=start_utc,
        duration_seconds=duration_seconds,
        complete_payload=complete_payload,
    )
    return read_vehicle(client, vehicle["id"])


def in_service_vehicle(client, depot_id, territory_id, vin, **kwargs):
    """A service-ready vehicle returned to service (status IN_SERVICE)."""
    vehicle = serve_vehicle(client, depot_id, territory_id, vin, **kwargs)
    resp = client.return_vehicle_to_service(vehicle["id"], headers=FLEET)
    return get_success_data(resp)


def create_pickup_location(client, territory_id, **overrides):
    resp = client.create_pickup_location(
        territory_id, f.create_pickup_location_payload(**overrides), headers=MAPPING
    )
    return get_success_data(resp, expected_status=201)


def create_curb_rule(client, territory_id, **overrides):
    resp = client.create_curb_rule(
        territory_id, f.create_curb_rule_payload(**overrides), headers=SAFETY
    )
    return get_success_data(resp, expected_status=201)


def create_area_rule(client, territory_id, route_class, allowed, approve=True, notes=None):
    """Draft a ServiceAreaRule and optionally have it approved."""
    payload = f.create_area_rule_payload(route_class=route_class, allowed=allowed)
    if notes is not None:
        payload["notes"] = notes
    rule = get_success_data(
        client.create_area_rule(territory_id, payload, headers=MAPPING),
        expected_status=201,
    )
    if approve:
        rule = get_success_data(
            client.approve_area_rule(territory_id, rule["id"], headers=SAFETY)
        )
    return rule


def create_ride(client, territory_id, **overrides):
    resp = client.create_ride(
        territory_id, f.create_ride_payload(**overrides), headers=FLEET
    )
    return get_success_data(resp, expected_status=201)


def match_ride(client, territory_id, ride_id, pickup_location_id,
               expected_vehicle_version, route_class=None):
    payload = {
        "pickup_location_id": pickup_location_id,
        "expected_vehicle_version": expected_vehicle_version,
    }
    if route_class is not None:
        payload["route_class"] = route_class
    return client.match_ride(territory_id, ride_id, payload, headers=FLEET)


def create_exclusion_zone(client, territory_id, activate=False, **overrides):
    zone = get_success_data(
        client.create_exclusion_zone(
            territory_id, f.create_exclusion_zone_payload(**overrides), headers=SAFETY
        ),
        expected_status=201,
    )
    if activate:
        zone = get_success_data(
            client.activate_exclusion_zone(territory_id, zone["id"], headers=SAFETY)
        )
    return zone


def activate_zones(client, territory_id, count, route_class=c.ROUTE_FREEWAY,
                   kind="CONSTRUCTION", duration_seconds=86400,
                   start_utc=c.BASE_INSTANT):
    """Schedule and activate ``count`` exclusion zones; return the list."""
    zones = []
    for index in range(count):
        zone = create_exclusion_zone(
            client,
            territory_id,
            activate=True,
            kind=kind,
            route_class=route_class,
            start_utc=start_utc,
            duration_seconds=duration_seconds + index,
        )
        zones.append(zone)
    return zones


def create_wave(client, territory_id, **overrides):
    resp = client.create_wave(
        territory_id, f.create_wave_payload(**overrides), headers=PLANNER
    )
    return get_success_data(resp, expected_status=201)


def create_roadside_team(client, territory_id, team_code, road_class=c.ROUTE_ARTERIAL):
    resp = client.create_roadside_team(
        territory_id, f.create_roadside_team_payload(team_code=team_code, road_class=road_class),
        headers=FLEET,
    )
    return get_success_data(resp, expected_status=201)


def open_roadside_case(client, vehicle_id, road_class=c.ROUTE_ARTERIAL):
    resp = client.open_roadside_case(
        vehicle_id, f.create_roadside_case_payload(road_class=road_class), headers=FLEET
    )
    return get_success_data(resp, expected_status=201)


def dispatch_roadside_case(client, case_id):
    return get_success_data(client.dispatch_roadside_case(case_id, headers=FLEET))


# ─── Tier 1/2: composite stacks ───────────────────────────────────────────


def active_territory_with_depot(client, depot_overrides=None, territory_overrides=None):
    """An ACTIVE territory plus one depot.

    Returns ``{"territory": <ServiceTerritory body>, "depot": <DepotSite body>}``.
    """
    set_clock(client)
    territory = create_active_territory(client, **(territory_overrides or {}))
    depot = create_depot(client, territory["id"], **(depot_overrides or {}))
    return {"territory": territory, "depot": depot}


def ready_ride_stack(client, depot_overrides=None, territory_overrides=None,
                     vin="VIN-0001", curb_access=c.CURB_SAFE,
                     curb_sub_service=c.SUB_SERVICE_STANDARD, curb_allowed=True,
                     idempotency_key="idem-stack-1", rider_name="Rider One",
                     vehicle_overrides=None):
    """Territory + depot + IN_SERVICE vehicle + permitted curb + REQUESTED ride.

    Returns a dict with ``territory``, ``depot``, ``vehicle``, ``pickup_location``,
    ``curb_rule`` and ``ride`` — the shared preamble of every ride workflow.
    """
    stack = active_territory_with_depot(
        client,
        depot_overrides=depot_overrides,
        territory_overrides=territory_overrides,
    )
    territory, depot = stack["territory"], stack["depot"]
    vehicle = in_service_vehicle(
        client, depot["id"], territory["id"], vin, **(vehicle_overrides or {})
    )
    pickup = create_pickup_location(
        client, territory["id"], curb_access=curb_access, curb_segment_code="CURB-1"
    )
    rule = create_curb_rule(
        client,
        territory["id"],
        curb_access=curb_access,
        sub_service_type=curb_sub_service,
        allowed=curb_allowed,
    )
    ride = create_ride(
        client, territory["id"], rider_name=rider_name, idempotency_key=idempotency_key
    )
    return {
        "territory": territory,
        "depot": depot,
        "vehicle": vehicle,
        "pickup_location": pickup,
        "curb_rule": rule,
        "ride": ride,
    }


def bind_demand_signal(client, territory_id, window_code=c.WINDOW_MIDDAY,
                       projected_rides=40, manual_only_rides=10):
    """Publish the demand curve that provisions a territory's ride credit."""
    return get_success_data(
        client.upsert_demand_signal(
            territory_id,
            {
                "window_code": window_code,
                "projected_rides": projected_rides,
                "manual_only_rides": manual_only_rides,
            },
            headers=PLANNER,
        )
    )


def credit_stack(client, projected_rides=50, manual_only_rides=10,
                 vehicle_overrides=None, **kwargs):
    """A ride-ready stack with a demand curve, for the credit literal claims."""
    stack = ready_ride_stack(client, vehicle_overrides=vehicle_overrides, **kwargs)
    stack["demand_signal"] = bind_demand_signal(
        client,
        stack["territory"]["id"],
        window_code=kwargs.get("window_code", c.WINDOW_MIDDAY),
        projected_rides=projected_rides,
        manual_only_rides=manual_only_rides,
    )
    return stack


def matched_ride_stack(client, **kwargs):
    """``ready_ride_stack`` advanced one step: the ride is MATCHED."""
    stack = ready_ride_stack(client, **kwargs)
    resp = match_ride(
        client,
        stack["territory"]["id"],
        stack["ride"]["id"],
        stack["pickup_location"]["id"],
        stack["vehicle"]["version"],
    )
    stack["ride"] = get_success_data(resp)
    stack["matched_vehicle"] = read_vehicle(client, stack["vehicle"]["id"])
    return stack


def stack_with_acknowledged_session(client, reason="STUCK", acknowledge=True, **kwargs):
    """A matched ride escalated to a session, optionally acknowledged."""
    stack = matched_ride_stack(client, **kwargs)
    session = get_success_data(
        client.create_assistance_session(
            stack["territory"]["id"],
            stack["ride"]["id"],
            f.create_assistance_session_payload(reason=reason),
            headers=ASSIST,
        ),
        expected_status=201,
    )
    if acknowledge:
        session = get_success_data(
            client.acknowledge_session(session["id"], headers=ASSIST)
        )
    stack["session"] = session
    stack["matched_vehicle"] = read_vehicle(client, stack["vehicle"]["id"])
    return stack


def run_depot_ops(client, depot_id):
    """Run the depot operations checkpoint once."""
    return get_success_data(client.run_depot_ops(depot_id, headers=DEPOT))


def stack_with_reviewable_incident(client, severity="MINOR",
                                   description="Curb contact, no damage", **kwargs):
    """A matched ride whose acknowledged session carries a FILED report."""
    stack = stack_with_acknowledged_session(client, **kwargs)
    report = get_success_data(
        client.film_incident(
            stack["ride"]["id"],
            {"severity": severity, "description": description},
            headers=SAFETY,
        ),
        expected_status=201,
    )
    stack["incident"] = report
    return stack


def stack_with_unresolved_ride(client, reason="STUCK", **kwargs):
    """A matched ride whose acknowledged session was declared unresolvable.

    The declaration needs an ``attempt_count`` of at least three (PRD 3.5).
    That counter is raised one step at a time by the depot operations
    checkpoint, each time a session has sat ``ACKNOWLEDGED`` across three
    depot operations runs (PRD 3.7).  The session must therefore be timed out
    three times, re-acknowledged between each, before the declaration is
    accepted; the ride is then FAILED and its former vehicle still IN_SERVICE.
    """
    stack = stack_with_acknowledged_session(client, reason=reason, **kwargs)
    depot_id = stack["depot"]["id"]
    session_id = stack["session"]["id"]
    while True:
        session = get_success_data(
            client.get_assistance_session(session_id, headers=ASSIST)
        )
        if session["attempt_count"] >= c.MAX_SESSION_ATTEMPTS:
            break
        for _ in range(c.ACK_TIMEOUT_OPS_RUNS):
            run_depot_ops(client, depot_id)
        get_success_data(client.acknowledge_session(session_id, headers=ASSIST))
    stack["session"] = get_success_data(
        client.escalate_session_unresolved(session_id, headers=ASSIST)
    )
    stack["ride"] = read_ride(client, stack["territory"]["id"], stack["ride"]["id"])
    stack["matched_vehicle"] = read_vehicle(client, stack["vehicle"]["id"])
    return stack


def stack_with_dispatched_roadside_case(client, team_code="T-ARTERIAL-1",
                                        road_class=c.ROUTE_ARTERIAL, extra_vehicles=0,
                                        **kwargs):
    """A roadside team and a case against an in-service vehicle, dispatched.

    The vehicle referenced by ``roadside_case`` is now ROADSIDE and
    roadside-blocked.  ``extra_vehicles`` registers and stages additional
    vehicles (``vehicle_2`` ...) with the same depot so multi-vehicle claims
    can be built on top.
    """
    stack = ready_ride_stack(client, **kwargs)
    territory, depot = stack["territory"], stack["depot"]
    team = create_roadside_team(client, territory["id"], team_code, road_class)
    case = open_roadside_case(client, stack["vehicle"]["id"], road_class)
    case = dispatch_roadside_case(client, case["id"])
    stack["team"] = team
    stack["roadside_case"] = case
    for index in range(extra_vehicles):
        stack[f"vehicle_{index + 2}"] = in_service_vehicle(
            client, depot["id"], territory["id"], f"VIN-EXTRA-{index + 1}"
        )
    return stack


# ─── Tier 4: accumulation / threshold targeting ───────────────────────────


def staged_available_vehicles(client, depot_id, territory_id, count,
                              battery_start=95, vin_prefix="VIN-WAVE"):
    """``count`` service-ready vehicles sitting AT_DEPOT and AVAILABLE.

    Batteries descend by one from ``battery_start`` so the dispatch ordering
    is a predictable battery ranking with no ties.
    """
    vehicles = []
    for index in range(count):
        vehicle = serve_vehicle(
            client,
            depot_id,
            territory_id,
            f"{vin_prefix}-{index + 1}",
            bay_index=(index % 2) + 1,
            battery_pct=battery_start - index,
        )
        vehicles.append(vehicle)
    return vehicles


def occupy_depot_bays(client, depot_id, vehicle_id, positions, service_type=c.KIND_CHARGE,
                      base_bay_index=1, start_utc=c.BASE_INSTANT, duration_seconds=1800):
    """Reserve ``positions`` distinct bays of one service type on a depot.

    Each reservation is a real BaySlot on its own ``bay_index``, so the
    depot's occupancy recomputes from the reservation count alone.
    """
    cycle = get_success_data(
        client.create_cycle(
            depot_id, f.create_cycle_payload(vehicle_id=vehicle_id, service_kind=service_type),
            headers=DEPOT,
        ),
        expected_status=201,
    )
    slots = []
    for offset in range(positions):
        slot = get_success_data(
            client.create_bay_slot(
                depot_id,
                f.create_bay_slot_payload(
                    service_type=service_type,
                    bay_index=base_bay_index + offset,
                    start_utc=start_utc,
                    duration_seconds=duration_seconds,
                    vehicle_id=vehicle_id,
                    cycle_id=cycle["id"],
                ),
                headers=DEPOT,
            ),
            expected_status=201,
        )
        slots.append(slot)
    return cycle, slots