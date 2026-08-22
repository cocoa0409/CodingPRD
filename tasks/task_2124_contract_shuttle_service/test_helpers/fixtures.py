"""Composite setup helpers.

Every test starts against an empty database with the logical clock at its
untouched default, so each helper here builds its preconditions from scratch
using only the endpoints the PRD declares.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    contract_payload,
    credit_memo_payload,
    driver_payload,
    maintenance_order_payload,
    on_demand_request_payload,
    renewal_offer_payload,
    report_payload,
    ridership_count_payload,
    route_payload,
    trip_completion_payload,
    vehicle_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_liaison_headers,
    make_contract_admin_headers,
    make_driver_headers,
)

ADMIN = TEST_USERS["contract_admin_headers"]
LIAISON = TEST_USERS["client_liaison_headers"]
PLANNER = TEST_USERS["ops_planner_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]

DEFAULT_CLOCK = TEST_DEFAULTS["CLOCK"]
DEFAULT_SERVICE_DATE = TEST_DEFAULTS["SERVICE_DATE"]


# ─── Primitive setup steps ────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_contract(**overrides) -> dict:
    return get_success_data(api_client.create_contract(contract_payload(**overrides), ADMIN))


def create_active_contract(**overrides) -> dict:
    contract = create_contract(**overrides)
    return get_success_data(api_client.activate_contract(contract["id"], ADMIN))


def get_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_contract(contract_id, ADMIN))


def create_route(contract_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_route(route_payload(contract_id, **overrides), PLANNER)
    )


def publish_route(route_id: str, service_date: str = DEFAULT_SERVICE_DATE) -> dict:
    return get_success_data(
        api_client.publish_route(route_id, {"service_date": service_date}, PLANNER)
    )


def republish_route(route_id: str, headway_minutes: int, expected_route_version: int,
                    service_date: str = DEFAULT_SERVICE_DATE) -> dict:
    return get_success_data(
        api_client.republish_route(
            route_id,
            {
                "service_date": service_date,
                "headway_minutes": headway_minutes,
                "expected_route_version": expected_route_version,
            },
            PLANNER,
        )
    )


def get_route(route_id: str) -> dict:
    return get_success_data(api_client.get_route(route_id, PLANNER))


def create_vehicle(**overrides) -> dict:
    return get_success_data(api_client.create_vehicle(vehicle_payload(**overrides), FLEET))


def get_vehicle(vehicle_id: str) -> dict:
    return get_success_data(api_client.get_vehicle(vehicle_id, FLEET))


def brand_vehicle(vehicle_id: str, branding_contract_id) -> dict:
    return get_success_data(
        api_client.brand_vehicle(
            vehicle_id, {"branding_contract_id": branding_contract_id}, FLEET
        )
    )


def create_driver(**overrides) -> dict:
    return get_success_data(api_client.create_driver(driver_payload(**overrides), PLANNER))


def get_driver(driver_id: str) -> dict:
    return get_success_data(api_client.get_driver(driver_id, PLANNER))


def list_trips(**params) -> list:
    return get_success_data(api_client.list_trips(PLANNER, params=params))


def get_trip(trip_id: str) -> dict:
    return get_success_data(api_client.get_trip(trip_id, PLANNER))


def trips_of_route(route_id: str, service_date: str = DEFAULT_SERVICE_DATE) -> list:
    return list_trips(route_id=route_id, service_date=service_date)


def assign_trip(trip_id: str, vehicle_id: str, driver_id: str) -> dict:
    return get_success_data(
        api_client.assign_trip(
            trip_id, {"vehicle_id": vehicle_id, "driver_id": driver_id}, PLANNER
        )
    )


def unassign_trip(trip_id: str) -> dict:
    return get_success_data(api_client.unassign_trip(trip_id, PLANNER))


def start_trip(trip_id: str, driver_id: str, actual_departure_min: int) -> dict:
    return get_success_data(
        api_client.start_trip(
            trip_id,
            {"actual_departure_min": actual_departure_min},
            make_driver_headers(driver_id),
        )
    )


def complete_trip(trip_id: str, driver_id: str, actual_completion_min: int,
                  boarded: int = 5, alighted: int = 5, ada_boardings: int = 0) -> dict:
    return get_success_data(
        api_client.complete_trip(
            trip_id,
            trip_completion_payload(
                actual_completion_min,
                boarded=boarded,
                alighted=alighted,
                ada_boardings=ada_boardings,
            ),
            make_driver_headers(driver_id),
        )
    )


def mark_trip_missed(trip_id: str, reason: str) -> dict:
    return get_success_data(api_client.mark_trip_missed(trip_id, {"reason": reason}, PLANNER))


def append_ridership_count(trip_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_ridership_count(ridership_count_payload(trip_id, **overrides), PLANNER)
    )


def create_on_demand_request(contract_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_on_demand_request(
            on_demand_request_payload(contract_id, **overrides), LIAISON
        )
    )


def match_on_demand_request(request_id: str, trip_id: str = None) -> dict:
    payload = {} if trip_id is None else {"trip_id": trip_id}
    return get_success_data(api_client.match_on_demand_request(request_id, payload, PLANNER))


def serve_on_demand_request(request_id: str, driver_id: str, actual_pickup_min: int) -> dict:
    return get_success_data(
        api_client.serve_on_demand_request(
            request_id,
            {"actual_pickup_min": actual_pickup_min},
            make_driver_headers(driver_id),
        )
    )


def get_on_demand_request(request_id: str) -> dict:
    return get_success_data(api_client.get_on_demand_request(request_id, LIAISON))


def create_maintenance_order(vehicle_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_maintenance_order(
            maintenance_order_payload(vehicle_id, **overrides), FLEET
        )
    )


def close_maintenance_order(order_id: str, outcome: str) -> dict:
    return get_success_data(
        api_client.close_maintenance_order(order_id, {"outcome": outcome}, FLEET)
    )


def create_report(contract_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_report(report_payload(contract_id, **overrides), LIAISON)
    )


def submit_report(report_id: str, submitter_user_id: str = "liaison-submit") -> dict:
    return get_success_data(
        api_client.submit_report(report_id, make_client_liaison_headers(submitter_user_id))
    )


def approve_report(report_id: str, approver_user_id: str = "admin-approve") -> dict:
    return get_success_data(
        api_client.approve_report(report_id, make_contract_admin_headers(approver_user_id))
    )


def dispute_report(report_id: str, dispute_reason: str = "boarding counts under review") -> dict:
    return get_success_data(
        api_client.dispute_report(report_id, {"dispute_reason": dispute_reason}, LIAISON)
    )


def get_report(report_id: str) -> dict:
    return get_success_data(api_client.get_report(report_id, ADMIN))


def create_credit_memo(contract_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_credit_memo(credit_memo_payload(contract_id, **overrides), LIAISON)
    )


def void_credit_memo(memo_id: str, voided_reason: str = "raised in error") -> dict:
    return get_success_data(
        api_client.void_credit_memo(memo_id, {"voided_reason": voided_reason}, ADMIN)
    )


def list_credit_memos(**params) -> list:
    return get_success_data(api_client.list_credit_memos(ADMIN, params=params))


def get_credit_memo(memo_id: str) -> dict:
    return get_success_data(api_client.get_credit_memo(memo_id, ADMIN))


def create_renewal_offer(contract_id: str, expected_contract_version: int = None,
                         **overrides) -> dict:
    if expected_contract_version is None:
        expected_contract_version = get_contract(contract_id)["version"]
    return get_success_data(
        api_client.create_renewal_offer(
            renewal_offer_payload(contract_id, expected_contract_version, **overrides), ADMIN
        )
    )


def counter_renewal_offer(offer_id: str, counter_rate_cents_per_service_hour: int) -> dict:
    return get_success_data(
        api_client.counter_renewal_offer(
            offer_id,
            {"counter_rate_cents_per_service_hour": counter_rate_cents_per_service_hour},
            LIAISON,
        )
    )


def respond_renewal_offer(offer_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.respond_renewal_offer(offer_id, {"decision": decision}, ADMIN)
    )


def get_renewal_offer(offer_id: str) -> dict:
    return get_success_data(api_client.get_renewal_offer(offer_id, ADMIN))


# ─── Tier 1/2: contract + route + generated trips ─────────────────────────────

def setup_published_route(clock: str = DEFAULT_CLOCK,
                          service_date: str = DEFAULT_SERVICE_DATE,
                          contract_overrides: dict = None,
                          route_overrides: dict = None) -> dict:
    """Clock set, contract ACTIVE, one route PUBLISHED for `service_date`.

    Returns {"contract", "route", "trips"} where `trips` is the generated day's
    board in departure order.
    """
    set_clock(clock)
    contract = create_active_contract(**(contract_overrides or {}))
    route = create_route(contract["id"], **(route_overrides or {}))
    route = publish_route(route["id"], service_date)
    trips = trips_of_route(route["id"], service_date)
    return {"contract": contract, "route": route, "trips": trips}


def add_single_departure_route(contract_id: str, departure_min: int,
                               loop_minutes: int = TEST_DEFAULTS["LOOP_MINUTES"],
                               service_date: str = DEFAULT_SERVICE_DATE,
                               name: str = None,
                               **route_overrides) -> dict:
    """A route whose window opens and closes on the same minute, so publishing it
    generates exactly one trip. Returns {"route", "trip"}."""
    overrides = {
        "loop_minutes": loop_minutes,
        "headway_minutes": route_overrides.pop("headway_minutes", 30),
        "service_window_start_min": departure_min,
        "service_window_end_min": departure_min,
        "demand_forecast_pax_per_hour": route_overrides.pop("demand_forecast_pax_per_hour", 0),
    }
    if name:
        overrides["name"] = name
    overrides.update(route_overrides)
    route = create_route(contract_id, **overrides)
    route = publish_route(route["id"], service_date)
    trips = trips_of_route(route["id"], service_date)
    return {"route": route, "trip": trips[0]}


def setup_single_trip_scenario(clock: str = DEFAULT_CLOCK,
                               service_date: str = DEFAULT_SERVICE_DATE,
                               departure_min: int = 420,
                               loop_minutes: int = TEST_DEFAULTS["LOOP_MINUTES"],
                               contract_overrides: dict = None,
                               vehicle_overrides: dict = None,
                               driver_overrides: dict = None) -> dict:
    """Contract ACTIVE, one PUBLISHED single-departure route, one vehicle and one
    driver standing by. Returns {"contract", "route", "trip", "vehicle", "driver"}."""
    set_clock(clock)
    contract = create_active_contract(**(contract_overrides or {}))
    vehicle = create_vehicle(**(vehicle_overrides or {}))
    driver = create_driver(**(driver_overrides or {}))
    built = add_single_departure_route(
        contract["id"], departure_min, loop_minutes=loop_minutes, service_date=service_date
    )
    return {
        "contract": contract,
        "route": built["route"],
        "trip": built["trip"],
        "vehicle": vehicle,
        "driver": driver,
    }


def setup_assigned_trip(**kwargs) -> dict:
    """As `setup_single_trip_scenario`, with the trip already ASSIGNED."""
    scenario = setup_single_trip_scenario(**kwargs)
    scenario["trip"] = assign_trip(
        scenario["trip"]["id"], scenario["vehicle"]["id"], scenario["driver"]["id"]
    )
    return scenario


def setup_in_service_trip(actual_departure_min: int = 423, **kwargs) -> dict:
    """As `setup_assigned_trip`, with the trip started."""
    scenario = setup_assigned_trip(**kwargs)
    scenario["trip"] = start_trip(
        scenario["trip"]["id"], scenario["driver"]["id"], actual_departure_min
    )
    return scenario


def setup_completed_trip(actual_departure_min: int = 423,
                         actual_completion_min: int = 470,
                         boarded: int = 5, alighted: int = 5, ada_boardings: int = 0,
                         **kwargs) -> dict:
    """As `setup_in_service_trip`, with the trip completed and its driver tally appended."""
    scenario = setup_in_service_trip(actual_departure_min=actual_departure_min, **kwargs)
    scenario["trip"] = complete_trip(
        scenario["trip"]["id"], scenario["driver"]["id"], actual_completion_min,
        boarded=boarded, alighted=alighted, ada_boardings=ada_boardings,
    )
    return scenario


def setup_missed_trip_with_memo(clock: str = DEFAULT_CLOCK,
                                service_date: str = DEFAULT_SERVICE_DATE,
                                contract_overrides: dict = None) -> dict:
    """Contract ACTIVE, one SCHEDULED trip declared MISSED for OPERATOR_FAULT, so
    a MISSED_TRIP memo is minted. Returns {"contract", "route", "trip", "memo"}."""
    set_clock(clock)
    contract = create_active_contract(**(contract_overrides or {}))
    built = add_single_departure_route(contract["id"], 420, service_date=service_date)
    trip = mark_trip_missed(built["trip"]["id"], "OPERATOR_FAULT")
    memos = list_credit_memos(trip_id=trip["id"])
    return {
        "contract": contract,
        "route": built["route"],
        "trip": trip,
        "memo": memos[0] if memos else None,
    }


# ─── Tier 3: on-demand riders ─────────────────────────────────────────────────

def setup_matched_on_demand_request(clock: str = DEFAULT_CLOCK,
                                    service_date: str = DEFAULT_SERVICE_DATE,
                                    requested_pickup_min: int = 425,
                                    party_size: int = 2,
                                    requires_ada: bool = False,
                                    trip_index: int = 1,
                                    vehicle_overrides: dict = None,
                                    driver_overrides: dict = None,
                                    contract_overrides: dict = None,
                                    route_overrides: dict = None) -> dict:
    """A PUBLISHED route whose trip at `trip_index` is ASSIGNED, plus one
    on-demand request MATCHED onto that trip.

    Returns {"contract", "route", "trips", "trip", "vehicle", "driver", "request"}.
    """
    base = setup_published_route(
        clock=clock, service_date=service_date,
        contract_overrides=contract_overrides, route_overrides=route_overrides,
    )
    vehicle = create_vehicle(**(vehicle_overrides or {}))
    driver = create_driver(**(driver_overrides or {}))
    trip = base["trips"][trip_index]
    trip = assign_trip(trip["id"], vehicle["id"], driver["id"])
    request = create_on_demand_request(
        base["contract"]["id"],
        service_date=service_date,
        requested_pickup_min=requested_pickup_min,
        party_size=party_size,
        requires_ada=requires_ada,
    )
    request = match_on_demand_request(request["id"], trip["id"])
    return {
        "contract": base["contract"],
        "route": base["route"],
        "trips": base["trips"],
        "trip": trip,
        "vehicle": vehicle,
        "driver": driver,
        "request": request,
    }


# ─── Tier 4: settlement scenarios ─────────────────────────────────────────────

def setup_four_trip_settlement_scenario() -> dict:
    """The dataset the two settlement variants disagree over.

    A four-trip board on 2026-09-02 at loop 48 / headway 12 over the window
    420..456: trip 1 completed on time (departed 423, completed 470), trip 2
    completed late (departed 439, completed 489), trip 3 declared MISSED for
    OPERATOR_FAULT, trip 4 left SCHEDULED. One DRAFT report covers the month.

    Returns {"contract", "route", "trips", "report", "vehicles", "drivers"}.
    """
    base = setup_published_route(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        route_overrides={
            "name": "Airport Loop",
            "loop_minutes": 48,
            "headway_minutes": 12,
            "service_window_start_min": 420,
            "service_window_end_min": 456,
            "demand_forecast_pax_per_hour": 180,
            "reference_seat_capacity": 20,
        },
    )
    trips = base["trips"]
    vehicle_a = create_vehicle(is_ada_accessible=True, odometer_km=120_000)
    vehicle_b = create_vehicle(is_ada_accessible=False, odometer_km=90_000)
    driver_a = create_driver(full_name="Dana Ruiz", ada_certified=True)
    driver_b = create_driver(full_name="Sam Ito", ada_certified=False)

    assign_trip(trips[0]["id"], vehicle_a["id"], driver_a["id"])
    assign_trip(trips[1]["id"], vehicle_b["id"], driver_b["id"])
    start_trip(trips[0]["id"], driver_a["id"], 423)
    complete_trip(trips[0]["id"], driver_a["id"], 470, boarded=14, alighted=14, ada_boardings=2)
    start_trip(trips[1]["id"], driver_b["id"], 439)
    complete_trip(trips[1]["id"], driver_b["id"], 489, boarded=9, alighted=9, ada_boardings=0)
    mark_trip_missed(trips[2]["id"], "OPERATOR_FAULT")

    report = create_report(
        base["contract"]["id"],
        period_start_date="2026-09-01",
        period_end_date="2026-09-30",
    )
    return {
        "contract": base["contract"],
        "route": base["route"],
        "trips": trips,
        "report": report,
        "vehicles": [vehicle_a, vehicle_b],
        "drivers": [driver_a, driver_b],
    }


def setup_fifty_minute_schedule_report() -> dict:
    """Three untouched 50-minute trips inside one reporting period, the dataset
    that separates sum-then-round from round-then-sum.

    Returns {"contract", "route", "trips", "report"}.
    """
    base = setup_published_route(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "Rounding Test Hotel"},
        route_overrides={
            "name": "Fifty Minute Loop",
            "loop_minutes": 50,
            "headway_minutes": 60,
            "service_window_start_min": 420,
            "service_window_end_min": 540,
            "demand_forecast_pax_per_hour": 0,
            "reference_seat_capacity": 20,
        },
    )
    report = create_report(
        base["contract"]["id"],
        period_start_date="2026-09-01",
        period_end_date="2026-09-30",
    )
    return {**base, "report": report}


def setup_on_time_grace_scenario() -> dict:
    """Two trips on 2026-09-02 at 420 and 432, each with its own bus and driver,
    plus a DRAFT report for the month.

    Returns {"contract", "route", "trips", "report", "vehicles", "drivers"}.
    """
    base = setup_published_route(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "Grace Boundary Hotel"},
        route_overrides={
            "name": "Grace Loop",
            "loop_minutes": 48,
            "headway_minutes": 12,
            "service_window_start_min": 420,
            "service_window_end_min": 432,
            "demand_forecast_pax_per_hour": 0,
            "reference_seat_capacity": 20,
        },
    )
    trips = base["trips"]
    vehicle_a = create_vehicle()
    vehicle_b = create_vehicle()
    driver_a = create_driver(full_name="Lena Ford")
    driver_b = create_driver(full_name="Marc Bell")
    assign_trip(trips[0]["id"], vehicle_a["id"], driver_a["id"])
    assign_trip(trips[1]["id"], vehicle_b["id"], driver_b["id"])
    report = create_report(
        base["contract"]["id"],
        period_start_date="2026-09-01",
        period_end_date="2026-09-30",
    )
    return {
        "contract": base["contract"],
        "route": base["route"],
        "trips": trips,
        "report": report,
        "vehicles": [vehicle_a, vehicle_b],
        "drivers": [driver_a, driver_b],
    }


def setup_empty_period_report() -> dict:
    """An ACTIVE contract with no routes, no trips and no memos, plus one DRAFT
    report for the month. Returns {"contract", "report"}."""
    set_clock("2026-09-01T06:00:00Z")
    contract = create_active_contract(client_name="Empty Period Corp", site_type="CORPORATE")
    report = create_report(
        contract["id"], period_start_date="2026-09-01", period_end_date="2026-09-30"
    )
    return {"contract": contract, "report": report}


def setup_approved_report_for_renewal() -> dict:
    """One completed trip that departed ten minutes late, settled through an
    APPROVED report, with the clock then moved inside the renewal window.

    Returns {"contract", "route", "trip", "report", "vehicle", "driver"}.
    """
    scenario = setup_completed_trip(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        actual_departure_min=430,
        actual_completion_min=478,
        boarded=40, alighted=40, ada_boardings=0,
        contract_overrides={"client_name": "Escalation Test Corp", "site_type": "CORPORATE"},
    )
    report = create_report(
        scenario["contract"]["id"],
        period_start_date="2026-09-01",
        period_end_date="2026-09-30",
    )
    submit_report(report["id"], "liaison-3")
    report = approve_report(report["id"], "admin-3")
    set_clock(TEST_DEFAULTS["RENEWAL_CLOCK"])
    return {**scenario, "report": report}


# ─── Tier 5: renewal negotiation ──────────────────────────────────────────────

def setup_renewal_pending_contract(clock: str = TEST_DEFAULTS["RENEWAL_CLOCK"],
                                   proposed_term_months: int = 12,
                                   contract_overrides: dict = None) -> dict:
    """Clock inside the renewal window, contract ACTIVE, one OPEN offer created.

    Returns {"contract", "offer", "activated_version"}.
    """
    set_clock(clock)
    contract = create_active_contract(**(contract_overrides or {}))
    offer = create_renewal_offer(
        contract["id"], contract["version"], proposed_term_months=proposed_term_months
    )
    return {"contract": contract, "offer": offer, "activated_version": contract["version"]}


def setup_countered_offer(counter_rate_cents_per_service_hour: int = 9_100,
                          **kwargs) -> dict:
    """As `setup_renewal_pending_contract`, with the offer already COUNTERED."""
    scenario = setup_renewal_pending_contract(**kwargs)
    scenario["offer"] = counter_renewal_offer(
        scenario["offer"]["id"], counter_rate_cents_per_service_hour
    )
    return scenario


# ─── Tier 5: maintenance displacement ─────────────────────────────────────────

def setup_maintenance_displacement_scenario() -> dict:
    """An ADA bus and certified driver on the first trip of a route sized for
    eight vehicles, with an ADA on-demand rider matched onto that trip, ready for
    a same-day shop order to displace it.

    Returns {"contract", "route", "trips", "trip", "vehicle", "driver", "request"}.
    """
    base = setup_published_route(
        clock="2026-09-02T05:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "Cascade Hotel"},
        route_overrides={
            "name": "Cascade Loop",
            "loop_minutes": 48,
            "headway_minutes": 12,
            "service_window_start_min": 420,
            "service_window_end_min": 456,
            "demand_forecast_pax_per_hour": 180,
            "reference_seat_capacity": 20,
        },
    )
    vehicle = create_vehicle(is_ada_accessible=True, odometer_km=30_000)
    driver = create_driver(full_name="Priya Raman", ada_certified=True)
    trip = assign_trip(base["trips"][0]["id"], vehicle["id"], driver["id"])
    request = create_on_demand_request(
        base["contract"]["id"],
        service_date="2026-09-02",
        requested_pickup_min=420,
        party_size=2,
        requires_ada=True,
    )
    request = match_on_demand_request(request["id"])
    return {
        "contract": base["contract"],
        "route": base["route"],
        "trips": base["trips"],
        "trip": trip,
        "vehicle": vehicle,
        "driver": driver,
        "request": request,
    }


def setup_degraded_route_scenario() -> dict:
    """The maintenance displacement cascade run to completion, leaving the route
    DEGRADED and one PENDING rider behind.

    Returns {"contract", "route", "trip", "vehicle", "driver", "request", "order"}.
    """
    base = setup_published_route(
        clock="2026-09-02T05:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "Degraded Hotel"},
        route_overrides={
            "name": "Degraded Loop",
            "loop_minutes": 48,
            "headway_minutes": 12,
            "service_window_start_min": 420,
            "service_window_end_min": 456,
            "demand_forecast_pax_per_hour": 180,
            "reference_seat_capacity": 20,
        },
    )
    vehicle = create_vehicle(odometer_km=900)
    driver = create_driver(full_name="Degraded Driver")
    trip = assign_trip(base["trips"][0]["id"], vehicle["id"], driver["id"])
    request = create_on_demand_request(
        base["contract"]["id"],
        service_date="2026-09-02",
        requested_pickup_min=420,
        party_size=1,
        requires_ada=False,
    )
    order = create_maintenance_order(
        vehicle["id"], kind="CORRECTIVE", service_date="2026-09-02",
        window_start_min=400, window_end_min=500,
    )
    return {
        "contract": base["contract"],
        "route": base["route"],
        "trip": trip,
        "vehicle": vehicle,
        "driver": driver,
        "request": request,
        "order": order,
    }


# ─── Tier 5: interval-geometry scenarios ──────────────────────────────────────

def setup_layover_gap_scenario() -> dict:
    """One bus and driver already on a 420..468 trip, plus two candidate trips
    departing at 479 (an eleven-minute gap) and 480 (exactly twelve).

    Returns {"contract", "vehicle", "driver", "trip_420", "trip_479", "trip_480"}.
    """
    set_clock("2026-09-01T06:00:00Z")
    contract = create_active_contract(client_name="Layover Hotel")
    vehicle = create_vehicle(odometer_km=3_000)
    driver = create_driver(full_name="Tomas Reyes")
    first = add_single_departure_route(contract["id"], 420, loop_minutes=48, name="Morning Loop")
    eleven = add_single_departure_route(
        contract["id"], 479, loop_minutes=30, name="Eleven Gap Shuttle"
    )
    twelve = add_single_departure_route(
        contract["id"], 480, loop_minutes=30, name="Twelve Gap Shuttle"
    )
    assign_trip(first["trip"]["id"], vehicle["id"], driver["id"])
    return {
        "contract": contract,
        "vehicle": vehicle,
        "driver": driver,
        "trip_420": first["trip"],
        "trip_479": eleven["trip"],
        "trip_480": twelve["trip"],
    }


def setup_touching_intervals_scenario() -> dict:
    """A 420..468 trip already bound to the first bus and the driver, and a
    468..498 trip whose departure touches the first trip's arrival.

    Returns {"contract", "vehicle_a", "vehicle_b", "driver", "trip_early", "trip_touching"}.
    """
    set_clock("2026-09-02T05:00:00Z")
    contract = create_active_contract(client_name="Adjacency Hotel")
    vehicle_a = create_vehicle(odometer_km=4_000)
    vehicle_b = create_vehicle(odometer_km=4_200)
    driver = create_driver(full_name="Hana Kim")
    early = add_single_departure_route(contract["id"], 420, loop_minutes=48, name="Early Loop")
    touching = add_single_departure_route(
        contract["id"], 468, loop_minutes=30, name="Touching Loop"
    )
    assign_trip(early["trip"]["id"], vehicle_a["id"], driver["id"])
    return {
        "contract": contract,
        "vehicle_a": vehicle_a,
        "vehicle_b": vehicle_b,
        "driver": driver,
        "trip_early": early["trip"],
        "trip_touching": touching["trip"],
    }


def setup_duty_cap_scenario() -> dict:
    """Two non-overlapping trips of 48 and 30 minutes on one service date, a
    driver capped at 77 minutes holding the first, and a driver capped at 78.

    Returns {"contract", "vehicle_a", "vehicle_b", "driver_77", "driver_78",
             "trip_48", "trip_30"}.
    """
    set_clock("2026-09-02T05:00:00Z")
    contract = create_active_contract(client_name="Duty Cap Corp", site_type="CORPORATE")
    vehicle_a = create_vehicle(odometer_km=6_000)
    vehicle_b = create_vehicle(odometer_km=6_200)
    driver_77 = create_driver(full_name="Cap Seventy Seven", max_duty_minutes_per_day=77)
    driver_78 = create_driver(full_name="Cap Seventy Eight", max_duty_minutes_per_day=78)
    early = add_single_departure_route(contract["id"], 420, loop_minutes=48, name="Duty Early")
    late = add_single_departure_route(contract["id"], 468, loop_minutes=30, name="Duty Late")
    assign_trip(early["trip"]["id"], vehicle_a["id"], driver_77["id"])
    return {
        "contract": contract,
        "vehicle_a": vehicle_a,
        "vehicle_b": vehicle_b,
        "driver_77": driver_77,
        "driver_78": driver_78,
        "trip_48": early["trip"],
        "trip_30": late["trip"],
    }


def setup_driver_overlap_scenario() -> dict:
    """Two genuinely overlapping trips — 420..468 and 440..470 — on separate
    buses, the first already held by the driver.

    Returns {"contract", "vehicle_a", "vehicle_b", "driver", "trip_early", "trip_overlapping"}.
    """
    set_clock("2026-09-02T05:00:00Z")
    contract = create_active_contract(client_name="Driver Overlap Corp", site_type="CORPORATE")
    vehicle_a = create_vehicle(odometer_km=700)
    vehicle_b = create_vehicle(odometer_km=800)
    driver = create_driver(full_name="Overlap Driver")
    early = add_single_departure_route(contract["id"], 420, loop_minutes=48, name="Overlap Early")
    late = add_single_departure_route(contract["id"], 440, loop_minutes=30, name="Overlap Late")
    assign_trip(early["trip"]["id"], vehicle_a["id"], driver["id"])
    return {
        "contract": contract,
        "vehicle_a": vehicle_a,
        "vehicle_b": vehicle_b,
        "driver": driver,
        "trip_early": early["trip"],
        "trip_overlapping": late["trip"],
    }


# ─── Tier 5: branded fleet ────────────────────────────────────────────────────

def setup_branded_fleet_at_floor(ada_min_accessible_pct: float = 50.00) -> dict:
    """A contract at the given accessibility floor with one ADA and one non-ADA
    bus already wrapped in its livery, so the branded ADA share sits exactly on
    the floor. Returns {"contract", "ada_vehicle", "plain_vehicle"}."""
    contract = create_active_contract(
        client_name="Floor Enforcement Corp", site_type="CORPORATE",
        ada_min_accessible_pct=ada_min_accessible_pct,
    )
    ada_vehicle = create_vehicle(
        is_ada_accessible=True, odometer_km=100, branding_contract_id=contract["id"]
    )
    plain_vehicle = create_vehicle(
        is_ada_accessible=False, odometer_km=200, branding_contract_id=contract["id"]
    )
    return {
        "contract": contract,
        "ada_vehicle": ada_vehicle,
        "plain_vehicle": plain_vehicle,
    }
