"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, and uses get_success_data() so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.

All roles are opaque (X-User-ID is not compared to any entity id), so the
shared header constants from test_users are correct for every call.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_yard_payload,
    create_train_plan_payload,
    create_crew_pool_payload,
    create_locomotive_payload,
    create_customer_payload,
    create_shipment_payload,
)
from .test_users import TEST_USERS

NP = TEST_USERS["network_planner_headers"]
CD = TEST_USERS["crew_dispatcher_headers"]
PP = TEST_USERS["power_planner_headers"]
TS = TEST_USERS["terminal_superintendent_headers"]
SM = TEST_USERS["service_manager_headers"]
ANY = TEST_USERS["any_headers"]

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------

def set_clock(current_utc: str):
    return get_success_data(
        api_client.set_clock({"current_utc": current_utc}, NP)
    )


def create_yard(yard_code=None, dwell_benchmark_hours=10, classification_capacity_cars=100):
    return get_success_data(
        api_client.create_yard(
            create_yard_payload(
                yard_code=yard_code or _uniq("YD"),
                dwell_benchmark_hours=dwell_benchmark_hours,
                classification_capacity_cars=classification_capacity_cars,
            ),
            NP,
        )
    )


def create_train_plan(origin_yard_id, destination_yard_id, train_symbol=None, **overrides):
    return get_success_data(
        api_client.create_train_plan(
            create_train_plan_payload(
                train_symbol=train_symbol or _uniq("PLAN"),
                origin_yard_id=origin_yard_id,
                destination_yard_id=destination_yard_id,
                **overrides,
            ),
            NP,
        )
    )


def create_active_plan(origin_yard_id, destination_yard_id, train_symbol=None, **overrides):
    """Create a plan and activate it. Returns the ACTIVE plan dict."""
    plan = create_train_plan(origin_yard_id, destination_yard_id, train_symbol, **overrides)
    return get_success_data(
        api_client.activate_train_plan(
            plan["id"], {"expected_train_plan_version": plan["version"]}, NP
        )
    )


def create_customer(customer_code=None, name="Fixture Shipper"):
    return get_success_data(
        api_client.create_customer(
            create_customer_payload(
                customer_code=customer_code or _uniq("CU"), name=name
            ),
            SM,
        )
    )


def create_shipment(customer_id, origin_yard_id, destination_yard_id, **overrides):
    return get_success_data(
        api_client.create_shipment(
            create_shipment_payload(
                customer_id=customer_id,
                origin_yard_id=origin_yard_id,
                destination_yard_id=destination_yard_id,
                **overrides,
            ),
            SM,
        )
    )


def create_crew_pool(home_yard_id, craft="CONDUCTOR", service_date="2026-09-01",
                     crews_available=2):
    return get_success_data(
        api_client.create_crew_pool(
            create_crew_pool_payload(
                home_yard_id=home_yard_id,
                craft=craft,
                service_date=service_date,
                crews_available=crews_available,
            ),
            CD,
        )
    )


def create_locomotive(current_yard_id, unit_number=None, horsepower=4400):
    return get_success_data(
        api_client.create_locomotive(
            create_locomotive_payload(
                unit_number=unit_number or _uniq("UP"),
                current_yard_id=current_yard_id,
                horsepower=horsepower,
            ),
            PP,
        )
    )


def assign_trip_legs(shipment, plan_ids):
    """Assign a single-generation itinerary of plan ids to a shipment.

    Uses the shipment's current version (re-reads if a dict is passed with a
    stale version). Returns the list of created legs (response data).
    """
    legs = [
        {"train_plan_id": pid, "leg_sequence": i + 1}
        for i, pid in enumerate(plan_ids)
    ]
    return get_success_data(
        api_client.assign_trip_legs(
            shipment["id"],
            {"expected_shipment_version": shipment["version"], "legs": legs},
            NP,
        )
    )


def create_departure(plan_id, service_date, crew_pool_id, locomotive_id,
                     car_count_planned=5, crew_hours_estimated=6):
    return get_success_data(
        api_client.create_train_departure(
            {
                "train_plan_id": plan_id,
                "service_date": service_date,
                "crew_pool_id": crew_pool_id,
                "locomotive_id": locomotive_id,
                "car_count_planned": car_count_planned,
                "crew_hours_estimated": crew_hours_estimated,
            },
            TS,
        )
    )


def finalize_departure(departure_id):
    return get_success_data(api_client.finalize_train_departure(departure_id, TS))


def record_car_event(shipment_id, yard_id, event_type, occurred_at, car_count):
    return get_success_data(
        api_client.create_car_event(
            {
                "shipment_id": shipment_id,
                "yard_id": yard_id,
                "event_type": event_type,
                "occurred_at": occurred_at,
                "car_count": car_count,
            },
            TS,
        )
    )


def get_shipment(shipment_id):
    return get_success_data(api_client.get_shipment(shipment_id, ANY))


def get_yard(yard_id):
    return get_success_data(api_client.get_yard(yard_id, ANY))


def get_pool(pool_id):
    return get_success_data(api_client.get_crew_pool(pool_id, ANY))


def get_locomotive(loco_id):
    return get_success_data(api_client.get_locomotive(loco_id, ANY))


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, ANY))


def list_legs_for_shipment(shipment_id, params=None):
    merged = {"shipment_id": shipment_id}
    if params:
        merged.update(params)
    data, _meta = _list(api_client.list_trip_legs(ANY, params=merged))
    return data


