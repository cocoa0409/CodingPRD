"""Educator certification routes (PRD sec 3.10) and the logical-clock endpoint."""
from flask import Blueprint

import resolve
import serialize
import services
import shape
from auth import endpoint
from envelope import created, ok
from errors import ApiError
from store import (CERTIFICATION_ROUTES, ROLES, ROUTE_HOUR_FLOOR, db, fmt_date,
                   stamp_new, touch)

bp = Blueprint("educators", __name__)
DIRECTOR = ("CteDirector",)
REVIEWER = ("StateComplianceReviewer",)
DIRECTOR_REVIEWER = ("CteDirector", "StateComplianceReviewer")


# ------------------------------------------------------------------ reads
@bp.get("/cte/educators/<educator_id>")
@endpoint(DIRECTOR_REVIEWER)
def get_educator(educator_id):
    educator = resolve.educator(educator_id)
    services.refresh_educator(educator)
    return ok(serialize.educator(educator))


# ------------------------------------------------------------------ writes
@bp.post("/cte/programs-of-study/<pos_id>/educators")
@endpoint(DIRECTOR)
def assign_educator(pos_id):
    data = shape.body()
    full_name = shape.req_string(data, "full_name", max_len=200)
    route = shape.req_enum(data, "certification_route", CERTIFICATION_ROUTES)
    claimed = shape.req_int(data, "claimed_industry_hours", minimum=0)
    expires_on = shape.req_date(data, "credential_expires_on")
    program = resolve.program(pos_id)
    services.refresh_clna(program)
    educator = stamp_new({
        "pos_id": pos_id,
        "full_name": full_name,
        "certification_route": route,
        "claimed_industry_hours": claimed,
        "verified_industry_hours": 0,
        "credential_expires_on": fmt_date(expires_on),
        "status": "PROVISIONAL",
    })
    db.educators[educator["id"]] = educator
    touch(program)
    return created(serialize.educator(educator))


@bp.post("/cte/educators/<educator_id>/verify-industry-hours")
@endpoint(REVIEWER)
def verify_industry_hours(educator_id):
    data = shape.body()
    verified_hours = shape.req_int(data, "verified_hours")
    shape.req_string(data, "verification_source", max_len=400)
    educator = resolve.educator(educator_id)
    services.refresh_educator(educator)

    if educator["status"] == "LAPSED":
        raise ApiError("ERR_INVALID_EDUCATOR_STATE",
                       "LAPSED is terminal; industry hours can no longer be "
                       "verified for this educator.")
    total = int(educator["verified_industry_hours"]) + verified_hours
    if verified_hours < 1 or total > int(educator["claimed_industry_hours"]):
        raise ApiError("ERR_INDUSTRY_HOURS_EXCEED_CLAIM",
                       "Each tranche must be worth at least 1 hour and the "
                       "running total may not exceed claimed_industry_hours.")

    educator["verified_industry_hours"] = total
    floor = ROUTE_HOUR_FLOOR[educator["certification_route"]]
    if educator["status"] == "PROVISIONAL" and total >= floor:
        educator["status"] = "ELIGIBLE"
    touch(educator)
    return ok(serialize.educator(educator))


# ------------------------------------------------------------------ clock
@bp.post("/_clock/set_current_utc")
@endpoint(ROLES)
def set_clock():
    data = shape.body()
    instant = shape.req_instant(data, "to_iso8601")
    db.clock = instant
    return ok({})
