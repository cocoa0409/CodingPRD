"""Composite setup helpers.

Every test starts against an empty database, so each fixture builds its full
precondition chain from PRD-declared endpoints. Setup calls use
get_success_data() (lenient) so a setup failure surfaces as a clear error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_facility_payload, create_dough_type_payload, create_cafe_payload,
    create_cafe_order_payload, create_route_payload, create_route_stop_payload,
    create_schedule_payload, create_bake_entry_payload,
    create_donation_pickup_payload, create_billing_period_payload,
)
from .test_users import (
    TEST_USERS, make_cafe_manager_headers,
)

PLANNER = TEST_USERS["facility_planner_headers"]
DISPATCHER = TEST_USERS["route_dispatcher_headers"]
DONATION = TEST_USERS["donation_coordinator_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: master data
# ---------------------------------------------------------------------------

def setup_facility(effective_capacity_units=2000, name="F1"):
    """Create a dough facility. Returns the facility dict."""
    return get_success_data(
        api.create_facility(
            create_facility_payload(name=name,
                                    effective_capacity_units=effective_capacity_units),
            PLANNER))


def setup_cxl_dough_type(**overrides):
    """CXL: conventional, cutoff 13:00, $4.00 flat, no-substitution."""
    payload = create_dough_type_payload(code="CXL", category="CONVENTIONAL",
                                        shelf_life_hours=36,
                                        order_cutoff_local="13:00",
                                        substitution_allowed=False,
                                        flat_transfer_price=4.00)
    payload.update(overrides)
    return get_success_data(api.create_dough_type(payload, PLANNER))


def setup_bmt_dough_type(**overrides):
    """BMT: artisan, cutoff 18:00, $5.00 flat, no-substitution."""
    payload = create_dough_type_payload(code="BMT", category="ARTISAN",
                                        shelf_life_hours=48,
                                        order_cutoff_local="18:00",
                                        substitution_allowed=False,
                                        flat_transfer_price=5.00)
    payload.update(overrides)
    return get_success_data(api.create_dough_type(payload, PLANNER))


def setup_cafe(facility_id, name="C1", ownership_type="FRANCHISE",
               credit_limit_cents=90000):
    """Create a cafe. Returns the cafe dict."""
    return get_success_data(
        api.create_cafe(
            create_cafe_payload(name=name, facility_id=facility_id,
                                ownership_type=ownership_type,
                                credit_limit_cents=credit_limit_cents),
            PLANNER))


def set_clock(to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, PLANNER))


# ---------------------------------------------------------------------------
# Tier 2: ordering lifecycle
# ---------------------------------------------------------------------------

def create_order(cafe, dough_type, production_date, quantity):
    """Create a DRAFT order with a fresh OCC token. Returns the order dict."""
    cafe_now = get_success_data(api.get_cafe(cafe["id"], PLANNER))
    return get_success_data(
        api.create_cafe_order(
            create_cafe_order_payload(cafe_id=cafe["id"],
                                      dough_type_id=dough_type["id"],
                                      production_date=production_date,
                                      quantity=quantity,
                                      expected_cafe_version=cafe_now["version"]),
            make_cafe_manager_headers(cafe["id"])))


def submit_order(cafe, order):
    return get_success_data(
        api.submit_cafe_order(order["id"], make_cafe_manager_headers(cafe["id"])))


def place_and_submit_order(cafe, dough_type, production_date, quantity,
                           order_clock="2026-09-09T10:00:00Z"):
    """Set the clock (pre-cutoff), create + submit an order. Returns order."""
    set_clock(order_clock)
    order = create_order(cafe, dough_type, production_date, quantity)
    submit_order(cafe, order)
    return get_success_data(api.get_cafe_order(order["id"], PLANNER))


# ---------------------------------------------------------------------------
# Tier 3: plan lifecycle
# ---------------------------------------------------------------------------

def create_plan_for_date(facility, production_date,
                         post_cutoff_clock="2026-09-09T13:00:01Z"):
    """Move the clock past the cutoff (auto-locking SUBMITTED orders), then
    create the plan, which sweeps the LOCKED orders. Returns the plan."""
    set_clock(post_cutoff_clock)
    return get_success_data(
        api.create_production_plan(facility["id"],
                                   {"production_date": production_date},
                                   PLANNER))


def lock_plan(facility, plan):
    return get_success_data(api.lock_production_plan(facility["id"], plan["id"], PLANNER))


def release_plan(facility, plan):
    fac_now = get_success_data(api.get_facility(facility["id"], PLANNER))
    return get_success_data(
        api.release_production_plan(facility["id"], plan["id"],
                                    {"expected_facility_version": fac_now["version"]},
                                    PLANNER))


def close_plan(facility, plan):
    return get_success_data(api.close_production_plan(facility["id"], plan["id"], PLANNER))


# ---------------------------------------------------------------------------
# Tier 4: routes and stops
# ---------------------------------------------------------------------------

def setup_route(facility, production_date, stops, vehicle_capacity_units=1000,
                depart=False):
    """Create a route with the given stops, publish it, optionally depart.

    stops: list of dicts {cafe, seq, planned_arrival, window_start_local,
                          window_end_local, planned_units}
    Returns (route, [stop, ...]).
    """
    route = get_success_data(
        api.create_route(facility["id"],
                         create_route_payload(
                             production_date=production_date,
                             vehicle_capacity_units=vehicle_capacity_units),
                         DISPATCHER))
    created_stops = []
    for spec in stops:
        stop = get_success_data(
            api.create_route_stop(
                facility["id"], route["id"],
                create_route_stop_payload(
                    seq=spec["seq"], cafe_id=spec["cafe"]["id"],
                    planned_arrival=spec["planned_arrival"],
                    window_start_local=spec["window_start_local"],
                    window_end_local=spec["window_end_local"],
                    planned_units=spec["planned_units"]),
                DISPATCHER))
        created_stops.append(stop)
    get_success_data(api.publish_route(facility["id"], route["id"], DISPATCHER))
    if depart:
        get_success_data(api.depart_route(facility["id"], route["id"], DISPATCHER))
    return route, created_stops


def arrive_stop(facility, route, stop, arrival_clock, loaded_units=None):
    """Park the clock at arrival_clock and record the arrival. Returns response data."""
    set_clock(arrival_clock)
    payload = {} if loaded_units is None else {"loaded_units": loaded_units}
    return get_success_data(
        api.arrive_route_stop(facility["id"], route["id"], stop["id"], payload,
                              DISPATCHER))


def get_order(order_id):
    return get_success_data(api.get_cafe_order(order_id, PLANNER))


def get_cafe(cafe_id):
    return get_success_data(api.get_cafe(cafe_id, PLANNER))


def get_plan(plan_id):
    return get_success_data(api.get_production_plan(plan_id, PLANNER))


def get_route(route_id):
    return get_success_data(api.get_route(route_id, PLANNER))


def get_stop(stop_id):
    return get_success_data(api.get_route_stop(stop_id, PLANNER))


# ---------------------------------------------------------------------------
# Tier 5: full-day scenarios
# ---------------------------------------------------------------------------

def setup_single_cafe_day(production_date="2026-09-10", quantity=100,
                          ownership_type="FRANCHISE", credit_limit_cents=90000,
                          facility_capacity=2000, dough_overrides=None,
                          arrive_loaded_units=None, close_plan_too=True,
                          order_clock="2026-09-09T10:00:00Z",
                          post_cutoff_clock="2026-09-09T13:00:01Z"):
    """Full single-cafe chain: F1 + CXL + cafe, order submitted, plan created/
    locked/released, route published+departed, one stop arrived in-window.

    Returns dict with facility, dough_type, cafe, order, plan, route, stop.
    With close_plan_too=True the plan is closed (order INVOICED).
    """
    facility = setup_facility(facility_capacity)
    dough_type = setup_cxl_dough_type(**(dough_overrides or {}))
    cafe = setup_cafe(facility["id"], "C1", ownership_type, credit_limit_cents)
    order = place_and_submit_order(cafe, dough_type, production_date, quantity,
                                   order_clock=order_clock)
    plan = create_plan_for_date(facility, production_date, post_cutoff_clock)
    lock_plan(facility, plan)
    release_plan(facility, plan)
    route, stops = setup_route(
        facility, production_date,
        [{"cafe": cafe, "seq": 1,
          "planned_arrival": f"{production_date}T03:10:00Z",
          "window_start_local": "03:00", "window_end_local": "04:00",
          "planned_units": quantity}],
        vehicle_capacity_units=max(500, quantity),
        depart=True)
    arrive_stop(facility, route, stops[0], f"{production_date}T03:10:00Z",
                loaded_units=arrive_loaded_units)
    if close_plan_too:
        close_plan(facility, plan)
    return {
        "facility": facility, "dough_type": dough_type, "cafe": cafe,
        "order": get_order(order["id"]), "plan": get_plan(plan["id"]),
        "route": get_route(route["id"]), "stop": get_stop(stops[0]["id"]),
    }


def setup_five_cafe_invoiced_day():
    """Five-cafe delivery day for 2026-09-11, plan closed, all orders INVOICED.

    C1 FRANCHISE 180 CXL; C2 COMPANY 240 CXL; C3 COMPANY 50 BMT;
    C4 FRANCHISE 100 CXL; C5 FRANCHISE 150 CXL + 60 BMT.
    Returns dict with facility, cxl, bmt, cafes, orders, plan.
    """
    facility = setup_facility(2000)
    cxl = setup_cxl_dough_type()
    bmt = setup_bmt_dough_type()
    c1 = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
    c2 = setup_cafe(facility["id"], "C2", "COMPANY", 200000)
    c3 = setup_cafe(facility["id"], "C3", "COMPANY", 90000)
    c4 = setup_cafe(facility["id"], "C4", "FRANCHISE", 200000)
    c5 = setup_cafe(facility["id"], "C5", "FRANCHISE", 100000)

    o_c1 = place_and_submit_order(c1, cxl, "2026-09-11", 180,
                                  order_clock="2026-09-10T09:00:00Z")
    o_c2 = place_and_submit_order(c2, cxl, "2026-09-11", 240,
                                  order_clock="2026-09-10T09:00:00Z")
    o_c3 = place_and_submit_order(c3, bmt, "2026-09-11", 50,
                                  order_clock="2026-09-10T09:00:00Z")
    o_c4 = place_and_submit_order(c4, cxl, "2026-09-11", 100,
                                  order_clock="2026-09-10T09:00:00Z")
    o_c5 = place_and_submit_order(c5, cxl, "2026-09-11", 150,
                                  order_clock="2026-09-10T09:00:00Z")
    o_c5b = place_and_submit_order(c5, bmt, "2026-09-11", 60,
                                   order_clock="2026-09-10T09:00:00Z")

    plan = create_plan_for_date(facility, "2026-09-11", "2026-09-10T18:00:00Z")
    lock_plan(facility, plan)
    release_plan(facility, plan)

    route, stops = setup_route(
        facility, "2026-09-11",
        [{"cafe": c1, "seq": 1, "planned_arrival": "2026-09-11T03:10:00Z",
          "window_start_local": "03:00", "window_end_local": "04:00",
          "planned_units": 180},
         {"cafe": c2, "seq": 2, "planned_arrival": "2026-09-11T03:20:00Z",
          "window_start_local": "03:00", "window_end_local": "04:00",
          "planned_units": 240},
         {"cafe": c3, "seq": 3, "planned_arrival": "2026-09-11T03:30:00Z",
          "window_start_local": "03:00", "window_end_local": "04:00",
          "planned_units": 50},
         {"cafe": c4, "seq": 4, "planned_arrival": "2026-09-11T03:40:00Z",
          "window_start_local": "03:00", "window_end_local": "04:00",
          "planned_units": 100},
         {"cafe": c5, "seq": 5, "planned_arrival": "2026-09-11T03:50:00Z",
          "window_start_local": "03:00", "window_end_local": "04:00",
          "planned_units": 210}],
        vehicle_capacity_units=1000, depart=True)
    for stop, clock in zip(stops, ["2026-09-11T03:10:00Z", "2026-09-11T03:20:00Z",
                                   "2026-09-11T03:30:00Z", "2026-09-11T03:40:00Z",
                                   "2026-09-11T03:50:00Z"]):
        arrive_stop(facility, route, stop, clock)
    close_plan(facility, plan)

    return {
        "facility": facility, "cxl": cxl, "bmt": bmt,
        "c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5,
        "o_c1": o_c1, "o_c2": o_c2, "o_c3": o_c3, "o_c4": o_c4,
        "o_c5": o_c5, "o_c5b": o_c5b,
        "plan": get_plan(plan["id"]),
    }


def setup_two_cafe_released_day():
    """C1 180 CXL + C3 50 BMT for 2026-09-11, delivered on time; plan RELEASED
    (not yet closed). Returns dict with both cafes, orders, plan."""
    facility = setup_facility(2000)
    cxl = setup_cxl_dough_type()
    bmt = setup_bmt_dough_type()
    c1 = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
    c3 = setup_cafe(facility["id"], "C3", "COMPANY", 90000)

    o_c1 = place_and_submit_order(c1, cxl, "2026-09-11", 180,
                                  order_clock="2026-09-10T09:00:00Z")
    o_c3 = place_and_submit_order(c3, bmt, "2026-09-11", 50,
                                  order_clock="2026-09-10T09:00:00Z")

    plan = create_plan_for_date(facility, "2026-09-11", "2026-09-10T18:00:00Z")
    lock_plan(facility, plan)
    release_plan(facility, plan)

    route, stops = setup_route(
        facility, "2026-09-11",
        [{"cafe": c1, "seq": 1, "planned_arrival": "2026-09-11T03:10:00Z",
          "window_start_local": "03:00", "window_end_local": "04:00",
          "planned_units": 180},
         {"cafe": c3, "seq": 2, "planned_arrival": "2026-09-11T03:30:00Z",
          "window_start_local": "03:00", "window_end_local": "04:00",
          "planned_units": 50}],
        vehicle_capacity_units=500, depart=True)
    arrive_stop(facility, route, stops[0], "2026-09-11T03:10:00Z")
    arrive_stop(facility, route, stops[1], "2026-09-11T03:30:00Z")

    return {
        "facility": facility, "cxl": cxl, "bmt": bmt,
        "c1": c1, "c3": c3, "o_c1": o_c1, "o_c3": o_c3,
        "plan": get_plan(plan["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 6: schedules, bake entries, donations
# ---------------------------------------------------------------------------

def setup_open_schedule(cafe, business_date="2026-09-10",
                        open_clock="2026-09-10T04:00:00Z"):
    """Create and open a schedule for the cafe. Returns the schedule."""
    mgr = make_cafe_manager_headers(cafe["id"])
    schedule = get_success_data(
        api.create_schedule(cafe["id"], create_schedule_payload(business_date=business_date),
                            mgr))
    set_clock(open_clock)
    get_success_data(api.open_schedule(cafe["id"], schedule["id"], mgr))
    return get_success_data(api.get_schedule(schedule["id"], PLANNER))


def close_schedule(cafe, schedule):
    return get_success_data(
        api.close_schedule(cafe["id"], schedule["id"],
                           make_cafe_manager_headers(cafe["id"])))


def create_bake_entry(cafe, schedule, order, quantity=40,
                      proof_start_at="2026-09-10T04:00:00Z", proof_minutes=90):
    return get_success_data(
        api.create_bake_entry(
            cafe["id"], schedule["id"],
            create_bake_entry_payload(cafe_order_id=order["id"], quantity=quantity,
                                      proof_start_at=proof_start_at,
                                      proof_minutes=proof_minutes),
            make_cafe_manager_headers(cafe["id"])))


def start_proof(cafe, schedule, entry):
    return get_success_data(
        api.start_proof(cafe["id"], schedule["id"], entry["id"],
                        make_cafe_manager_headers(cafe["id"])))


def setup_proofing_scenario(production_date="2026-09-10", quantity=100,
                            entry_quantity=40,
                            proof_start_at="2026-09-10T04:00:00Z",
                            proof_minutes=90,
                            proof_clock="2026-09-10T04:00:00Z"):
    """Delivered order + OPEN schedule + one entry already PROOFING."""
    day = setup_single_cafe_day(production_date=production_date, quantity=quantity,
                                close_plan_too=False)
    schedule = setup_open_schedule(day["cafe"], business_date=production_date,
                                   open_clock=proof_clock)
    entry = create_bake_entry(day["cafe"], schedule, day["order"],
                              quantity=entry_quantity, proof_start_at=proof_start_at,
                              proof_minutes=proof_minutes)
    start_proof(day["cafe"], schedule, entry)
    day["schedule"] = get_success_data(api.get_schedule(schedule["id"], PLANNER))
    day["entry"] = get_success_data(api.get_bake_entry(entry["id"], PLANNER))
    return day


def setup_closed_schedule(cafe, business_date="2026-09-10",
                          open_clock="2026-09-10T08:00:00Z"):
    """Create, open, and close a schedule with no bake entries."""
    schedule = setup_open_schedule(cafe, business_date=business_date,
                                   open_clock=open_clock)
    close_schedule(cafe, schedule)
    return get_success_data(api.get_schedule(schedule["id"], PLANNER))


def log_pickup(cafe, schedule, partner_name="CityFood", unsold_conventional=12,
               unsold_artisan=0):
    return get_success_data(
        api.create_donation_pickup(
            cafe["id"],
            create_donation_pickup_payload(schedule_id=schedule["id"],
                                           partner_name=partner_name,
                                           unsold_conventional=unsold_conventional,
                                           unsold_artisan=unsold_artisan),
            DONATION))


def confirm_pickup(cafe, pickup):
    return get_success_data(
        api.confirm_donation_pickup(cafe["id"], pickup["id"], DONATION))


def get_pickup(pickup_id):
    return get_success_data(api.get_donation_pickup(pickup_id, PLANNER))


# ---------------------------------------------------------------------------
# Tier 7: billing periods
# ---------------------------------------------------------------------------

def setup_billing_period(facility, period_start="2026-09-08",
                         period_end="2026-09-14", admin_pool_cents=5000000):
    return get_success_data(
        api.create_billing_period(
            facility["id"],
            create_billing_period_payload(period_start=period_start,
                                          period_end=period_end,
                                          admin_pool_cents=admin_pool_cents),
            FINANCE))


def add_settlement_line(facility, period, cafe, cafe_hours):
    return get_success_data(
        api.create_settlement_line(facility["id"], period["id"],
                                   {"cafe_id": cafe["id"], "cafe_hours": cafe_hours},
                                   FINANCE))


def get_settlement_line(line_id):
    return get_success_data(api.get_settlement_line(line_id, PLANNER))


def get_billing_period(period_id):
    return get_success_data(api.get_billing_period(period_id, PLANNER))
