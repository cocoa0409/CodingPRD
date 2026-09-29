"""The herd, its immutable health record and its duty-day run (PRD 3.9)."""

from flask import Blueprint

import calc
import derive
import fields
from auth import auth
from derive import Touch, health_event_json, horse_json
from envelope import created, listing, ok
from errors import ApiError
from fields import body, require
from lookup import find, health_event
from store import db

bp = Blueprint("horses", __name__)

HERD_READERS = ("RanchManager", "HorseProgramDirector", "ActivityGuide", "SafetyOfficer")
HORSE_STATUSES = ("IN_SERVICE", "REST", "LAME", "REHAB", "REVIEW_HOLD", "RETIRED")
EVENT_TYPES = (
    "LAMENESS",
    "COLIC",
    "REST_START",
    "REHAB_START",
    "VET_CLEARANCE",
    "FARRIER",
    "RETIREMENT",
)
# event_type -> (accepted from, resulting status)
TRANSITIONS = {
    "LAMENESS": (("IN_SERVICE",), "LAME"),
    "COLIC": (("IN_SERVICE",), "LAME"),
    "REHAB_START": (("LAME",), "REHAB"),
    "VET_CLEARANCE": (("REHAB", "REST"), "IN_SERVICE"),
    "REST_START": (("IN_SERVICE",), "REST"),
    "RETIREMENT": (("IN_SERVICE", "REST", "LAME", "REHAB", "REVIEW_HOLD"), "RETIRED"),
}
OUT_OF_SERVICE_EVENTS = ("LAMENESS", "COLIC", "REST_START", "RETIREMENT")


@bp.post("/horses")
def create_horse():
    auth("HorseProgramDirector")
    data = body()
    require(data, "name", "min_rider_ability", "max_rider_ability", "weight_limit_lb")
    name = fields.as_str(data, "name")
    low = fields.as_enum(data, "min_rider_ability", calc.RIDER_RANKS)
    high = fields.as_enum(data, "max_rider_ability", calc.RIDER_RANKS)
    limit = fields.as_number(data, "weight_limit_lb", exclusive_min=0)
    if calc.RANKS[high] < calc.RANKS[low]:
        fields.bad("max_rider_ability", "must be at or above min_rider_ability")
    for existing in db.horses.values():
        if existing["name"] == name:
            fields.bad("name", "must be unique across the herd")

    row = db.insert(
        "horses",
        {
            "name": name,
            "min_rider_ability": low,
            "max_rider_ability": high,
            "weight_limit_lb": limit,
            "horse_status": "IN_SERVICE",
            "consecutive_duty_days": 0,
            "last_duty_date": None,
            "last_rest_started_on": None,
        },
    )
    return created(horse_json(row))


@bp.get("/horses/<horse_id>")
def read_horse(horse_id):
    auth(*HERD_READERS)
    return ok(horse_json(find("horses", horse_id)))


@bp.get("/horses")
def list_horses():
    auth(*HERD_READERS)
    status = fields.query_enum("horse_status", HORSE_STATUSES)
    return listing(derive.rows_of("horses", horse_status=status), horse_json)


@bp.post("/horses/<horse_id>/health-events")
def file_health_event(horse_id):
    auth("HorseProgramDirector")
    horse = find("horses", horse_id)
    data = body()
    require(data, "event_type", "observed_on")
    event_type = fields.as_enum(data, "event_type", EVENT_TYPES)
    observed_on = fields.as_date(data, "observed_on")
    note = fields.as_str(data, "note")

    current = horse["horse_status"]
    resulting = current
    rule = TRANSITIONS.get(event_type)
    if rule is not None and current in rule[0]:
        resulting = rule[1]

    touch = Touch()
    horse["horse_status"] = resulting
    if event_type == "REST_START":
        horse["last_rest_started_on"] = observed_on
    if event_type in ("REST_START", "VET_CLEARANCE"):
        horse["consecutive_duty_days"] = 0

    if event_type in OUT_OF_SERVICE_EVENTS:
        for seat in db.rows("activity_reservations"):
            if seat.get("assigned_horse_id") != horse["id"]:
                continue
            if seat.get("mount_status") != "ASSIGNED":
                continue
            if not derive.slot_not_started(seat):
                continue
            derive.release_mount(seat, touch)
            touch.add(seat)
            touch.slot(db.activity_slots.get(seat["slot_id"]))

    event = db.insert(
        "horse_health_events",
        {
            "horse_id": horse["id"],
            "event_type": event_type,
            "observed_on": observed_on,
            "note": note,
            "resulting_horse_status": resulting,
        },
        versioned=False,
    )
    touch.add(horse)
    touch.finalize()
    return created(health_event_json(event))


@bp.get("/horse-health-events/<event_id>")
def read_health_event(event_id):
    auth(*HERD_READERS)
    return ok(health_event_json(health_event(event_id)))


@bp.get("/horse-health-events")
def list_health_events():
    auth(*HERD_READERS)
    rows = derive.rows_of(
        "horse_health_events",
        horse_id=fields.query_filter("horse_id"),
        event_type=fields.query_enum("event_type", EVENT_TYPES),
    )
    return listing(rows, health_event_json)
