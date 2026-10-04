"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints — the test harness restarts the API server before every test, so no
state carries over. Fixtures use get_success_data() (lenient) internally so
setup failures surface as clear "Setup failed" errors.
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    create_aircraft_payload,
    create_booking_payload,
    create_crew_base_payload,
    create_crew_member_payload,
    create_publication_payload,
    create_route_payload,
    create_season_window_payload,
    create_station_payload,
    create_supplier_offer_payload,
)
from .test_users import TEST_USERS

NP = TEST_USERS["network_planner_headers"]
OC = TEST_USERS["ops_controller_headers"]
CS = TEST_USERS["customer_service_headers"]
FA = TEST_USERS["finance_analyst_headers"]
CR = TEST_USERS["crew_scheduler_headers"]


def set_default_clock():
    """Pin the logical clock to the default instant (PRD §2.4)."""
    resp = api_client.set_clock(DEFAULT_CLOCK_UTC, NP)
    assert resp.status_code == 200, f"Setup failed: set clock -> {resp.text}"


# ---------------------------------------------------------------------------
# Tier 1: primitive creators
# ---------------------------------------------------------------------------

def create_origin_station(iata_code: str = "SCK", **overrides) -> dict:
    payload = create_station_payload(
        iata_code=iata_code, station_kind="ORIGIN_SMALL_CITY", **overrides
    )
    resp = api_client.create_station(payload, NP)
    assert resp.status_code == 201, f"Setup failed: create origin station -> {resp.text}"
    return get_success_data(resp)


def create_destination_station(iata_code: str = "SFB", **overrides) -> dict:
    payload = create_station_payload(
        iata_code=iata_code,
        station_kind="LEISURE_DESTINATION",
        timezone="America/New_York",
        **overrides,
    )
    resp = api_client.create_station(payload, NP)
    assert resp.status_code == 201, f"Setup failed: create destination station -> {resp.text}"
    return get_success_data(resp)


def create_route(origin_station_id: str, destination_station_id: str, **overrides) -> dict:
    payload = create_route_payload(
        origin_station_id=origin_station_id,
        destination_station_id=destination_station_id,
        **overrides,
    )
    resp = api_client.create_route(payload, NP)
    assert resp.status_code == 201, f"Setup failed: create route -> {resp.text}"
    return get_success_data(resp)


def create_window(route_id: str, **overrides) -> dict:
    payload = create_season_window_payload(**overrides)
    resp = api_client.create_season_window(route_id, payload, NP)
    assert resp.status_code == 201, f"Setup failed: create season window -> {resp.text}"
    return get_success_data(resp)


def activate_route(route_id: str) -> dict:
    resp = api_client.activate_route(route_id, NP)
    assert resp.status_code == 200, f"Setup failed: activate route -> {resp.text}"
    return get_success_data(resp)


def create_publication(route_id: str, window: dict, **overrides) -> dict:
    """Publish a schedule against an OPEN window, threading the window's OCC
    version. If the caller has bumped the window since `window` was captured,
    pass window_version=<current> explicitly."""
    payload = create_publication_payload(
        season_window_id=window["id"],
        expected_window_version=overrides.pop(
            "window_version", window.get("version", 1)
        ),
        **overrides,
    )
    resp = api_client.create_publication(route_id, payload, NP)
    assert resp.status_code == 201, f"Setup failed: create publication -> {resp.text}"
    return get_success_data(resp)


def get_fresh_window(route_id: str, window_id: str) -> dict:
    resp = api_client.get_season_window(route_id, window_id, NP)
    assert resp.status_code == 200, f"Setup failed: get window -> {resp.text}"
    return get_success_data(resp)


def create_aircraft(**overrides) -> dict:
    payload = create_aircraft_payload(**overrides)
    resp = api_client.create_aircraft(payload, OC)
    assert resp.status_code == 201, f"Setup failed: create aircraft -> {resp.text}"
    return get_success_data(resp)


