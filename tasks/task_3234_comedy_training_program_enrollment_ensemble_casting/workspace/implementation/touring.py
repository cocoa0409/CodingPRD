"""TouringAssignment routes."""
from flask import Blueprint, request
from store import store, fresh, stamp, parse_dt, logical_now
from middleware import auth, json_body, require_fields, pagination_params, require_student_owner
from response import success_obj, success_list
from errors import (
    not_found, invalid_request, raise_err, ERR_INVALID_STATE, ERR_DEADLINE_PASSED,
    ERR_TOUR_WINDOW_INVALID, ERR_UNDERSTUDY_INELIGIBLE,
)

bp = Blueprint("touring", __name__)

ROLES_READ = ["CastingDirector", "ProgramDirector", "Student"]


def _get(tid):
    t = store.tours.get(tid)
    if not t:
        not_found("touring assignment not found")
    return t


def _understudy_ok(understudy_id, cast):
    stu = store.students.get(understudy_id)
    if not stu:
        return False
    if stu.get("is_alumni"):
        return True
    # CREDITED enrollment in the cast's track (§3.9). A cast has no track field of
    # its own; its track is the track of the cohort its members were cast from.
    # A CREDITED enrollment credits the student in the track of that enrollment's
    # section level, so an understudy with any CREDITED enrollment whose track
    # matches a cohort track that backs this cast qualifies; with no cohort linkage
    # recorded, any CREDITED enrollment in a known track qualifies.
    cast_tracks = {
        c.get("_track") for c in store.cohorts.values()
        if understudy_id in (c.get("_admitted_ids") or []) and c.get("_track")
    }
    for e in store.enrollments.values():
        if e["student_id"] != understudy_id or e["status"] != "CREDITED":
            continue
        section = store.sections.get(e["section_id"])
        level = store.levels.get(section["level_id"]) if section else None
        track = level.get("track") if level else None
        if not cast_tracks or track in cast_tracks:
            return True
    return False


def _validate_window(cast_id, start, end, exclude_id=None):
    if start >= end:
        raise_err(ERR_TOUR_WINDOW_INVALID, "tour_start_utc must be before tour_end_utc")
    for t in store.tours.values():
        if t["ensemble_cast_id"] != cast_id or t["id"] == exclude_id:
            continue
        if t["status"] in ("DECLINED", "REPLACED"):
            continue
        ts = parse_dt(t["tour_start_utc"])
        te = parse_dt(t["tour_end_utc"])
        if start < te and ts < end:
            raise_err(ERR_TOUR_WINDOW_INVALID, "tour overlaps another tour on this cast")


@bp.post("/touring-assignments")
def create_tour():
    auth(["CastingDirector"])
    body = json_body()
    require_fields(body, ["ensemble_cast_id", "principal_student_id", "understudy_student_id", "tour_start_utc", "tour_end_utc"])
    cast = store.casts.get(body["ensemble_cast_id"])
    if not cast:
        not_found("ensemble cast not found")
    if body["principal_student_id"] not in store.students:
        not_found("principal student not found")
    if body["understudy_student_id"] not in store.students:
        not_found("understudy student not found")
    start = parse_dt(body["tour_start_utc"])
    end = parse_dt(body["tour_end_utc"])
    _validate_window(cast["id"], start, end)
    if end <= logical_now():
        raise_err(ERR_DEADLINE_PASSED, "tour window has already passed")
    if not _understudy_ok(body["understudy_student_id"], cast):
        raise_err(ERR_UNDERSTUDY_INELIGIBLE, "understudy fails coverage predicate")
    tour = fresh({
        "ensemble_cast_id": cast["id"],
        "principal_student_id": body["principal_student_id"],
        "understudy_student_id": body["understudy_student_id"],
        "tour_start_utc": body["tour_start_utc"],
        "tour_end_utc": body["tour_end_utc"],
        "travel_committed": False,
        "status": "PROPOSED",
    })
    store.tours[tour["id"]] = tour
    return success_obj(tour, 201)


@bp.get("/touring-assignments")
def list_tours():
    auth(ROLES_READ)
    limit, offset = pagination_params()
    items = list(store.tours.values())
    for f in ("ensemble_cast_id", "principal_student_id", "understudy_student_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [x for x in items if x.get(f) == v]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/touring-assignments/<tid>")
def get_tour(tid):
    user_id, role = auth(ROLES_READ)
    t = _get(tid)
    if role == "Student" and user_id not in (t["principal_student_id"], t["understudy_student_id"]):
        not_found("touring assignment not found")
    return success_obj(t)


@bp.post("/touring-assignments/<tid>/accept")
def accept(tid):
    user_id, role = auth(["Student"])
    t = _get(tid)
    if t["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "assignment must be PROPOSED")
    if user_id != t["principal_student_id"]:
        raise_err(ERR_INVALID_STATE, "only the principal may accept")
    cast = store.casts.get(t["ensemble_cast_id"])
    if not _understudy_ok(t["understudy_student_id"], cast):
        raise_err(ERR_UNDERSTUDY_INELIGIBLE, "understudy fails coverage predicate")
    t["status"] = "ACCEPTED"
    t["travel_committed"] = True
    stamp(t)
    return success_obj(t)


@bp.post("/touring-assignments/<tid>/decline")
def decline(tid):
    user_id, role = auth(["Student"])
    t = _get(tid)
    if t["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "assignment must be PROPOSED")
    if user_id != t["principal_student_id"]:
        raise_err(ERR_INVALID_STATE, "only the principal may decline")
    t["status"] = "DECLINED"
    stamp(t)
    return success_obj(t)


@bp.post("/touring-assignments/<tid>/sync")
def sync(tid):
    auth(["CastingDirector", "ProgramDirector"])
    t = _get(tid)
    now = logical_now()
    start = parse_dt(t["tour_start_utc"])
    end = parse_dt(t["tour_end_utc"])
    if t["status"] == "ACCEPTED" and now >= start:
        t["status"] = "ON_TOUR"
        stamp(t)
    if t["status"] == "ON_TOUR" and now >= end:
        t["status"] = "RETURNED"
        stamp(t)
    return success_obj(t)


@bp.post("/touring-assignments/<tid>/replace")
def replace(tid):
    auth(["CastingDirector"])
    t = _get(tid)
    if t["status"] != "ACCEPTED":
        raise_err(ERR_INVALID_STATE, "assignment must be ACCEPTED")
    body = json_body()
    require_fields(body, ["new_principal_student_id", "new_understudy_student_id"])
    if body["new_principal_student_id"] not in store.students:
        not_found("new principal not found")
    if body["new_understudy_student_id"] not in store.students:
        not_found("new understudy not found")
    cast = store.casts.get(t["ensemble_cast_id"])
    if not _understudy_ok(body["new_understudy_student_id"], cast):
        raise_err(ERR_UNDERSTUDY_INELIGIBLE, "understudy fails coverage predicate")
    t["status"] = "REPLACED"
    t["travel_committed"] = False
    stamp(t)
    new_tour = fresh({
        "ensemble_cast_id": t["ensemble_cast_id"],
        "principal_student_id": body["new_principal_student_id"],
        "understudy_student_id": body["new_understudy_student_id"],
        "tour_start_utc": t["tour_start_utc"],
        "tour_end_utc": t["tour_end_utc"],
        "travel_committed": False,
        "status": "PROPOSED",
    })
    store.tours[new_tour["id"]] = new_tour
    return success_obj(t)
