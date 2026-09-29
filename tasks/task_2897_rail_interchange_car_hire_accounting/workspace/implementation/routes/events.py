"""Interchange event capture and hire segment reads (PRD sections 3.3, 3.4)."""
from flask import Blueprint

import db
import middleware
import response
import shapes
from errors import fail
from middleware import endpoint
from services import interchange, serialize

bp = Blueprint("events", __name__)


@bp.post("/car-hire/interchange-events")
@endpoint(roles=[db.ROLE_CLERK])
def create_event():
    body = shapes.body()
    # --- step 6: request shape ---
    car_id = shapes.s_id(body, "car_id")
    junction_id = shapes.s_id(body, "junction_id")
    event_type = shapes.s_str(body, "event_type")
    delivering_road_id = shapes.s_id(body, "delivering_road_id")
    receiving_road_id = shapes.s_id(body, "receiving_road_id")
    interchange_at = shapes.s_dt(body, "interchange_at")
    odometer_miles = shapes.s_int(body, "odometer_miles", minimum=0)
    load_status = shapes.s_str(body, "load_status")
    # --- step 7: enums ---
    shapes.check_enum("event_type", event_type, db.EVENT_TYPE)
    shapes.check_enum("load_status", load_status, db.LOAD_STATUS)
    # --- step 8: body foreign keys ---
    car = db.lookup("car", car_id)
    junction = db.lookup("junction", junction_id)
    db.lookup("railroad", delivering_road_id)
    db.lookup("railroad", receiving_road_id)
    # --- step 9: the acting road must be one of the two roads on the event ---
    middleware.require_party(delivering_road_id, receiving_road_id)
    # --- step 17: a bad ordered car cannot be delivered ---
    if event_type == "INTERCHANGE_DELIVERY" and car["mechanical_status"] in (
        "BAD_ORDER",
        "UNDER_REPAIR",
    ):
        fail("ERR_CAR_BAD_ORDER_NOT_INTERCHANGEABLE")
    # --- step 18: suspension ---
    middleware.require_active(middleware.acting(), delivering_road_id, receiving_road_id)
    # --- step 19: junction must be open ---
    if junction["status"] != "OPEN":
        fail("ERR_JUNCTION_CLOSED")
    # --- step 22: the two roads must be the junction's two roads ---
    if {delivering_road_id, receiving_road_id} != {junction["road_a_id"], junction["road_b_id"]}:
        fail("ERR_ROADS_NOT_CONNECTED_AT_JUNCTION")
    # --- step 23: the delivering road must hold the car ---
    if car["current_handling_road_id"] != delivering_road_id:
        fail("ERR_DELIVERING_ROAD_NOT_IN_CUSTODY")
    # --- step 30: no instant after the logical clock ---
    now = db.now()
    if interchange_at > now:
        fail("ERR_EVENT_IN_FUTURE")
    # --- step 31: the late reporting limit is inclusive at 168 hours ---
    if now - interchange_at > db.hours(db.LATE_REPORT_LIMIT_HOURS):
        fail("ERR_LATE_EVENT_REQUIRES_CORRECTION")
    # --- step 32: monotone sequence per car ---
    latest = interchange.latest_recorded_event(car["id"])
    if latest is not None:
        if interchange_at <= latest["interchange_at"] or odometer_miles < int(
            latest["odometer_miles"]
        ):
            fail("ERR_EVENT_OUT_OF_SEQUENCE")
    from services import pricing

    open_segment = pricing.open_movement_for(car)
    if event_type == "INTERCHANGE_DELIVERY" and open_segment is not None:
        if interchange_at <= open_segment["start_at"] or odometer_miles < int(
            open_segment["start_odometer_miles"] or 0
        ):
            fail("ERR_EVENT_OUT_OF_SEQUENCE")

    event = interchange.mint_event(
        car["id"],
        junction["id"],
        event_type,
        delivering_road_id,
        receiving_road_id,
        interchange_at,
        odometer_miles,
        load_status,
        middleware.acting(),
    )
    if event_type == "INTERCHANGE_DELIVERY":
        interchange.capture_delivery(car, event)
    else:
        interchange.capture_rejection(car, event)
    return response.ok(serialize.event(event), 201)


