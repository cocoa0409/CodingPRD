"""Composite fixtures that walk the API to a wanted state.

The harness restarts the server before every test, so each test builds the
world it needs from scratch through the public API only. These helpers do that
walking and return the created resources, the ownership-correct headers, and
the observed versions the test then asserts against.

Organisation:

  Tier 1  atomic builders: clock, facility, operator, event, forecast, TMI,
          flight - one API call each
  Tier 2  gate composites: published forecasts, proposed/published/active TMIs
  Tier 3  program lifecycle: the canonical ACTIVE GDP scenario and its
          terminal variants (completed / cancelled)
  Tier 4  scenario packs: compression, GA accommodation, reroute buckets,
          bulk flight filing for pagination and shift-bound tests
  Tier 5  readers: versioned re-reads and full-page listings

Setup calls use the lenient success reader, so a failure inside a fixture
surfaces as a clear setup failure instead of a confusing assertion error.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    COMMAND_CENTER_HEADERS,
    FLOW_MANAGER_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    make_operator_headers,
)

# The instant the design recipes pin the logical clock to before any windowed
# create; on/after the clock's startup default, so no recipe time is in the
# past relative to a fresh deployment.
RECIPE_CLOCK = "2026-09-15T12:00:00Z"

# Full-page listing size, so a 12-slot program or a 12-flight operator never
# silently truncates to the envelope's default page of 10.
FULL_PAGE = {"limit": 100}


# ═══ Tier 1: atomic builders ═══════════════════════════════════════════════

def set_clock(api: ApiClient, instant: str = RECIPE_CLOCK) -> Dict[str, Any]:
    """Move the logical clock and return what the write reported."""
    return get_success_data(api.set_clock(f.clock_payload(instant), SYSTEM_ADMIN_HEADERS))


def create_facility(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_facility(f.facility_payload(**overrides), SYSTEM_ADMIN_HEADERS))


def create_airport(
    api: ApiClient, ident: str = "KEWR", base_acceptance_rate: int = 30, **overrides: Any
) -> Dict[str, Any]:
    return create_facility(
        api, ident=ident, facility_type="AIRPORT",
        base_acceptance_rate=base_acceptance_rate, **overrides,
    )


def create_sector(
    api: ApiClient, ident: str = "ZDC42", base_acceptance_rate: int = 2, **overrides: Any
) -> Dict[str, Any]:
    return create_facility(
        api, ident=ident, facility_type="EN_ROUTE_SECTOR",
        base_acceptance_rate=base_acceptance_rate, **overrides,
    )


def patch_facility(api: ApiClient, facility_id: str, **fields: Any) -> Dict[str, Any]:
    return get_success_data(
        api.patch_facility(facility_id, f.facility_patch_payload(**fields), SYSTEM_ADMIN_HEADERS)
    )


def create_operator(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_operator(f.operator_payload(**overrides), SYSTEM_ADMIN_HEADERS))


def create_carrier(api: ApiClient, name: str = "Alpha Air", **overrides: Any) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """A SCHEDULED_CARRIER operator plus its ownership-correct headers."""
    operator = create_operator(api, name=name, operator_type="SCHEDULED_CARRIER", **overrides)
    return operator, make_operator_headers(operator["id"])


def create_ga_operator(api: ApiClient, name: str = "Golf Aviation", **overrides: Any) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """A GENERAL_AVIATION operator plus its ownership-correct headers."""
    operator = create_operator(api, name=name, operator_type="GENERAL_AVIATION", **overrides)
    return operator, make_operator_headers(operator["id"])


def create_charter_operator(api: ApiClient, name: str = "Charter One", **overrides: Any) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """An UNSCHEDULED_CHARTER operator plus its ownership-correct headers."""
    operator = create_operator(api, name=name, operator_type="UNSCHEDULED_CHARTER", **overrides)
    return operator, make_operator_headers(operator["id"])


def report_constraint_event(
    api: ApiClient,
    facility_id: str,
    event_type: str = "WEATHER",
    severity: int = 2,
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
    headers: Dict[str, str] = FLOW_MANAGER_HEADERS,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_constraint_event(
            facility_id,
            f.constraint_event_payload(
                event_type=event_type, severity=severity,
                window_start=window_start, window_end=window_end,
            ),
            headers,
        )
    )


def confirm_event(
    api: ApiClient, event_id: str, headers: Dict[str, str] = FLOW_MANAGER_HEADERS
) -> Dict[str, Any]:
    return get_success_data(api.confirm_constraint_event(event_id, headers))


def clear_event(
    api: ApiClient, event_id: str, headers: Dict[str, str] = FLOW_MANAGER_HEADERS
) -> Dict[str, Any]:
    return get_success_data(api.clear_constraint_event(event_id, headers))


def extend_event(
    api: ApiClient,
    event_id: str,
    window_end: str,
    severity: Optional[int] = None,
    headers: Dict[str, str] = FLOW_MANAGER_HEADERS,
) -> Dict[str, Any]:
    return get_success_data(
        api.extend_constraint_event(
            event_id, f.constraint_event_extend_payload(window_end, severity), headers
        )
    )


def report_and_confirm_event(
    api: ApiClient,
    facility_id: str,
    event_type: str = "WEATHER",
    severity: int = 2,
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
) -> Dict[str, Any]:
    """A CONFIRMED constraint event: report, then confirm."""
    event = report_constraint_event(
        api, facility_id, event_type=event_type, severity=severity,
        window_start=window_start, window_end=window_end,
    )
    return confirm_event(api, event["id"])


def create_forecast(
    api: ApiClient,
    facility_id: str,
    variant: str = "PLANNING",
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
    headers: Dict[str, str] = FLOW_MANAGER_HEADERS,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_capacity_forecast(
            facility_id,
            f.capacity_forecast_payload(
                variant=variant, window_start=window_start, window_end=window_end
            ),
            headers,
        )
    )


def publish_forecast(
    api: ApiClient, forecast_id: str, headers: Dict[str, str] = FLOW_MANAGER_HEADERS
) -> Dict[str, Any]:
    return get_success_data(api.publish_capacity_forecast(forecast_id, headers))


def create_published_forecast(
    api: ApiClient,
    facility_id: str,
    variant: str = "PLANNING",
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
) -> Dict[str, Any]:
    """A forecast already in PUBLISHED, eligible as the initiative gate."""
    forecast = create_forecast(
        api, facility_id, variant=variant, window_start=window_start, window_end=window_end
    )
    return publish_forecast(api, forecast["id"])


def propose_tmi(
    api: ApiClient,
    facility_id: str,
    tmi_type: str = "GROUND_DELAY_PROGRAM",
    program_start: Optional[str] = None,
    program_end: Optional[str] = None,
    controlled_rate: Optional[int] = None,
    proposer_headers: Dict[str, str] = FLOW_MANAGER_HEADERS,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_tmi(
            facility_id,
            f.tmi_payload(
                tmi_type=tmi_type, program_start=program_start,
                program_end=program_end, controlled_rate=controlled_rate,
            ),
            proposer_headers,
        )
    )


def propose_gdp(
    api: ApiClient,
    facility_id: str,
    program_start: Optional[str] = None,
    program_end: Optional[str] = None,
    controlled_rate: int = 6,
    proposer_headers: Dict[str, str] = FLOW_MANAGER_HEADERS,
) -> Dict[str, Any]:
    return propose_tmi(
        api, facility_id, tmi_type="GROUND_DELAY_PROGRAM",
        program_start=program_start, program_end=program_end,
        controlled_rate=controlled_rate, proposer_headers=proposer_headers,
    )


def publish_tmi(
    api: ApiClient, tmi_id: str, publisher_headers: Dict[str, str] = COMMAND_CENTER_HEADERS
) -> Dict[str, Any]:
    return get_success_data(api.publish_tmi(tmi_id, publisher_headers))


def activate_tmi(
    api: ApiClient, tmi_id: str, headers: Dict[str, str] = FLOW_MANAGER_HEADERS
) -> Dict[str, Any]:
    return get_success_data(api.activate_tmi(tmi_id, headers))


def cancel_tmi(
    api: ApiClient, tmi_id: str, headers: Dict[str, str] = COMMAND_CENTER_HEADERS
) -> Dict[str, Any]:
    return get_success_data(api.cancel_tmi(tmi_id, headers))


def complete_tmi(
    api: ApiClient, tmi_id: str, headers: Dict[str, str] = COMMAND_CENTER_HEADERS
) -> Dict[str, Any]:
    return get_success_data(api.complete_tmi(tmi_id, headers))


def file_flight(
    api: ApiClient,
    operator: Dict[str, Any],
    facility_id: str,
    designator: str = "AAL1",
    scheduled_arrival: Optional[str] = None,
    origin: str = "KORD",
    estimated_arrival: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """File one flight as its owning operator (identity threading)."""
    operator_headers = headers if headers is not None else make_operator_headers(operator["id"])
    return get_success_data(
        api.create_flight(
            operator["id"],
            f.flight_payload(
                designator=designator, origin=origin,
                arrival_facility_id=facility_id,
                scheduled_arrival=scheduled_arrival,
                estimated_arrival=estimated_arrival,
            ),
            operator_headers,
        )
    )


def file_flights(
    api: ApiClient,
    operator: Dict[str, Any],
    facility_id: str,
    scheduled_times: Sequence[str],
    designator_prefix: str = "AAL",
    origin: str = "KORD",
) -> List[Dict[str, Any]]:
    """File one flight per scheduled time; designators are numbered per prefix."""
    headers = make_operator_headers(operator["id"])
    flights: List[Dict[str, Any]] = []
    for index, hhmm in enumerate(scheduled_times, start=1):
        flights.append(
            file_flight(
                api, operator, facility_id,
                designator=f"{designator_prefix}{index}",
                scheduled_arrival=f.at(hhmm) if len(hhmm) == 5 else hhmm,
                origin=origin, headers=headers,
            )
        )
    return flights


def update_flight(
    api: ApiClient,
    flight: Dict[str, Any],
    new_eta: Optional[str] = None,
    new_ops_status: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Post an OCC-guarded data-exchange update, re-reading the current version
    first so the caller never has to track cascaded version bumps by hand."""
    current = get_success_data(api.get_flight(flight["id"], FLOW_MANAGER_HEADERS))
    operator_headers = (
        headers if headers is not None else make_operator_headers(current["operator_id"])
    )
    return get_success_data(
        api.update_flight(
            flight["id"],
            f.flight_update_payload(
                expected_flight_version=current["version"],
                new_eta=new_eta, new_ops_status=new_ops_status,
            ),
            operator_headers,
        )
    )


