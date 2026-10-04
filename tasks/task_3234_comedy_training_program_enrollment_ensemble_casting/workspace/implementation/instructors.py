"""Instructor routes."""
from flask import Blueprint
from store import store, fresh
from middleware import auth, json_body, require_fields, pagination_params
from response import success_obj, success_list
from errors import not_found, invalid_request

bp = Blueprint("instructors", __name__)

TRACKS = {"IMPROV", "SKETCH", "STANDUP", "CONSERVATORY"}


@bp.post("/instructors")
def create_instructor():
    auth(["ProgramDirector"])
    body = json_body()
    require_fields(body, ["display_name", "home_track", "certified_tracks"])
    if body["home_track"] not in TRACKS:
        invalid_request("invalid home_track")
    if not isinstance(body["certified_tracks"], list):
        invalid_request("certified_tracks must be an array")
    for t in body["certified_tracks"]:
        if t not in TRACKS:
            invalid_request("invalid track in certified_tracks")
    maxh = body.get("max_weekly_hours", 20)
    if not isinstance(maxh, int) or isinstance(maxh, bool) or maxh < 0:
        invalid_request("max_weekly_hours must be a non-negative integer")
    inst = fresh({
        "display_name": body["display_name"],
        "home_track": body["home_track"],
        "certified_tracks": body["certified_tracks"],
        "max_weekly_hours": maxh,
        "status": "ACTIVE",
    })
    store.instructors[inst["id"]] = inst
    return success_obj(inst, 201)


@bp.get("/instructors")
def list_instructors():
    auth(["ProgramDirector", "Registrar"])
    limit, offset = pagination_params()
    items = sorted(store.instructors.values(), key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/instructors/<instructorId>")
def get_instructor(instructorId):
    auth(["ProgramDirector", "Registrar"])
    inst = store.instructors.get(instructorId)
    if not inst:
        not_found("instructor not found")
    return success_obj(inst)
