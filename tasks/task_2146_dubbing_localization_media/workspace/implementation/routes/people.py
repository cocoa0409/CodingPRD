"""Voice talents and studios."""
from flask import Blueprint, request

from auth import ALL_ROLES, auth
from domain import get_studio, get_talent
from errors import ApiError
from responses import created, ok
from store import TERRITORIES, db, new_row, serialize, touch
from validate import body, v_array, v_enum, v_int, v_string

bp = Blueprint("people", __name__)

UNION_STATUSES = ("UNION", "NON_UNION")


@bp.post("/voice-talents")
@auth("CastingDirector")
def create_voice_talent():
    data = body()
    full_name = v_string(data, "full_name")
    language_code = v_string(data, "language_code")
    base_rate = v_int(data, "base_rate_cents_per_hour", minimum=1)
    licensed = v_array(data, "licensed_territories", non_empty=True, member_enum=TERRITORIES)
    union_status = v_enum(data, "union_status", UNION_STATUSES, required=False, default="NON_UNION")
    max_daily = v_int(data, "max_daily_recorded_minutes", required=False, default=300, minimum=1)

    row = new_row({
        "full_name": full_name,
        "language_code": language_code,
        "union_status": union_status,
        "base_rate_cents_per_hour": base_rate,
        "licensed_territories": list(licensed),
        "max_daily_recorded_minutes": max_daily,
        "held_minutes": 0,
        "recorded_minutes": 0,
        "status": "ACTIVE",
    })
    db.voice_talents[row["id"]] = row
    return created(serialize(row))


@bp.get("/voice-talents/<talent_id>")
@auth(*ALL_ROLES)
def read_voice_talent(talent_id):
    return ok(serialize(get_talent(talent_id)))


@bp.post("/voice-talents/<talent_id>/set-status")
@auth("CastingDirector")
def set_talent_status(talent_id):
    talent = get_talent(talent_id)
    data = body()
    to_status = v_enum(data, "to_status", ("ACTIVE", "SUSPENDED"))
    if to_status == "SUSPENDED":
        if talent["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
    else:
        if talent["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE")
    talent["status"] = to_status
    touch(talent)
    return ok(serialize(talent))


@bp.post("/studios")
@auth("ProductionCoordinator")
def create_studio():
    data = body()
    name = v_string(data, "name")
    territory = v_enum(data, "territory", TERRITORIES)
    hourly_rate_cents = v_int(data, "hourly_rate_cents", minimum=1)
    turnaround = v_int(data, "turnaround_buffer_minutes", required=False, default=30, minimum=0)
    daily_capacity = v_int(data, "daily_capacity_minutes", required=False, default=600, minimum=1)

    row = new_row({
        "name": name,
        "territory": territory,
        "hourly_rate_cents": hourly_rate_cents,
        "turnaround_buffer_minutes": turnaround,
        "daily_capacity_minutes": daily_capacity,
        "booked_minutes": 0,
        "status": "ACTIVE",
    })
    db.studios[row["id"]] = row
    return created(serialize(row))


@bp.get("/studios/<studio_id>")
@auth(*ALL_ROLES)
def read_studio(studio_id):
    return ok(serialize(get_studio(studio_id)))


@bp.post("/studios/<studio_id>/set-status")
@auth("ProductionCoordinator")
def set_studio_status(studio_id):
    studio = get_studio(studio_id)
    data = body()
    to_status = v_enum(data, "to_status", ("ACTIVE", "MAINTENANCE"))
    if to_status == "MAINTENANCE":
        if studio["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        for session in db.sessions.values():
            if session["studio_id"] == studio["id"] and session["status"] == "IN_PROGRESS":
                raise ApiError("ERR_INVALID_STATE")
    else:
        if studio["status"] != "MAINTENANCE":
            raise ApiError("ERR_INVALID_STATE")
    studio["status"] = to_status
    touch(studio)
    return ok(serialize(studio))