def cancel_flight(
    api: ApiClient, flight: Dict[str, Any], headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    operator_headers = (
        headers if headers is not None else make_operator_headers(flight["operator_id"])
    )
    return get_success_data(api.cancel_flight(flight["id"], operator_headers))


# ═══ Tier 2: gate composites ═══════════════════════════════════════════════

def setup_published_tmi(
    api: ApiClient,
    *,
    tmi_type: str = "GROUND_DELAY_PROGRAM",
    controlled_rate: Optional[int] = 6,
    program_start: str = "13:00",
    program_end: str = "15:00",
    base_acceptance_rate: int = 30,
    facility_ident: str = "KEWR",
    proposer_headers: Dict[str, str] = FLOW_MANAGER_HEADERS,
    publisher_headers: Dict[str, str] = COMMAND_CENTER_HEADERS,
    with_forecast: bool = True,
    forecast_variant: str = "PLANNING",
) -> Dict[str, Any]:
    """Facility plus a proposed-and-published TMI (not yet activated).

    GDP and AFP initiatives need the forecast gate, so a PUBLISHED PLANNING
    forecast covering the whole program window is created by default; ground
    stops and reroutes are exempt and skip it.
    """
    set_clock(api)
    facility = create_airport(api, ident=facility_ident, base_acceptance_rate=base_acceptance_rate)
    forecast = None
    if with_forecast and tmi_type in ("GROUND_DELAY_PROGRAM", "AIRSPACE_FLOW_PROGRAM"):
        forecast = create_published_forecast(
            api, facility["id"], variant=forecast_variant,
            window_start=f.at(program_start), window_end=f.at(program_end),
        )
    tmi = propose_tmi(
        api, facility["id"], tmi_type=tmi_type,
        program_start=f.at(program_start), program_end=f.at(program_end),
        controlled_rate=controlled_rate, proposer_headers=proposer_headers,
    )
    tmi = publish_tmi(api, tmi["id"], publisher_headers)
    return {"facility": facility, "forecast": forecast, "tmi": tmi}


def setup_active_tmi(
    api: ApiClient,
    *,
    tmi_type: str = "GROUND_DELAY_PROGRAM",
    controlled_rate: Optional[int] = 6,
    program_start: str = "13:00",
    program_end: str = "15:00",
    base_acceptance_rate: int = 30,
    facility_ident: str = "KEWR",
    with_forecast: bool = True,
) -> Dict[str, Any]:
    """A TMI driven to ACTIVE. For a GDP this runs the slot allocation over
    whatever flights exist at activation; other types flip status only."""
    world = setup_published_tmi(
        api, tmi_type=tmi_type, controlled_rate=controlled_rate,
        program_start=program_start, program_end=program_end,
        base_acceptance_rate=base_acceptance_rate, facility_ident=facility_ident,
        with_forecast=with_forecast,
    )
    world["tmi"] = activate_tmi(api, world["tmi"]["id"])
    return world


# ═══ Tier 3: the canonical ACTIVE ground delay program ═════════════════════

def setup_active_gdp(
    api: ApiClient,
    *,
    base_acceptance_rate: int = 30,
    controlled_rate: int = 6,
    program_start: str = "13:00",
    program_end: str = "15:00",
    carrier_names: Sequence[str] = ("Alpha Air", "Bravo Air"),
    flight_specs: Sequence[Tuple[int, str, str]] = (
        (0, "AAL1", "13:05"),
        (0, "AAL2", "13:10"),
        (0, "AAL3", "13:20"),
        (1, "BAL4", "13:15"),
        (1, "BAL5", "13:26"),
    ),
    facility_ident: str = "KEWR",
    proposer_headers: Dict[str, str] = FLOW_MANAGER_HEADERS,
    publisher_headers: Dict[str, str] = COMMAND_CENTER_HEADERS,
) -> Dict[str, Any]:
    """Clock pinned; airport and carriers registered; PLANNING forecast
    published; GDP proposed and published; flights filed by their owning
    carriers; program activated. Returns every handle a test needs.

    ``flight_specs`` is a list of (carrier_index, designator, "HH:MM") triples;
    the returned ``flights`` list is aligned with it one to one.
    """
    set_clock(api)
    facility = create_airport(api, ident=facility_ident, base_acceptance_rate=base_acceptance_rate)
    operators: List[Dict[str, Any]] = []
    operator_headers: List[Dict[str, str]] = []
    for name in carrier_names:
        operator, headers = create_carrier(api, name)
        operators.append(operator)
        operator_headers.append(headers)
    forecast = create_published_forecast(
        api, facility["id"], window_start=f.at(program_start), window_end=f.at(program_end)
    )
    tmi = propose_gdp(
        api, facility["id"], program_start=f.at(program_start),
        program_end=f.at(program_end), controlled_rate=controlled_rate,
        proposer_headers=proposer_headers,
    )
    tmi = publish_tmi(api, tmi["id"], publisher_headers)
    flights: List[Dict[str, Any]] = []
    for carrier_index, designator, hhmm in flight_specs:
        flights.append(
            file_flight(
                api, operators[carrier_index], facility["id"],
                designator=designator, scheduled_arrival=f.at(hhmm),
                headers=operator_headers[carrier_index],
            )
        )
    tmi = activate_tmi(api, tmi["id"])
    return {
        "facility": facility,
        "forecast": forecast,
        "tmi": tmi,
        "operators": operators,
        "operator_headers": operator_headers,
        "flights": flights,
    }


def setup_completed_gdp(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """The canonical scenario driven through completion (FINAL attribution)."""
    world = setup_active_gdp(api, **kwargs)
    world["tmi"] = complete_tmi(api, world["tmi"]["id"])
    return world


def setup_cancelled_gdp(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """The canonical scenario cancelled from ACTIVE (compensation cascade)."""
    world = setup_active_gdp(api, **kwargs)
    world["tmi"] = cancel_tmi(api, world["tmi"]["id"])
    return world


def create_revision(
    api: ApiClient,
    tmi_id: str,
    *,
    new_controlled_rate: Optional[int] = None,
    new_program_end: Optional[str] = None,
    reason: str = "weather improving",
    headers: Dict[str, str] = FLOW_MANAGER_HEADERS,
) -> Dict[str, Any]:
    """Post an OCC-guarded manual revision, re-reading the TMI version first."""
    current = get_success_data(api.get_tmi(tmi_id, FLOW_MANAGER_HEADERS))
    return get_success_data(
        api.create_tmi_revision(
            tmi_id,
            f.tmi_revision_payload(
                expected_tmi_version=current["version"], reason=reason,
                new_controlled_rate=new_controlled_rate, new_program_end=new_program_end,
            ),
            headers,
        )
    )


def apply_revision(api: ApiClient, tmi_id: str) -> Dict[str, Any]:
    """Activate a REVISING program, applying its pending revision."""
    return activate_tmi(api, tmi_id)


def run_compression(api: ApiClient, tmi_id: str) -> Dict[str, Any]:
    return get_success_data(api.create_compression_run(tmi_id, FLOW_MANAGER_HEADERS))


# ═══ Tier 4: scenario packs ════════════════════════════════════════════════

def setup_compression_scenario(
    api: ApiClient,
    *,
    controlled_rate: int = 12,
    program_start: str = "13:00",
    program_end: str = "14:00",
    flight_specs: Sequence[Tuple[int, str, str]] = (
        (0, "AAL1", "13:02"),
        (0, "AAL2", "13:07"),
        (0, "AAL3", "13:12"),
        (1, "BAL1", "13:17"),
        (1, "BAL2", "13:22"),
    ),
    cancel_flight_index: int = 0,
) -> Dict[str, Any]:
    """An ACTIVE GDP with one holder flight already cancelled, so its slot sits
    RELEASED waiting for compression. Returns the world plus cancelled_flight.
    """
    world = setup_active_gdp(
        api, controlled_rate=controlled_rate,
        program_start=program_start, program_end=program_end,
        flight_specs=flight_specs,
    )
    cancelled = cancel_flight(api, world["flights"][cancel_flight_index])
    world["cancelled_flight"] = cancelled
    return world


def create_ga_request(
    api: ApiClient,
    operator: Dict[str, Any],
    tmi_id: str,
    requested_window_start: Optional[str] = None,
    requested_window_end: Optional[str] = None,
    priority_class: str = "STANDARD",
) -> Dict[str, Any]:
    headers = make_operator_headers(operator["id"])
    return get_success_data(
        api.create_ga_request(
            operator["id"],
            f.ga_request_payload(
                tmi_id=tmi_id,
                requested_window_start=requested_window_start,
                requested_window_end=requested_window_end,
                priority_class=priority_class,
            ),
            headers,
        )
    )


def adjudicate_ga_request(
    api: ApiClient, request_id: str, decision: str = "ACCOMMODATE"
) -> Dict[str, Any]:
    return get_success_data(
        api.adjudicate_ga_request(request_id, f.ga_adjudication_payload(decision), FLOW_MANAGER_HEADERS)
    )


def setup_ga_scenario(
    api: ApiClient,
    *,
    controlled_rate: int = 6,
    program_start: str = "13:00",
    program_end: str = "15:00",
    carrier_flight_specs: Sequence[Tuple[int, str, str]] = ((0, "AAL1", "13:05"),),
    request_window: Tuple[str, str] = ("14:30", "15:00"),
    priority_class: str = "STANDARD",
    num_requests: int = 0,
) -> Dict[str, Any]:
    """An ACTIVE GDP plus a GA operator and (optionally) that many GA requests
    already filed against the program. Adds ga_operator, ga_headers and
    ga_requests to the returned world."""
    world = setup_active_gdp(
        api, controlled_rate=controlled_rate,
        program_start=program_start, program_end=program_end,
        carrier_names=("Alpha Air",), flight_specs=carrier_flight_specs,
    )
    ga_operator, ga_headers = create_ga_operator(api)
    requests: List[Dict[str, Any]] = []
    for _ in range(num_requests):
        requests.append(
            create_ga_request(
                api, ga_operator, world["tmi"]["id"],
                requested_window_start=f.at(request_window[0]),
                requested_window_end=f.at(request_window[1]),
                priority_class=priority_class,
            )
        )
    world["ga_operator"] = ga_operator
    world["ga_headers"] = ga_headers
    world["ga_requests"] = requests
    return world


def setup_reroute_scenario(
    api: ApiClient,
    *,
    sector_base_rate: int = 2,
    sector_ident: str = "ZDC42",
    flight_etas: Sequence[str] = ("13:30", "13:40", "13:50"),
    program_start: str = "13:00",
    program_end: str = "15:00",
    airport_base_rate: int = 30,
) -> Dict[str, Any]:
    """Airport plus en route sector plus an ACTIVE REROUTE initiative and a
    set of UNCONTROLLED flights whose ETAs (== schedules) fall in the given
    times. Reroute initiatives are exempt from the forecast gate."""
    set_clock(api)
    airport = create_airport(api, base_acceptance_rate=airport_base_rate)
    sector = create_sector(api, ident=sector_ident, base_acceptance_rate=sector_base_rate)
    operator, operator_headers = create_carrier(api)
    flights = file_flights(api, operator, airport["id"], list(flight_etas),
                           designator_prefix="AALX")
    tmi = propose_tmi(
        api, airport["id"], tmi_type="REROUTE",
        program_start=f.at(program_start), program_end=f.at(program_end),
    )
    tmi = publish_tmi(api, tmi["id"])
    tmi = activate_tmi(api, tmi["id"])
    return {
        "airport": airport,
        "sector": sector,
        "operator": operator,
        "operator_headers": operator_headers,
        "tmi": tmi,
        "flights": flights,
    }


def assign_reroute(
    api: ApiClient,
    tmi_id: str,
    flight_id: str,
    via_sector_id: str,
    assigned_route: str = "J60",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_reroute_assignment(
            tmi_id,
            f.reroute_assignment_payload(
                flight_id=flight_id, via_sector_id=via_sector_id,
                assigned_route=assigned_route,
            ),
            FLOW_MANAGER_HEADERS,
        )
    )


def fill_reroute_bucket(
    api: ApiClient,
    tmi_id: str,
    sector_id: str,
    flights: Sequence[Dict[str, Any]],
    count: int,
    assigned_route: str = "J60",
) -> List[Dict[str, Any]]:
    """Assign the first ``count`` flights into the sector's hourly bucket."""
    return [
        assign_reroute(api, tmi_id, flight["id"], sector_id, assigned_route)
        for flight in flights[:count]
    ]


def setup_airport_with_confirmed_events(
    api: ApiClient,
    event_specs: Sequence[Tuple[str, int, str, str]],
    *,
    base_acceptance_rate: int = 30,
    facility_ident: str = "KEWR",
) -> Dict[str, Any]:
    """An airport carrying several CONFIRMED events.

    ``event_specs`` is a list of (event_type, severity, "HH:MM", "HH:MM").
    """
    set_clock(api)
    facility = create_airport(api, ident=facility_ident, base_acceptance_rate=base_acceptance_rate)
    events = [
        report_and_confirm_event(
            api, facility["id"], event_type=event_type, severity=severity,
            window_start=f.at(start), window_end=f.at(end),
        )
        for event_type, severity, start, end in event_specs
    ]
    return {"facility": facility, "events": events}


# ═══ Tier 5: readers ═══════════════════════════════════════════════════════

def get_tmi(api: ApiClient, tmi_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_tmi(tmi_id, FLOW_MANAGER_HEADERS))


def get_flight(api: ApiClient, flight_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_flight(flight_id, FLOW_MANAGER_HEADERS))


def get_operator(api: ApiClient, operator_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_operator(operator_id, FLOW_MANAGER_HEADERS))


def get_facility(api: ApiClient, facility_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_facility(facility_id, FLOW_MANAGER_HEADERS))


def list_tmi_slots(
    api: ApiClient, tmi_id: str, params: Optional[Dict] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """All slots of a program in slot_index order (full page by default)."""
    merged = dict(FULL_PAGE)
    if params:
        merged.update(params)
    return validate_paginated(api.list_tmi_slots(tmi_id, FLOW_MANAGER_HEADERS, params=merged))


def list_flight_slots(api: ApiClient, flight_id: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(api.list_flight_slots(flight_id, FLOW_MANAGER_HEADERS))


def list_slot_transactions(
    api: ApiClient, tmi_id: str, params: Optional[Dict] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The program's append-only transaction log, created_at ascending."""
    merged = dict(FULL_PAGE)
    if params:
        merged.update(params)
    return validate_paginated(
        api.list_slot_transactions(tmi_id, FLOW_MANAGER_HEADERS, params=merged)
    )


def list_tmi_ledgers(api: ApiClient, tmi_id: str) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(
        api.list_tmi_delay_ledgers(tmi_id, FLOW_MANAGER_HEADERS)
    )
    return rows


def list_operator_ledgers(api: ApiClient, operator_id: str) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(
        api.list_operator_delay_ledgers(operator_id, FLOW_MANAGER_HEADERS)
    )
    return rows


def list_tmi_revisions(api: ApiClient, tmi_id: str) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(api.list_tmi_revisions(tmi_id, FLOW_MANAGER_HEADERS))
    return rows


def list_compression_runs(api: ApiClient, tmi_id: str) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(api.list_compression_runs(tmi_id, FLOW_MANAGER_HEADERS))
    return rows


def list_tmi_ga_requests(api: ApiClient, tmi_id: str) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(api.list_tmi_ga_requests(tmi_id, FLOW_MANAGER_HEADERS))
    return rows


def list_operator_ga_requests(api: ApiClient, operator_id: str) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(api.list_operator_ga_requests(operator_id, FLOW_MANAGER_HEADERS))
    return rows


def list_flights(
    api: ApiClient, params: Optional[Dict] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(api.list_flights(FLOW_MANAGER_HEADERS, params=params))


def list_facility_forecasts(
    api: ApiClient, facility_id: str, params: Optional[Dict] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(
        api.list_capacity_forecasts(facility_id, FLOW_MANAGER_HEADERS, params=params)
    )


def list_facility_events(
    api: ApiClient, facility_id: str, params: Optional[Dict] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(
        api.list_constraint_events(facility_id, FLOW_MANAGER_HEADERS, params=params)
    )


def list_reroute_assignments(
    api: ApiClient, params: Optional[Dict] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(api.list_reroute_assignments(FLOW_MANAGER_HEADERS, params=params))
