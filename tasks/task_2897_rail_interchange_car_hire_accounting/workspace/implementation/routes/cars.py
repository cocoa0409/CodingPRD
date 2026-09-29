"""Cars and their three status dimensions (PRD sections 3.2, 3.5, 3.6)."""
from flask import Blueprint

import db
import middleware
import response
import shapes
from errors import fail
from middleware import endpoint
from services import pricing, serialize

bp = Blueprint("cars", __name__)


def open_bad_order_segment(car):
    rows = [
        m
        for m in db.movements.values()
        if m["car_id"] == car["id"]
        and m["bad_order_from"] is not None
        and m["bad_order_to"] is None
        and m["status"] != "VOID"
    ]
    rows.sort(key=db.order_key)
    return rows[-1] if rows else None


@bp.post("/car-hire/cars")
@endpoint(roles=[db.ROLE_FLEET_OWNER])
def create_car():
    body = shapes.body()
    car_mark = shapes.s_str(body, "car_mark")
    car_type_id = shapes.s_id(body, "car_type_id")
    owner_road_id = shapes.s_id(body, "owner_road_id")
    initial_handling_road_id = shapes.s_id(body, "initial_handling_road_id", required=False)

    car_type = db.lookup("car_type", car_type_id)
    owner = db.lookup("railroad", owner_road_id)
    handling_road_id = owner_road_id
    if initial_handling_road_id is not None:
        db.lookup("railroad", initial_handling_road_id)
        handling_road_id = initial_handling_road_id

    middleware.require_party(owner_road_id)
    middleware.require_active(middleware.acting(), owner_road_id, handling_road_id)

    if any(c["car_mark"] == car_mark for c in db.cars.values()):
        fail("ERR_DUPLICATE_RESOURCE", "car_mark is already registered.")

    row = db.base_row()
    row.update(
        {
            "car_mark": car_mark,
            "car_type_id": car_type["id"],
            "owner_road_id": owner["id"],
            "current_handling_road_id": handling_road_id,
            "custody_status": "ON_HOME_ROAD",
            "mechanical_status": "SERVICEABLE",
            "routing_status": "NO_OBLIGATION",
            "prescribed_return_junction_id": None,
            "obligation_issued_at": None,
            "obligation_due_at": None,
            "bad_order_since": None,
            "bad_order_cleared_at": None,
            "cumulative_mileage": 0,
        }
    )
    db.cars[row["id"]] = row
    # the bootstrap hire segment: the only one with a null received_event_id
    pricing.open_movement(row, handling_road_id, row["created_at"], 0, "EMPTY", None)
    return response.ok(serialize.car(row), 201)


@bp.get("/car-hire/cars")
@endpoint(roles=db.ALL_ROLES)
def list_cars():
    response.page_params()
    custody = shapes.q_enum("custody_status", db.CUSTODY_STATUS)
    mechanical = shapes.q_enum("mechanical_status", db.MECHANICAL_STATUS)
    routing = shapes.q_enum("routing_status", db.ROUTING_STATUS)
    owner_road_id = shapes.q_str("owner_road_id")
    handling_road_id = shapes.q_str("current_handling_road_id")
    car_type_id = shapes.q_str("car_type_id")
    junction_id = shapes.q_str("prescribed_return_junction_id")
    car_mark = shapes.q_str("car_mark")

    rows = list(db.cars.values())
    if custody is not None:
        rows = [r for r in rows if serialize.derive_custody(r) == custody]
    if mechanical is not None:
        rows = [r for r in rows if r["mechanical_status"] == mechanical]
    if routing is not None:
        rows = [r for r in rows if r["routing_status"] == routing]
    if owner_road_id is not None:
        rows = [r for r in rows if r["owner_road_id"] == owner_road_id]
    if handling_road_id is not None:
        rows = [r for r in rows if r["current_handling_road_id"] == handling_road_id]
    if car_type_id is not None:
        rows = [r for r in rows if r["car_type_id"] == car_type_id]
    if junction_id is not None:
        rows = [r for r in rows if r["prescribed_return_junction_id"] == junction_id]
    if car_mark is not None:
        rows = [r for r in rows if r["car_mark"] == car_mark]
    rows.sort(key=db.order_key)
    return response.paginate(rows, serialize.car)


