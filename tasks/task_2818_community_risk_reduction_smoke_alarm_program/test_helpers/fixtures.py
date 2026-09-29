"""Composite setup helpers and pytest fixtures.

The harness restarts the API and empties the store before every single test, so
every helper here builds its preconditions from scratch through the documented
endpoints only. Helpers are plain functions returning the created rows so tests
can vary any step; the pytest fixtures at the bottom cover the arrangements that
recur unchanged.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import CrrApiClient
from .constants import (
    AssessmentBasis,
    CLOCK_EPOCH,
    DeviceType,
    PlacementLocation,
    ReportDecision,
)
from .test_users import (
    ADMIN,
    ANALYST,
    COORDINATOR,
    GRANT_OFFICER_COMPILE_ID,
    GRANT_OFFICER_SUBMIT_ID,
    OFFICER,
    make_crr_technician_headers,
    make_grant_officer_headers,
    make_partner_liaison_headers,
)

# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def pin_clock(api: CrrApiClient, instant: str = CLOCK_EPOCH) -> str:
    """Set the logical program clock and return the instant it now reports."""
    data = get_success_data(api.set_clock(instant, ADMIN))
    return data["current_utc"]


# ---------------------------------------------------------------------------
# Zones and assessments
# ---------------------------------------------------------------------------


def create_zone(api: CrrApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_zone(f.zone_payload(**overrides), ANALYST), 201)


def create_district_with_children(
    api: CrrApiClient,
    child_overrides: Optional[List[Dict[str, Any]]] = None,
    **district_overrides: Any,
) -> Dict[str, Any]:
    """Create a parent zone and nest one child zone per entry in ``child_overrides``."""
    parent = get_success_data(
        api.create_zone(f.district_payload(**district_overrides), ANALYST), 201
    )
    children = []
    for index, overrides in enumerate(child_overrides or []):
        payload = f.zone_payload(parent_zone_id=parent["id"], **overrides)
        payload.setdefault("zone_code", f"Z-CHILD-{index + 1}")
        children.append(get_success_data(api.create_zone(payload, ANALYST), 201))
    return {"parent": parent, "children": children}


def assess_zone(
    api: CrrApiClient,
    zone_id: str,
    expected_zone_version: int,
    basis: str = AssessmentBasis.PROVISIONAL,
) -> Dict[str, Any]:
    payload = f.assessment_payload(expected_zone_version, basis=basis)
    return get_success_data(api.create_assessment(zone_id, payload, ANALYST), 201)


def create_assessed_zone(api: CrrApiClient, **overrides: Any) -> Dict[str, Any]:
    """A leaf zone carrying a PROVISIONAL score, re-read after the write-back."""
    zone = create_zone(api, **overrides)
    assess_zone(api, zone["id"], zone["version"])
    return read_zone(api, zone["id"])


def read_zone(api: CrrApiClient, zone_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_zone(zone_id, ANALYST))


def record_fire_incident(api: CrrApiClient, zone_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_fire_incident(zone_id, f.fire_incident_payload(**overrides), ANALYST),
        201,
    )


# ---------------------------------------------------------------------------
# Households
# ---------------------------------------------------------------------------


def create_household(api: CrrApiClient, zone_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_household(f.household_payload(zone_id, **overrides), COORDINATOR), 201
    )


def read_household(api: CrrApiClient, household_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_household(household_id, COORDINATOR))


# ---------------------------------------------------------------------------
# Crews, routes and visits
# ---------------------------------------------------------------------------


def create_crew(api: CrrApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_crew(f.crew_payload(**overrides), ADMIN), 201)


def create_route(api: CrrApiClient, zone_id: str, crew_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_route(f.route_payload(zone_id, crew_id, **overrides), COORDINATOR), 201
    )


def publish_route(api: CrrApiClient, route_id: str) -> Dict[str, Any]:
    return get_success_data(api.publish_route(route_id, COORDINATOR))


def create_published_route(
    api: CrrApiClient, zone_id: str, crew_id: str, **overrides: Any
) -> Dict[str, Any]:
    route = create_route(api, zone_id, crew_id, **overrides)
    return publish_route(api, route["id"])


def read_route(api: CrrApiClient, route_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_route(route_id, COORDINATOR))


def book_visit(
    api: CrrApiClient, household_id: str, route_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_visit(f.visit_payload(household_id, route_id, **overrides), COORDINATOR),
        201,
    )


def read_visit(api: CrrApiClient, visit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_visit(visit_id, COORDINATOR))


def arrive(
    api: CrrApiClient,
    visit_id: str,
    crew_id: str,
    pre_existing_working_smoke_alarms: int = 0,
    pre_existing_working_co_alarms: int = 0,
) -> Dict[str, Any]:
    payload = f.arrive_payload(
        pre_existing_working_smoke_alarms=pre_existing_working_smoke_alarms,
        pre_existing_working_co_alarms=pre_existing_working_co_alarms,
    )
    return get_success_data(
        api.arrive_visit(visit_id, payload, make_crr_technician_headers(crew_id))
    )


def deliver_education(api: CrrApiClient, visit_id: str, crew_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.record_education(
            visit_id, f.education_payload(**overrides), make_crr_technician_headers(crew_id)
        )
    )


def complete_visit(api: CrrApiClient, visit_id: str, crew_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.complete_visit(
            visit_id, f.complete_payload(**overrides), make_crr_technician_headers(crew_id)
        )
    )


def reserve_installation(
    api: CrrApiClient, visit_id: str, crew_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_installation(
            f.installation_payload(visit_id, **overrides),
            make_crr_technician_headers(crew_id),
        ),
        201,
    )


def read_installation(api: CrrApiClient, installation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_installation(installation_id, OFFICER))


# ---------------------------------------------------------------------------
# Partners, grants and lots
# ---------------------------------------------------------------------------


def create_partner(api: CrrApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_partner(f.partner_payload(**overrides), ADMIN), 201)


def create_grant(api: CrrApiClient, partner_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_grant(f.grant_payload(partner_id, **overrides), OFFICER), 201)


def activate_grant(api: CrrApiClient, grant_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_grant(grant_id, OFFICER))


def create_active_grant(
    api: CrrApiClient, partner_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """A partner with a signed agreement plus one ACTIVE grant."""
    if partner_id is None:
        partner_id = create_partner(api)["id"]
    grant = create_grant(api, partner_id, **overrides)
    activated = activate_grant(api, grant["id"])
    activated["partner_id"] = partner_id
    return activated


def read_grant(api: CrrApiClient, grant_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_grant(grant_id, OFFICER))


def create_lot(api: CrrApiClient, grant_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_device_lot(f.device_lot_payload(grant_id, **overrides), OFFICER), 201
    )


def read_lot(api: CrrApiClient, lot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_device_lot(lot_id, OFFICER))


# ---------------------------------------------------------------------------
# Escape plans, follow-ups and reports
# ---------------------------------------------------------------------------


def create_escape_plan(
    api: CrrApiClient, household_id: str, expected_household_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload = f.escape_plan_payload(household_id, expected_household_version, **overrides)
    return get_success_data(api.create_escape_plan(payload, COORDINATOR), 201)


def issue_escape_plan(api: CrrApiClient, plan_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.issue_escape_plan(plan_id, f.issue_plan_payload(**overrides), COORDINATOR)
    )


def read_escape_plan(api: CrrApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_escape_plan(plan_id, COORDINATOR))


def log_follow_up(api: CrrApiClient, household_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_follow_up(f.follow_up_payload(household_id, **overrides), COORDINATOR), 201
    )


def compile_report(api: CrrApiClient, grant_id: str, **overrides: Any) -> Dict[str, Any]:
    """Compile a DRAFT report as the compiling officer."""
    return get_success_data(
        api.create_grant_report(
            f.grant_report_payload(grant_id, **overrides),
            make_grant_officer_headers(GRANT_OFFICER_COMPILE_ID),
        ),
        201,
    )


def submit_report(api: CrrApiClient, report_id: str, **overrides: Any) -> Dict[str, Any]:
    """Submit as a different officer, satisfying the separation-of-duties rule."""
    return get_success_data(
        api.submit_grant_report(
            report_id,
            f.submit_report_payload(**overrides),
            make_grant_officer_headers(GRANT_OFFICER_SUBMIT_ID),
        )
    )


def decide_report(
    api: CrrApiClient,
    report_id: str,
    partner_id: str,
    decision: str = ReportDecision.ACCEPT,
    reviewer_note: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_grant_report(
            report_id,
            f.decision_payload(decision=decision, reviewer_note=reviewer_note),
            make_partner_liaison_headers(partner_id),
        )
    )


def read_report(api: CrrApiClient, report_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_grant_report(report_id, OFFICER))


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------


def canvass_ready(
    api: CrrApiClient,
    zone_overrides: Optional[Dict[str, Any]] = None,
    crew_overrides: Optional[Dict[str, Any]] = None,
    route_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Clock pinned, one scored leaf zone, one crew and one PUBLISHED route."""
    pin_clock(api)
    zone = create_assessed_zone(api, **(zone_overrides or {}))
    crew = create_crew(api, **(crew_overrides or {}))
    route = create_published_route(api, zone["id"], crew["id"], **(route_overrides or {}))
    return {"zone": zone, "crew": crew, "route": route}