def assign_aircraft(flight_id: str, aircraft_id: str) -> dict:
    resp = api_client.assign_aircraft(flight_id, {"aircraft_id": aircraft_id}, OC)
    assert resp.status_code == 200, f"Setup failed: assign aircraft -> {resp.text}"
    return get_success_data(resp)


def list_flights_for_publication(publication_id: str) -> List[dict]:
    resp = api_client.list_flights(OC, params={"publication_id": publication_id})
    assert resp.status_code == 200, f"Setup failed: list flights -> {resp.text}"
    flights = get_success_data(resp)
    # PRD only guarantees created_at-ascending list order; flights generated in
    # the same millisecond share a created_at, so re-order by flight_date to
    # make "first flight" deterministic for fixtures.
    flights.sort(key=lambda f: (f["flight_date"], f["id"]))
    return flights


def get_flight(flight_id: str) -> dict:
    resp = api_client.get_flight(flight_id, OC)
    assert resp.status_code == 200, f"Setup failed: get flight -> {resp.text}"
    return get_success_data(resp)


def create_supplier_offer(destination_station_id: str, **overrides) -> dict:
    payload = create_supplier_offer_payload(
        destination_station_id=destination_station_id, **overrides
    )
    resp = api_client.create_supplier_offer(payload, FA)
    assert resp.status_code == 201, f"Setup failed: create supplier offer -> {resp.text}"
    return get_success_data(resp)


def create_air_only_booking(flight: dict, passenger_count: int = 1) -> dict:
    """Create an AIR_ONLY booking threading the flight's current OCC version."""
    fresh = get_flight(flight["id"])
    payload = create_booking_payload(
        flight_instance_id=fresh["id"],
        passenger_count=passenger_count,
        booking_kind="AIR_ONLY",
        expected_flight_version=fresh["version"],
    )
    resp = api_client.create_booking(payload, CS)
    assert resp.status_code == 201, f"Setup failed: create AIR_ONLY booking -> {resp.text}"
    return get_success_data(resp)


def create_package_booking(flight: dict, hotel_offer_id: str,
                           passenger_count: int = 1,
                           rental_car_offer_id: Optional[str] = None,
                           attraction_offer_id: Optional[str] = None) -> dict:
    """Create a PACKAGE booking threading the flight's current OCC version."""
    fresh = get_flight(flight["id"])
    payload = create_booking_payload(
        flight_instance_id=fresh["id"],
        passenger_count=passenger_count,
        booking_kind="PACKAGE",
        expected_flight_version=fresh["version"],
        hotel_offer_id=hotel_offer_id,
    )
    if rental_car_offer_id is not None:
        payload["rental_car_offer_id"] = rental_car_offer_id
    if attraction_offer_id is not None:
        payload["attraction_offer_id"] = attraction_offer_id
    resp = api_client.create_booking(payload, CS)
    assert resp.status_code == 201, f"Setup failed: create PACKAGE booking -> {resp.text}"
    return get_success_data(resp)


def get_booking(booking_id: str) -> dict:
    resp = api_client.get_booking(booking_id, CS)
    assert resp.status_code == 200, f"Setup failed: get booking -> {resp.text}"
    return get_success_data(resp)


def get_settlement(settlement_id: str) -> dict:
    resp = api_client.get_supplier_settlement(settlement_id, FA)
    assert resp.status_code == 200, f"Setup failed: get settlement -> {resp.text}"
    return get_success_data(resp)


def get_bundle(bundle_id: str) -> dict:
    resp = api_client.get_package_bundle(bundle_id, FA)
    assert resp.status_code == 200, f"Setup failed: get bundle -> {resp.text}"
    return get_success_data(resp)


def get_route(route_id: str) -> dict:
    resp = api_client.get_route(route_id, NP)
    assert resp.status_code == 200, f"Setup failed: get route -> {resp.text}"
    return get_success_data(resp)