@bp.get("/car-hire/cars/<car_id>")
@endpoint(roles=db.ALL_ROLES, path_params=[("car_id", "car")])
def read_car(car):
    middleware.party_car(car)
    return response.ok(serialize.car(car))


@bp.post("/car-hire/cars/<car_id>/bad-order-report")
@endpoint(roles=[db.ROLE_CLERK], path_params=[("car_id", "car")])
def bad_order_report(car):
    body = shapes.body()
    reported_at = shapes.s_dt(body, "reported_at")
    shapes.s_str(body, "defect_code")
    shapes.s_str(body, "defect_note", required=False)

    # the reporting road must be the road holding the car
    middleware.require_party(car["current_handling_road_id"])
    if car["mechanical_status"] != "SERVICEABLE":
        fail("ERR_INVALID_STATE_TRANSITION")
    middleware.require_active(middleware.acting(), car["current_handling_road_id"])
    if reported_at > db.now():
        fail("ERR_EVENT_IN_FUTURE")
    segment = pricing.open_movement_for(car)
    if segment is not None and reported_at < segment["start_at"]:
        fail("ERR_INVALID_INTERVAL", "reported_at precedes the open segment's start.")

    car["mechanical_status"] = "BAD_ORDER"
    car["bad_order_since"] = reported_at
    db.touch(car)
    if segment is not None and segment["bad_order_from"] is None:
        segment["bad_order_from"] = reported_at
        segment["bad_order_to"] = None
        db.touch(segment)
    return response.ok(serialize.car(car))


@bp.post("/car-hire/cars/<car_id>/release-to-service")
@endpoint(roles=[db.ROLE_CLERK], path_params=[("car_id", "car")])
def release_to_service(car):
    body = shapes.body()
    released_at = shapes.s_dt(body, "released_at")
    shapes.s_str(body, "release_note", required=False)

    middleware.require_party(car["current_handling_road_id"])
    if car["mechanical_status"] not in ("BAD_ORDER", "UNDER_REPAIR"):
        fail("ERR_CAR_NOT_BAD_ORDERED")
    middleware.require_active(middleware.acting(), car["current_handling_road_id"])
    if released_at > db.now():
        fail("ERR_EVENT_IN_FUTURE")
    if car["bad_order_since"] is not None and released_at <= car["bad_order_since"]:
        fail("ERR_INVALID_INTERVAL", "released_at must be strictly later than bad_order_since.")

    car["mechanical_status"] = "SERVICEABLE"
    car["bad_order_since"] = None
    car["bad_order_cleared_at"] = released_at
    db.touch(car)
    segment = open_bad_order_segment(car)
    if segment is not None:
        segment["bad_order_to"] = released_at
        db.touch(segment)
    return response.ok(serialize.car(car))


@bp.post("/car-hire/cars/<car_id>/empty-routing-obligation")
@endpoint(roles=[db.ROLE_FLEET_OWNER], path_params=[("car_id", "car")])
def empty_routing_obligation(car):
    body = shapes.body()
    junction_id = shapes.s_id(body, "prescribed_return_junction_id")
    issued_at = shapes.s_dt(body, "issued_at")
    due_at = shapes.s_dt(body, "due_at")

    junction = db.lookup("junction", junction_id)
    # the obligation belongs to the owner, never the holder
    middleware.require_party(car["owner_road_id"])
    if car["routing_status"] not in ("NO_OBLIGATION", "OBLIGATION_MET"):
        fail("ERR_INVALID_STATE_TRANSITION")
    middleware.require_active(middleware.acting(), car["owner_road_id"])
    if junction["status"] != "OPEN":
        fail("ERR_JUNCTION_CLOSED")
    if car["owner_road_id"] not in (junction["road_a_id"], junction["road_b_id"]):
        fail("ERR_ROADS_NOT_CONNECTED_AT_JUNCTION")
    if issued_at > db.now():
        fail("ERR_EVENT_IN_FUTURE")
    if issued_at >= due_at or db.now() >= due_at:
        fail("ERR_INVALID_INTERVAL")

    car["routing_status"] = "OBLIGATION_ACTIVE"
    car["prescribed_return_junction_id"] = junction["id"]
    car["obligation_issued_at"] = issued_at
    car["obligation_due_at"] = due_at
    db.touch(car)
    return response.ok(serialize.car(car))