@bp.get("/car-hire/interchange-events")
@endpoint(roles=db.ALL_ROLES)
def list_events():
    response.page_params()
    event_type = shapes.q_enum("event_type", db.EVENT_TYPE)
    status = shapes.q_enum("status", db.EVENT_STATUS)
    source = shapes.q_enum("source", db.EVENT_SOURCE)
    car_id = shapes.q_str("car_id")
    junction_id = shapes.q_str("junction_id")
    delivering = shapes.q_str("delivering_road_id")
    receiving = shapes.q_str("receiving_road_id")
    recorded_by = shapes.q_str("recorded_by_road_id")
    corrects = shapes.q_str("corrects_event_id")
    at_from = shapes.q_dt("interchange_at_from")
    at_to = shapes.q_dt("interchange_at_to")

    rows = list(db.events.values())
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if source is not None:
        rows = [r for r in rows if r["source"] == source]
    if car_id is not None:
        rows = [r for r in rows if r["car_id"] == car_id]
    if junction_id is not None:
        rows = [r for r in rows if r["junction_id"] == junction_id]
    if delivering is not None:
        rows = [r for r in rows if r["delivering_road_id"] == delivering]
    if receiving is not None:
        rows = [r for r in rows if r["receiving_road_id"] == receiving]
    if recorded_by is not None:
        rows = [r for r in rows if r["recorded_by_road_id"] == recorded_by]
    if corrects is not None:
        rows = [r for r in rows if r["corrects_event_id"] == corrects]
    if at_from is not None:
        rows = [r for r in rows if r["interchange_at"] >= at_from]
    if at_to is not None:
        rows = [r for r in rows if r["interchange_at"] <= at_to]
    # interchange_at ascending, created_at ascending on ties
    rows.sort(key=lambda r: (r["interchange_at"], r["created_at"], r["_seq"]))
    return response.paginate(rows, serialize.event)


@bp.get("/car-hire/interchange-events/<interchange_event_id>")
@endpoint(roles=db.ALL_ROLES, path_params=[("interchange_event_id", "event")])
def read_event(event):
    return response.ok(serialize.event(event))


# --------------------------------------------------------------------------
# hire segments
# --------------------------------------------------------------------------


def _movement_sort_key(row):
    """end_at ascending, with still-open segments last ordered by start_at."""
    if row["end_at"] is not None:
        return (0, row["end_at"], row["created_at"], row["_seq"])
    return (1, row["start_at"], row["created_at"], row["_seq"])


@bp.get("/car-hire/hire-movements")
@endpoint(roles=db.ALL_ROLES)
def list_movements():
    response.page_params()
    status = shapes.q_enum("status", db.MOVEMENT_STATUS)
    car_id = shapes.q_str("car_id")
    handling = shapes.q_str("handling_road_id")
    owner = shapes.q_str("owner_road_id")
    received = shapes.q_str("received_event_id")
    delivered = shapes.q_str("delivered_event_id")
    cycle_id = shapes.q_str("settlement_cycle_id")
    hire_liable = shapes.q_bool("hire_liable")
    reclaim_locked = shapes.q_bool("reclaim_locked")
    end_from = shapes.q_dt("end_at_from")
    end_to = shapes.q_dt("end_at_to")

    rows = list(db.movements.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if car_id is not None:
        rows = [r for r in rows if r["car_id"] == car_id]
    if handling is not None:
        rows = [r for r in rows if r["handling_road_id"] == handling]
    if owner is not None:
        rows = [r for r in rows if r["owner_road_id"] == owner]
    if received is not None:
        rows = [r for r in rows if r["received_event_id"] == received]
    if delivered is not None:
        rows = [r for r in rows if r["delivered_event_id"] == delivered]
    if cycle_id is not None:
        rows = [r for r in rows if r["settlement_cycle_id"] == cycle_id]
    if hire_liable is not None:
        rows = [r for r in rows if bool(r["hire_liable"]) == hire_liable]
    if reclaim_locked is not None:
        rows = [r for r in rows if bool(r["reclaim_locked"]) == reclaim_locked]
    if end_from is not None:
        rows = [r for r in rows if r["end_at"] is not None and r["end_at"] >= end_from]
    if end_to is not None:
        rows = [r for r in rows if r["end_at"] is not None and r["end_at"] <= end_to]
    rows.sort(key=_movement_sort_key)
    return response.paginate(rows, serialize.movement)


@bp.get("/car-hire/hire-movements/<movement_id>")
@endpoint(roles=db.ALL_ROLES, path_params=[("movement_id", "movement")])
def read_movement(movement):
    middleware.party_movement(movement)
    return response.ok(serialize.movement(movement))
