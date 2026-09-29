"""Canvass-area endpoints (PRD 3.3)."""
from datetime import timedelta

from flask import Blueprint

import auth
import calc
import engine
import envelope
import fetch
import serialize
import store
import validators as v
from errors import ApiError
from routes_agency import require_onboarded
from store import db, now

bp = Blueprint("area", __name__)

AREA_STATUSES = ("DRAFT", "LOCKED", "INVALIDATED")


@bp.post("/neighborhood-safety/request-areas")
def create_area():
    actor = auth.authenticate(("Officer",))
    body = v.body_json()
    v.require_present(body, "agency_id")
    agency = fetch.must("Agency", body.get("agency_id"))
    center_x = v.coord_field(body, "center_x_m")
    center_y = v.coord_field(body, "center_y_m")
    radius = v.int_field(body, "radius_m", lo=50)
    window_start = v.dt_field(body, "window_start_utc")
    window_end = v.dt_field(body, "window_end_utc")
    area_label = v.str_field(body, "area_label", required=False, default=None,
                             allow_empty=True)
    officer = auth.require_officer(actor)
    if officer["agency_id"] != agency["id"]:
        auth.mismatch("Acting officer does not belong to this agency")
    require_onboarded(agency)

    # rule 34 -- window sanity
    if window_start >= window_end:
        raise ApiError("ERR_INVALID_WINDOW",
                       "window_start_utc must fall strictly before window_end_utc")
    if window_end > now():
        raise ApiError("ERR_INVALID_WINDOW",
                       "window_end_utc must fall at or before the current clock")
    if (window_end - window_start).total_seconds() > calc.AREA_MAX_WINDOW_HOURS * 3600:
        raise ApiError("ERR_INVALID_WINDOW",
                       "The footage window may not exceed 168 hours")
    # rule 37 -- radius ceiling
    if radius > calc.AREA_MAX_RADIUS_M:
        raise ApiError("ERR_AREA_RADIUS_EXCEEDS_LIMIT",
                       "radius_m may not exceed %d metres" % calc.AREA_MAX_RADIUS_M)
    # rule 38 -- repeat-canvass rule
    buffer_delta = timedelta(hours=calc.AREA_CANVASS_BUFFER_HOURS)
    for other in db.request_areas.values():
        if other["agency_id"] != agency["id"]:
            continue
        if other["status"] == "INVALIDATED":
            continue
        if calc.dist_sq(center_x, center_y, other["center_x_m"],
                        other["center_y_m"]) > calc.AREA_PROXIMITY_M ** 2:
            continue
        extended_end = other["window_end_utc"] + buffer_delta
        if window_start <= extended_end and other["window_start_utc"] <= window_end:
            raise ApiError("ERR_AREA_CANVASS_OVERLAP",
                           "This agency has already canvassed nearby in this window")

    row = engine.new_row({
        "agency_id": agency["id"],
        "created_by_officer_id": officer["id"],
        "area_label": area_label,
        "center_x_m": center_x,
        "center_y_m": center_y,
        "radius_m": radius,
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "status": "DRAFT",
        "locked_at": None,
        "effective_min_devices": None,
        "eligible_device_count": 0,
        "derived_request_count": 0,
        "invalidated_reason": None,
    })
    db.request_areas[row["id"]] = row
    return envelope.created(serialize.dump("RequestArea", row))


@bp.post("/neighborhood-safety/request-areas/<area_id>/lock")
def lock_area(area_id):
    actor = auth.authenticate(("Officer",))
    area = fetch.must("RequestArea", area_id)
    agency = db.agencies.get(area["agency_id"])
    officer = auth.require_officer_is(actor, area["created_by_officer_id"],
                                     area["agency_id"])
    if officer is not None and officer["duty_role"] not in ("REQUESTER",
                                                            "DUAL_ROLE"):
        auth.sod("An auditor may not lock a canvass area")
    require_onboarded(agency)
    if area["status"] != "DRAFT":
        raise ApiError("ERR_AREA_ALREADY_LOCKED",
                       "Area %s is no longer in DRAFT" % area["id"])

    locked_at = now()
    roster = calc.build_roster(area, locked_at)
    db.rosters[area["id"]] = roster
    area["locked_at"] = locked_at
    area["status"] = "LOCKED"
    area["eligible_device_count"] = len(roster)
    area["effective_min_devices"] = calc.effective_min_devices(agency, area)
    engine.touch(area)
    return envelope.ok(serialize.dump("RequestArea", area))


@bp.get("/neighborhood-safety/request-areas/<area_id>")
def read_area(area_id):
    auth.authenticate(("PlatformAdmin", "AgencyAdmin", "Officer"))
    area = fetch.must("RequestArea", area_id)
    return envelope.ok(serialize.dump("RequestArea", area))


@bp.get("/neighborhood-safety/request-areas")
def list_areas():
    auth.authenticate(("PlatformAdmin", "AgencyAdmin", "Officer"))
    limit, offset = v.pagination()
    agency_id = v.query_str("agency_id")
    officer_id = v.query_str("created_by_officer_id")
    status = v.query_enum("status", AREA_STATUSES)
    rows = list(db.request_areas.values())
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    if officer_id is not None:
        rows = [r for r in rows if r["created_by_officer_id"] == officer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = store.by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return envelope.collection(serialize.dump_all("RequestArea", page), limit,
                               offset, total)