def list_exceptions_for_shipment(shipment_id):
    data, _meta = _list(api_client.list_shipment_exceptions(shipment_id, ANY))
    return data


def _list(resp):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


# ---------------------------------------------------------------------------
# Tier 2/3: full single-train operational scenario
# ---------------------------------------------------------------------------

def setup_operational_scenario(
    prefix,
    departure_utc="2026-09-01T08:00:00Z",
    frequency_mask=("TUE",),
    route_miles=300,
    cutoff_minutes=60,
    crews_available=2,
    crew_hours_estimated=6,
    shipment_car_count=2,
    committed_miles=300,
    pickup_by="2026-09-01T07:30:00Z",
    delivery_by="2026-09-04T00:00:00Z",
    start_clock="2026-09-01T06:00:00Z",
    assign=True,
    service_date="2026-09-01",
):
    """Yards A/B + ACTIVE plan A->B + customer + shipment (+ assignment) +
    CONDUCTOR pool + AVAILABLE locomotive + SCHEDULED departure.

    Returns a dict with every entity created.
    """
    set_clock(start_clock)
    yA = create_yard(yard_code=_uniq(f"{prefix}A"))
    yB = create_yard(yard_code=_uniq(f"{prefix}B"))
    plan = create_active_plan(
        yA["id"], yB["id"],
        train_symbol=_uniq(f"{prefix}-P"),
        scheduled_departure_utc=departure_utc,
        frequency_mask=list(frequency_mask),
        route_distance_miles=route_miles,
        cutoff_minutes=cutoff_minutes,
    )
    customer = create_customer()
    shipment = create_shipment(
        customer["id"], yA["id"], yB["id"],
        car_count=shipment_car_count,
        first_mile_pickup_by=pickup_by,
        last_mile_delivery_by=delivery_by,
        committed_route_miles=committed_miles,
    )
    if assign:
        assign_trip_legs(shipment, [plan["id"]])
    pool = create_crew_pool(yA["id"], crews_available=crews_available,
                            service_date=service_date)
    loco = create_locomotive(yA["id"])
    departure = create_departure(
        plan["id"], service_date, pool["id"], loco["id"],
        car_count_planned=shipment_car_count,
        crew_hours_estimated=crew_hours_estimated,
    )
    return {
        "yA": yA, "yB": yB, "plan": plan, "customer": customer,
        "shipment": shipment, "pool": pool, "loco": loco,
        "departure": departure,
    }


def finalize_and_depart(scenario, at_utc):
    """Advance the clock and finalize the scenario's departure; record the
    shipment's TRAIN_DEPARTURE event at the origin yard."""
    set_clock(at_utc)
    dep = finalize_departure(scenario["departure"]["id"])
    s = scenario["shipment"]
    record_car_event(s["id"], scenario["yA"]["id"], "TRAIN_DEPARTURE", at_utc,
                     s["car_count"])
    return dep


# ---------------------------------------------------------------------------
# Tier 4: two-session dwell scenario at one yard
# ---------------------------------------------------------------------------

def setup_two_shipments_dwelling(
    prefix,
    benchmark=10,
    arrival_a_utc="2026-09-01T20:00:00Z",
    arrival_b_utc="2026-09-01T21:00:00Z",
    departure_utc="2026-09-01T08:00:00Z",
    cars_a=3,
    cars_b=2,
):
    """Two shipments (cars_a / cars_b) ride one ACTIVE plan A->C, depart via
    one finalized departure, and both have OPEN dwell sessions at yard C
    (arrival events recorded at arrival_a_utc / arrival_b_utc).

    Returns a dict with yards, plan, customer, both shipments, pool, loco,
    departure.
    """
    set_clock("2026-09-01T06:00:00Z")
    yA = create_yard(yard_code=_uniq(f"{prefix}A"), dwell_benchmark_hours=benchmark)
    yC = create_yard(yard_code=_uniq(f"{prefix}C"), dwell_benchmark_hours=benchmark)
    plan = create_active_plan(
        yA["id"], yC["id"],
        train_symbol=_uniq(f"{prefix}-P"),
        scheduled_departure_utc=departure_utc,
        frequency_mask=["TUE"],
        route_distance_miles=300,
    )
    customer = create_customer()
    sA = create_shipment(customer["id"], yA["id"], yC["id"], car_count=cars_a)
    sB = create_shipment(customer["id"], yA["id"], yC["id"], car_count=cars_b)
    assign_trip_legs(sA, [plan["id"]])
    assign_trip_legs(sB, [plan["id"]])
    pool = create_crew_pool(yA["id"], crews_available=2)
    loco = create_locomotive(yA["id"])
    dep = create_departure(plan["id"], "2026-09-01", pool["id"], loco["id"],
                           car_count_planned=cars_a + cars_b, crew_hours_estimated=8)
    set_clock(departure_utc)
    finalize_departure(dep["id"])
    record_car_event(sA["id"], yA["id"], "TRAIN_DEPARTURE", departure_utc, cars_a)
    record_car_event(sB["id"], yA["id"], "TRAIN_DEPARTURE", departure_utc, cars_b)
    set_clock(arrival_a_utc)
    record_car_event(sA["id"], yC["id"], "YARD_ARRIVAL", arrival_a_utc, cars_a)
    set_clock(arrival_b_utc)
    record_car_event(sB["id"], yC["id"], "YARD_ARRIVAL", arrival_b_utc, cars_b)
    return {
        "yA": yA, "yC": yC, "plan": plan, "customer": customer,
        "sA": sA, "sB": sB, "pool": pool, "loco": loco, "departure": dep,
    }
