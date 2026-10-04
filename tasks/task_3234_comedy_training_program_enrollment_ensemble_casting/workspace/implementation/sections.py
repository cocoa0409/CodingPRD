"""CourseSection routes."""
from flask import Blueprint, request
from store import store, fresh, stamp
from middleware import auth, json_body, require_fields, pagination_params
from response import success_obj, success_list
from errors import not_found, invalid_request, raise_err, ERR_INVALID_STATE, ERR_INSTRUCTOR_UNAVAILABLE
from services import recompute_section_counts, cancel_section_cascade

bp = Blueprint("sections", __name__)

ROLES_READ = ["ProgramDirector", "Registrar", "Student", "PlacementOfficer"]


def _check_instructor(instructor_id, level, weekly_hours, exclude_section_id=None):
    inst = store.instructors.get(instructor_id)
    if not inst:
        not_found("instructor not found")
    track = level["track"] if level else None
    if track not in (inst.get("certified_tracks") or []):
        raise_err(ERR_INSTRUCTOR_UNAVAILABLE, "instructor not certified for this track")
    load = 0
    for sec in store.sections.values():
        if sec.get("instructor_id") == instructor_id and sec["id"] != exclude_section_id:
            if sec["status"] not in ("CANCELLED", "COMPLETED"):
                load += sec.get("weekly_hours", 0)
    if load + weekly_hours > inst.get("max_weekly_hours", 20):
        raise_err(ERR_INSTRUCTOR_UNAVAILABLE, "instructor weekly load would exceed max")


@bp.post("/sections")
def create_section():
    auth(["ProgramDirector"])
    body = json_body()
    require_fields(body, ["term_id", "level_id", "capacity", "tuition_cents", "weekly_hours"])
    term = store.terms.get(body["term_id"])
    if not term:
        not_found("term not found")
    level = store.levels.get(body["level_id"])
    if not level:
        not_found("level not found")
    capacity = body["capacity"]
    if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity <= 0:
        invalid_request("capacity must be a positive integer")
    for f in ("tuition_cents", "weekly_hours"):
        if not isinstance(body[f], int) or isinstance(body[f], bool):
            invalid_request(f"{f} must be an integer")
    instructor_id = body.get("instructor_id")
    if instructor_id is not None:
        _check_instructor(instructor_id, level, body["weekly_hours"])
    sec = fresh({
        "term_id": body["term_id"],
        "level_id": body["level_id"],
        "instructor_id": instructor_id,
        "capacity": capacity,
        "tuition_cents": body["tuition_cents"],
        "weekly_hours": body["weekly_hours"],
        "enrolled_count": 0,
        "waitlist_count": 0,
        "status": "DRAFT",
    })
    store.sections[sec["id"]] = sec
    return success_obj(sec, 201)


@bp.get("/sections")
def list_sections():
    auth(ROLES_READ)
    limit, offset = pagination_params()
    items = list(store.sections.values())
    if request.args.get("term_id"):
        items = [x for x in items if x["term_id"] == request.args["term_id"]]
    if request.args.get("level_id"):
        items = [x for x in items if x["level_id"] == request.args["level_id"]]
    if request.args.get("instructor_id"):
        items = [x for x in items if x.get("instructor_id") == request.args["instructor_id"]]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/sections/<sectionId>")
def get_section(sectionId):
    auth(ROLES_READ)
    sec = store.sections.get(sectionId)
    if not sec:
        not_found("section not found")
    recompute_section_counts(sec)
    return success_obj(sec)


@bp.patch("/sections/<sectionId>")
def patch_section(sectionId):
    auth(["ProgramDirector"])
    sec = store.sections.get(sectionId)
    if not sec:
        not_found("section not found")
    body = json_body()
    new_instructor = body.get("instructor_id", sec.get("instructor_id"))
    new_hours = body.get("weekly_hours", sec["weekly_hours"])
    if "weekly_hours" in body and (not isinstance(new_hours, int) or isinstance(new_hours, bool)):
        invalid_request("weekly_hours must be an integer")
    if "capacity" in body:
        cap = body["capacity"]
        if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
            invalid_request("capacity must be a positive integer")
        sec["capacity"] = cap
    if new_instructor is not None:
        level = store.levels.get(sec["level_id"])
        _check_instructor(new_instructor, level, new_hours, exclude_section_id=sec["id"])
        sec["instructor_id"] = new_instructor
    if "weekly_hours" in body:
        sec["weekly_hours"] = new_hours
    stamp(sec)
    return success_obj(sec)


@bp.post("/sections/<sectionId>/cancel")
def cancel_section(sectionId):
    auth(["ProgramDirector"])
    sec = store.sections.get(sectionId)
    if not sec:
        not_found("section not found")
    if sec["status"] not in ("DRAFT", "OPEN"):
        raise_err(ERR_INVALID_STATE, "only DRAFT or OPEN sections may be cancelled")
    sec["status"] = "CANCELLED"
    stamp(sec)
    cancel_section_cascade(sec)
    return success_obj(sec)