def get_publication_flat(publication_id: str) -> dict:
    resp = api_client.get_publication_flat(publication_id, NP)
    assert resp.status_code == 200, f"Setup failed: get publication -> {resp.text}"
    return get_success_data(resp)


def get_window_flat(window_id: str) -> dict:
    resp = api_client.get_season_window_flat(window_id, NP)
    assert resp.status_code == 200, f"Setup failed: get window (flat) -> {resp.text}"
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: station pair + route composites
# ---------------------------------------------------------------------------

def setup_station_pair(origin_iata: str = "SCK", dest_iata: str = "SFB") -> Dict[str, dict]:
    """Origin + destination stations. Returns {"origin": ..., "destination": ...}."""
    return {
        "origin": create_origin_station(iata_code=origin_iata),
        "destination": create_destination_station(iata_code=dest_iata),
    }


def setup_route_with_open_window(**overrides) -> Dict[str, dict]:
    """Stations + route + one OPEN window + route activated (SEASONAL_ACTIVE).

    Window defaults: 2027-03-01..2027-03-31. Overridable via window_start_date /
    window_end_date / route kwargs.
    """
    set_default_clock()
    pair = setup_station_pair(
        origin_iata=overrides.pop("origin_iata", "SCK"),
        dest_iata=overrides.pop("dest_iata", "SFB"),
    )
    route_kwargs = {
        k: overrides.pop(k)
        for k in list(overrides.keys())
        if k in ("base_fare_cents", "weekly_frequency_cap")
    }
    route = create_route(pair["origin"]["id"], pair["destination"]["id"], **route_kwargs)
    window = create_window(route["id"], **overrides)
    route = activate_route(route["id"])
    return {
        "origin": pair["origin"],
        "destination": pair["destination"],
        "route": route,
        "window": window,
    }


# ---------------------------------------------------------------------------
# Tier 3: full pipeline (route + window + publication + flights + aircraft)
# ---------------------------------------------------------------------------

def setup_published_pipeline(
    operating_days_mask: Optional[List[int]] = None,
    first_operating_date: str = "2027-03-01",
    last_operating_date: str = "2027-03-01",
    block_minutes: int = 240,
    seat_capacity: int = 156,
    daily_cap: int = 480,
    peak_cap: int = 720,
    tail_number: str = "N901NV",
    assign_aircraft_to: str = "all",
    weekly_frequency_cap: int = 4,
    **route_window_overrides,
) -> Dict[str, object]:
    """Route (active) + window + publication + generated flights + aircraft.

    Returns a dict with keys: origin, destination, route, window, publication,
    flights (list, creation order = flight_date ascending), aircraft.
    If assign_aircraft_to == "all", every generated flight gets the tail.
    """
    ctx = setup_route_with_open_window(
        weekly_frequency_cap=weekly_frequency_cap, **route_window_overrides
    )
    publication = create_publication(
        ctx["route"]["id"],
        ctx["window"],
        operating_days_mask=operating_days_mask or [1],
        first_operating_date=first_operating_date,
        last_operating_date=last_operating_date,
        block_minutes=block_minutes,
    )
    flights = list_flights_for_publication(publication["id"])
    assert len(flights) >= 1, (
        f"Setup failed: publication generated no flights for mask "
        f"{operating_days_mask} over {first_operating_date}..{last_operating_date}"
    )
    aircraft = create_aircraft(
        tail_number=tail_number,
        seat_capacity=seat_capacity,
        daily_utilization_cap_minutes=daily_cap,
        peak_day_cap_minutes=peak_cap,
    )
    if assign_aircraft_to == "all":
        for flight in flights:
            assign_aircraft(flight["id"], aircraft["id"])
        flights = [get_flight(f["id"]) for f in flights]
    return {
        "origin": ctx["origin"],
        "destination": ctx["destination"],
        "route": ctx["route"],
        "window": ctx["window"],
        "publication": publication,
        "flights": flights,
        "aircraft": aircraft,
    }


# ---------------------------------------------------------------------------
# Tier 4: disruption / rebook / settlement composites
# ---------------------------------------------------------------------------