def scheduled_visit(
    api: CrrApiClient,
    zone_overrides: Optional[Dict[str, Any]] = None,
    crew_overrides: Optional[Dict[str, Any]] = None,
    route_overrides: Optional[Dict[str, Any]] = None,
    household_overrides: Optional[Dict[str, Any]] = None,
    visit_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The arrangement above plus one household with one SCHEDULED visit."""
    ctx = canvass_ready(api, zone_overrides, crew_overrides, route_overrides)
    household = create_household(api, ctx["zone"]["id"], **(household_overrides or {}))
    visit = book_visit(api, household["id"], ctx["route"]["id"], **(visit_overrides or {}))
    ctx["household"] = household
    ctx["visit"] = visit
    return ctx


def arrived_visit(
    api: CrrApiClient,
    pre_existing_working_smoke_alarms: int = 0,
    pre_existing_working_co_alarms: int = 0,
    **scenario_overrides: Any,
) -> Dict[str, Any]:
    """A visit whose crew is on site, so the install axis is SURVEYED."""
    ctx = scheduled_visit(api, **scenario_overrides)
    ctx["visit"] = arrive(
        api,
        ctx["visit"]["id"],
        ctx["crew"]["id"],
        pre_existing_working_smoke_alarms=pre_existing_working_smoke_alarms,
        pre_existing_working_co_alarms=pre_existing_working_co_alarms,
    )
    return ctx


def funded_program(
    api: CrrApiClient,
    grant_overrides: Optional[Dict[str, Any]] = None,
    lot_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One partner, one ACTIVE grant and one smoke-alarm lot received against it."""
    partner = create_partner(api)
    grant = create_active_grant(api, partner["id"], **(grant_overrides or {}))
    lot = create_lot(api, grant["id"], **(lot_overrides or {}))
    return {"partner": partner, "grant": grant, "lot": lot}


def funded_arrived_visit(
    api: CrrApiClient,
    pre_existing_working_smoke_alarms: int = 1,
    pre_existing_working_co_alarms: int = 0,
    grant_overrides: Optional[Dict[str, Any]] = None,
    lot_overrides: Optional[Dict[str, Any]] = None,
    **scenario_overrides: Any,
) -> Dict[str, Any]:
    """A SURVEYED visit backed by an ACTIVE grant and a stocked lot."""
    pin_clock(api)
    zone = create_assessed_zone(api, **(scenario_overrides.get("zone_overrides") or {}))
    crew = create_crew(api, **(scenario_overrides.get("crew_overrides") or {}))
    funding = funded_program(api, grant_overrides, lot_overrides)
    household = create_household(
        api, zone["id"], **(scenario_overrides.get("household_overrides") or {})
    )
    route = create_published_route(
        api, zone["id"], crew["id"], **(scenario_overrides.get("route_overrides") or {})
    )
    visit = book_visit(
        api,
        household["id"],
        route["id"],
        **(scenario_overrides.get("visit_overrides") or {}),
    )
    visit = arrive(
        api,
        visit["id"],
        crew["id"],
        pre_existing_working_smoke_alarms=pre_existing_working_smoke_alarms,
        pre_existing_working_co_alarms=pre_existing_working_co_alarms,
    )
    ctx = {
        "zone": zone,
        "crew": crew,
        "household": household,
        "route": route,
        "visit": visit,
    }
    ctx.update(funding)
    return ctx


def reserved_installation(
    api: CrrApiClient, **scenario_overrides: Any
) -> Dict[str, Any]:
    """A SURVEYED visit holding one RESERVED smoke-alarm placement."""
    ctx = funded_arrived_visit(api, **scenario_overrides)
    ctx["installation"] = reserve_installation(
        api,
        ctx["visit"]["id"],
        ctx["crew"]["id"],
        device_lot_id=ctx["lot"]["id"],
        placement_location=PlacementLocation.SLEEPING_AREA,
    )
    return ctx


def committed_installation(api: CrrApiClient, **scenario_overrides: Any) -> Dict[str, Any]:
    """The reservation above, committed by closing the visit out as COMPLETE."""
    ctx = reserved_installation(api, **scenario_overrides)
    deliver_education(api, ctx["visit"]["id"], ctx["crew"]["id"])
    ctx["visit"] = complete_visit(api, ctx["visit"]["id"], ctx["crew"]["id"])
    ctx["installation"] = read_installation(api, ctx["installation"]["id"])
    ctx["lot"] = read_lot(api, ctx["lot"]["id"])
    ctx["grant"] = read_grant(api, ctx["grant"]["id"])
    ctx["household"] = read_household(api, ctx["household"]["id"])
    ctx["zone"] = read_zone(api, ctx["zone"]["id"])
    return ctx


def serviced_household(
    api: CrrApiClient,
    pre_existing_working_smoke_alarms: int = 2,
    **scenario_overrides: Any,
) -> Dict[str, Any]:
    """A household whose visit closed as COMPLETE on pre-existing coverage alone."""
    ctx = arrived_visit(
        api,
        pre_existing_working_smoke_alarms=pre_existing_working_smoke_alarms,
        **scenario_overrides,
    )
    deliver_education(api, ctx["visit"]["id"], ctx["crew"]["id"])
    ctx["visit"] = complete_visit(api, ctx["visit"]["id"], ctx["crew"]["id"])
    ctx["household"] = read_household(api, ctx["household"]["id"])
    ctx["zone"] = read_zone(api, ctx["zone"]["id"])
    return ctx


def serviced_household_with_issued_plan(
    api: CrrApiClient, **scenario_overrides: Any
) -> Dict[str, Any]:
    """A serviced household carrying an ISSUED escape plan."""
    ctx = serviced_household(api, **scenario_overrides)
    plan = create_escape_plan(api, ctx["household"]["id"], ctx["household"]["version"])
    ctx["plan"] = issue_escape_plan(api, plan["id"])
    ctx["household"] = read_household(api, ctx["household"]["id"])
    return ctx


def follow_up_window_open(
    api: CrrApiClient, at_instant: str = "2026-09-05T00:00:00Z", **scenario_overrides: Any
) -> Dict[str, Any]:
    """A serviced household with an ISSUED plan, with the clock moved past day 30."""
    ctx = serviced_household_with_issued_plan(api, **scenario_overrides)
    pin_clock(api, at_instant)
    return ctx


def draft_report(api: CrrApiClient, **scenario_overrides: Any) -> Dict[str, Any]:
    """One committed installation plus a DRAFT report covering its install date."""
    ctx = committed_installation(api, **scenario_overrides)
    ctx["report"] = compile_report(api, ctx["grant"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api() -> CrrApiClient:
    """Client bound to the API under test."""
    return CrrApiClient()


@pytest.fixture
def pinned_clock(api: CrrApiClient) -> str:
    """The logical clock explicitly pinned to the program epoch."""
    return pin_clock(api)


@pytest.fixture
def assessed_zone(api: CrrApiClient, pinned_clock: str) -> Dict[str, Any]:
    """A scored middle-tier leaf zone."""
    return create_assessed_zone(api)


@pytest.fixture
def crew(api: CrrApiClient, pinned_clock: str) -> Dict[str, Any]:
    """An ACTIVE crew certified for every device type."""
    return create_crew(api)


@pytest.fixture
def canvass_context(api: CrrApiClient) -> Dict[str, Any]:
    """Scored zone, crew and PUBLISHED route."""
    return canvass_ready(api)


@pytest.fixture
def scheduled_visit_context(api: CrrApiClient) -> Dict[str, Any]:
    """Scored zone, crew, PUBLISHED route, household and one SCHEDULED visit."""
    return scheduled_visit(api)


@pytest.fixture
def funded_visit_context(api: CrrApiClient) -> Dict[str, Any]:
    """A SURVEYED visit with grant funding and stock available."""
    return funded_arrived_visit(api)


@pytest.fixture
def committed_installation_context(api: CrrApiClient) -> Dict[str, Any]:
    """A closed-out visit whose single installation is INSTALLED."""
    return committed_installation(api)


@pytest.fixture
def serviced_household_context(api: CrrApiClient) -> Dict[str, Any]:
    """A household that has reached VISIT_COMPLETED."""
    return serviced_household(api)


def defer_visit(
    api: CrrApiClient,
    visit_id: str,
    crew_id: str,
    deferral_reason: str = "OCCUPANT_DECLINED_INSTALL",
) -> Dict[str, Any]:
    """Close a visit out as DEFERRED, which skips the placement standard entirely."""
    return get_success_data(
        api.complete_visit(
            visit_id,
            f.deferred_payload(deferral_reason),
            make_crr_technician_headers(crew_id),
        )
    )


def survey_one_unit(
    api: CrrApiClient,
    zone_id: str,
    crew_code: str = "CREW-A1",
    address_line: str = "1 Ash Lane",
    pre_existing_working_smoke_alarms: int = 2,
    **household_overrides: Any,
) -> Dict[str, Any]:
    """Take one household in the zone all the way to a closed-out visit.

    Closing the visit out is what moves the zone's survey counters, which is what
    the validated assessment basis measures its alarm gap from.
    """
    crew = create_crew(api, crew_code=crew_code)
    household = create_household(
        api, zone_id, address_line=address_line, **household_overrides
    )
    route = create_published_route(api, zone_id, crew["id"], planned_slots=4)
    visit = book_visit(api, household["id"], route["id"])
    arrive(
        api,
        visit["id"],
        crew["id"],
        pre_existing_working_smoke_alarms=pre_existing_working_smoke_alarms,
    )
    visit = defer_visit(api, visit["id"], crew["id"])
    return {"crew": crew, "household": household, "route": route, "visit": visit}


def verify_installation(api: CrrApiClient, installation_id: str, crew_id: str) -> Dict[str, Any]:
    """Verify an installed device as a crew other than the one that installed it."""
    return get_success_data(
        api.verify_installation(installation_id, make_crr_technician_headers(crew_id))
    )


def unit_rate_installations_scenario(
    api: CrrApiClient,
    include_co_alarm: bool = True,
    verify: bool = True,
    grant_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One closed-out visit whose devices are funded by a UNIT_RATE grant.

    Two smoke devices and optionally one CO device are placed on a single visit at
    a household that had no working alarms at all, so the visit can close as
    COMPLETE on the newly installed coverage alone. A second crew verifies the
    devices afterwards, which is permitted only because it did not install them.
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    verifier = create_crew(api, crew_code="CREW-B2")
    partner = create_partner(api)
    grant = create_active_grant(api, partner["id"], **(grant_overrides or {}))
    smoke_lot = create_lot(api, grant["id"])
    co_lot = create_lot(api, grant["id"], **{"sku": "CO-A", "device_type": DeviceType.CO_ALARM, "unit_cost_cents": 2990, "received_qty": 5}) if include_co_alarm else None
    household = create_household(
        api,
        zone["id"],
        address_line="8 Cedar Way",
        fuel_burning_appliance=bool(include_co_alarm),
    )
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    visit = book_visit(api, household["id"], route["id"])
    visit = arrive(api, visit["id"], crew["id"])

    installations = [
        reserve_installation(
            api,
            visit["id"],
            crew["id"],
            device_type=DeviceType.SMOKE_10YR,
            placement_location=PlacementLocation.SLEEPING_AREA,
            storey=1,
            device_lot_id=smoke_lot["id"],
        ),
        reserve_installation(
            api,
            visit["id"],
            crew["id"],
            device_type=DeviceType.SMOKE_10YR,
            placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
            storey=1,
            device_lot_id=smoke_lot["id"],
        ),
    ]
    if include_co_alarm:
        installations.append(
            reserve_installation(
                api,
                visit["id"],
                crew["id"],
                device_type=DeviceType.CO_ALARM,
                placement_location=PlacementLocation.LIVING_LEVEL,
                storey=1,
                device_lot_id=co_lot["id"],
            )
        )

    deliver_education(api, visit["id"], crew["id"])
    visit = complete_visit(api, visit["id"], crew["id"])

    if verify:
        for installation in installations:
            verify_installation(api, installation["id"], verifier["id"])

    installations = [read_installation(api, row["id"]) for row in installations]
    return {
        "zone": read_zone(api, zone["id"]),
        "crew": crew,
        "verifier": verifier,
        "partner": partner,
        "grant": read_grant(api, grant["id"]),
        "smoke_lot": read_lot(api, smoke_lot["id"]),
        "co_lot": read_lot(api, co_lot["id"]) if include_co_alarm else None,
        "household": read_household(api, household["id"]),
        "route": route,
        "visit": visit,
        "installations": installations,
    }
