"""ShowcaseEvent routes."""
from flask import Blueprint, request
from store import store, fresh, stamp, parse_dt
from middleware import auth, json_body, require_fields, pagination_params
from response import success_obj, success_list
from errors import (
    not_found, invalid_request, raise_err, ERR_INVALID_STATE,
    ERR_VENUE_SLOT_CONFLICT, ERR_VENUE_CAPACITY_EXCEEDED, ERR_GRADES_INCOMPLETE,
)
from services import venue_conflict, credit_enrollment

bp = Blueprint("showcases", __name__)

ROLES = ["ProgramDirector", "CastingDirector", "Registrar", "Student"]


def _get_showcase(sid):
    s = store.showcases.get(sid)
    if not s:
        not_found("showcase not found")
    return s


@bp.post("/showcases")
def create_showcase():
    auth(["ProgramDirector"])
    body = json_body()
    require_fields(body, ["level_id", "term_id", "performer_enrollment_ids"])
    level = store.levels.get(body["level_id"])
    if not level:
        not_found("level not found")
    term = store.terms.get(body["term_id"])
    if not term:
        not_found("term not found")
    if not isinstance(body["performer_enrollment_ids"], list):
        invalid_request("performer_enrollment_ids must be an array")
    slot_id = body.get("venue_slot_id")
    if slot_id is not None and slot_id not in store.venue_slots:
        not_found("venue slot not found")
    sc = fresh({
        "level_id": body["level_id"],
        "venue_slot_id": slot_id,
        "term_id": body["term_id"],
        "is_industry": bool(body.get("is_industry", False)),
        "performer_enrollment_ids": list(body["performer_enrollment_ids"]),
        "grade_by_enrollment": dict(body.get("grade_by_enrollment") or {}),
        "status": "PLANNED",
    })
    store.showcases[sc["id"]] = sc
    return success_obj(sc, 201)


@bp.get("/showcases")
def list_showcases():
    auth(ROLES)
    limit, offset = pagination_params()
    items = list(store.showcases.values())
    if request.args.get("level_id"):
        items = [x for x in items if x["level_id"] == request.args["level_id"]]
    if request.args.get("term_id"):
        items = [x for x in items if x["term_id"] == request.args["term_id"]]
    if request.args.get("is_industry") is not None:
        val = request.args["is_industry"].lower() == "true"
        items = [x for x in items if x["is_industry"] == val]
    if request.args.get("venue_slot_id"):
        items = [x for x in items if x.get("venue_slot_id") == request.args["venue_slot_id"]]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/showcases/<sid>")
def get_showcase(sid):
    auth(ROLES)
    return success_obj(_get_showcase(sid))


@bp.post("/showcases/<sid>/schedule")
def schedule(sid):
    auth(["ProgramDirector"])
    sc = _get_showcase(sid)
    if sc["status"] != "PLANNED":
        raise_err(ERR_INVALID_STATE, "showcase must be PLANNED")
    slot = store.venue_slots.get(sc.get("venue_slot_id"))
    if not slot:
        not_found("venue slot not found")
    if slot["status"] != "AVAILABLE":
        raise_err(ERR_VENUE_SLOT_CONFLICT, "venue slot is not AVAILABLE")
    start = parse_dt(slot["start_utc"])
    end = parse_dt(slot["end_utc"])
    if venue_conflict(start, end, slot["venue_name"], exclude_id=slot["id"]):
        raise_err(ERR_VENUE_SLOT_CONFLICT, "slot conflicts with existing bookings")
    if slot["capacity"] < len(sc["performer_enrollment_ids"]):
        raise_err(ERR_VENUE_CAPACITY_EXCEEDED, "venue capacity below performer count")
    sc["status"] = "SCHEDULED"
    stamp(sc)
    slot["status"] = "RESERVED"
    stamp(slot)
    return success_obj(sc)


@bp.post("/showcases/<sid>/stage")
def stage(sid):
    auth(["ProgramDirector"])
    sc = _get_showcase(sid)
    if sc["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "showcase must be SCHEDULED")
    body = json_body()
    grades = body.get("grade_by_enrollment")
    if not isinstance(grades, dict):
        invalid_request("grade_by_enrollment must be an object")
    for eid in sc["performer_enrollment_ids"]:
        if eid not in grades:
            raise_err(ERR_GRADES_INCOMPLETE, "grades must cover every performer")
    for k, v in grades.items():
        if v not in ("PASS", "FAIL"):
            invalid_request("grades must be PASS or FAIL")
    sc["grade_by_enrollment"] = dict(grades)
    sc["status"] = "STAGED"
    stamp(sc)
    slot = store.venue_slots.get(sc.get("venue_slot_id"))
    if slot and slot["status"] == "RESERVED":
        slot["status"] = "BOOKED"
        stamp(slot)
    for eid, grade in grades.items():
        e = store.enrollments.get(eid)
        if not e:
            continue
        if grade == "PASS" and e["status"] == "COMPLETED":
            credit_enrollment(e, showcase_id=sc["id"])
    return success_obj(sc)


@bp.post("/showcases/<sid>/archive")
def archive(sid):
    auth(["ProgramDirector"])
    sc = _get_showcase(sid)
    if sc["status"] != "STAGED":
        raise_err(ERR_INVALID_STATE, "showcase must be STAGED")
    sc["status"] = "ARCHIVED"
    stamp(sc)
    slot = store.venue_slots.get(sc.get("venue_slot_id"))
    if slot and slot["status"] in ("RESERVED", "BOOKED"):
        slot["status"] = "RELEASED"
        stamp(slot)
    return success_obj(sc)


@bp.post("/showcases/<sid>/cancel")
def cancel(sid):
    auth(["ProgramDirector"])
    sc = _get_showcase(sid)
    if sc["status"] not in ("PLANNED", "SCHEDULED"):
        raise_err(ERR_INVALID_STATE, "showcase must be PLANNED or SCHEDULED")
    was_scheduled = sc["status"] == "SCHEDULED"
    sc["status"] = "CANCELLED"
    stamp(sc)
    if was_scheduled:
        slot = store.venue_slots.get(sc.get("venue_slot_id"))
        if slot and slot["status"] == "RESERVED":
            slot["status"] = "RELEASED"
            stamp(slot)
    return success_obj(sc)