def setup_stranded_booking_on_first_flight(
    first_date: str = "2027-03-01",
    last_date: str = "2027-03-08",
    reason_code: str = "WEATHER",
    passenger_count: int = 1,
    **pipeline_overrides,
) -> Dict[str, object]:
    """Pipeline with >= 2 Monday flights; one AIR_ONLY booking on the first
    flight; a disruption cancels the first flight -> booking STRANDED.

    Returns pipeline ctx plus "booking", "disruption", "f1", "f2".
    """
    ctx = setup_published_pipeline(
        operating_days_mask=[1],
        first_operating_date=first_date,
        last_operating_date=last_date,
        **pipeline_overrides,
    )
    flights = ctx["flights"]
    assert len(flights) >= 2, "Setup failed: need at least two flights for stranding"
    booking = create_air_only_booking(flights[0], passenger_count=passenger_count)
    resp = api_client.declare_disruption(
        ctx["route"]["id"],
        {"flight_instance_id": flights[0]["id"], "reason_code": reason_code},
        OC,
    )
    assert resp.status_code == 201, f"Setup failed: declare disruption -> {resp.text}"
    disruption = get_success_data(resp)
    ctx.update(
        {
            "booking": get_booking(booking["id"]),
            "disruption": disruption,
            "f1": flights[0],
            "f2": flights[1],
        }
    )
    return ctx


def setup_settlement_with_package_bookings(
    num_bookings: int = 1,
    cancel_booking_indexes: Optional[List[int]] = None,
    settle_supplier_code: str = "HTL-SFB-1",
    net_cost_cents: int = 12000,
    sell_price_cents: int = 20000,
    period_start_date: str = "2027-03-01",
    period_end_date: str = "2027-03-31",
) -> Dict[str, object]:
    """Pipeline + hotel offer + N PACKAGE bookings + PROVISIONAL settlement.

    Returns ctx with: offer, bookings (list), settlement.
    Optionally cancels the bookings at the given indexes (AFTER settlement
    creation when settlement_first is implied by the call order below).
    """
    ctx = setup_published_pipeline()
    offer = create_supplier_offer(
        ctx["destination"]["id"],
        supplier_code=settle_supplier_code,
        component_kind="HOTEL",
        net_cost_cents=net_cost_cents,
        sell_price_cents=sell_price_cents,
    )
    flight = ctx["flights"][0]
    bookings = [
        create_package_booking(flight, offer["id"]) for _ in range(num_bookings)
    ]
    ctx.update({"offer": offer, "bookings": bookings})
    return ctx


def create_provisional_settlement(
    supplier_code: str,
    period_start_date: str = "2027-03-01",
    period_end_date: str = "2027-03-31",
) -> dict:
    resp = api_client.create_supplier_settlement(
        {
            "supplier_code": supplier_code,
            "period_start_date": period_start_date,
            "period_end_date": period_end_date,
        },
        FA,
    )
    assert resp.status_code == 201, f"Setup failed: create settlement -> {resp.text}"
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: crew composites
# ---------------------------------------------------------------------------

def setup_crew_base_with_member(
    base_station_id: str,
    base_code: str = "SCK",
    employee_number: str = "E1001",
    crew_role: str = "CAPTAIN",
) -> Dict[str, dict]:
    """Crew base at a station + one member hired into it."""
    resp = api_client.create_crew_base(
        create_crew_base_payload(base_station_id=base_station_id, base_code=base_code),
        CR,
    )
    assert resp.status_code == 201, f"Setup failed: create crew base -> {resp.text}"
    base = get_success_data(resp)
    resp = api_client.create_crew_member(
        base["id"],
        create_crew_member_payload(
            employee_number=employee_number, crew_role=crew_role
        ),
        CR,
    )
    assert resp.status_code == 201, f"Setup failed: create crew member -> {resp.text}"
    member = get_success_data(resp)
    return {"base": base, "member": member}
