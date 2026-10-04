"""Locations and ProductionSlots routes."""
import math
from flask import Blueprint, request

import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_PRODUCTION_QUOTA_EXCEEDED, ERR_LOCATION_OVERLAP, ERR_LOCATION_BLACKOUT,
    ERR_INVALID_WINDOW,
)
from helpers import (
    new_id, now_iso, parse_int, parse_str, parse_pagination, paginate,
    get_or_404, require_fields, parse_dt,
)
from middleware import require_auth
from response import success_object, success_list
from services import serialize, bump, recompute_booked_shoot_days, studio_of_season

bp = Blueprint("production", __name__)

LOC_READ_ROLES = ["PlatformAdmin", "SlatePlanner", "ProductionManager", "ProgrammingExec"]
LOCATION_FIELDS = ["studio_id", "name", "blackout_windows"]
SLOT_FIELDS = ["season_id", "title_id", "location_id", "shoot_start", "shoot_end", "shoot_days", "status"]


def _validate_blackouts(windows):
    if not isinstance(windows, list):
        raise err(ERR_INVALID_REQUEST, "blackout_windows must be a list")
    for w in windows:
        if not isinstance(w, dict) or "start" not in w or "end" not in w:
            raise err(ERR_INVALID_REQUEST, "blackout_windows entries need start/end")
        parse_dt(w["start"], "blackout_windows.start")
        parse_dt(w["end"], "blackout_windows.end")


# ---------------- Locations ----------------

@bp.route("/slate/locations", methods=["POST"])
@require_auth(["ProductionManager"])
def create_location():
    body = request.get_json(silent=True) or {}
    require_fields(body, ["studio_id", "name"])
    studio = db.studios.get(body["studio_id"])
    if studio is None:
        raise err(ERR_NOT_FOUND, "studio not found")
    name = parse_str(body["name"], "name")
    blackouts = body.get("blackout_windows") or []
    _validate_blackouts(blackouts)
    lid = new_id()
    ts = now_iso()
    location = {
        "id": lid,
        "studio_id": body["studio_id"],
        "name": name,
        "blackout_windows": blackouts,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.locations[lid] = location
    return success_object(serialize(location, LOCATION_FIELDS), 201)


@bp.route("/slate/locations/<lid>", methods=["GET"])
@require_auth(LOC_READ_ROLES)
def get_location(lid):
    location = get_or_404(db.locations, lid, "location")
    return success_object(serialize(location, LOCATION_FIELDS), 200)


@bp.route("/slate/locations", methods=["GET"])
@require_auth(LOC_READ_ROLES)
def list_locations():
    limit, offset = parse_pagination(request.args)
    studio_filter = request.args.get("studio_id")
    items = list(db.locations.values())
    if studio_filter:
        items = [l for l in items if l["studio_id"] == studio_filter]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(l, LOCATION_FIELDS) for l in page], limit, offset, total)


# ---------------- Production Slots ----------------

@bp.route("/slate/production-slots", methods=["POST"])
@require_auth(["ProductionManager"])
def create_production_slot():
    body = request.get_json(silent=True) or {}
    require_fields(body, ["title_id", "location_id", "shoot_start", "shoot_end", "shoot_days"])
    title = db.titles.get(body["title_id"])
    if title is None:
        raise err(ERR_NOT_FOUND, "title not found")
    location = db.locations.get(body["location_id"])
    if location is None:
        raise err(ERR_NOT_FOUND, "location not found")
    season = db.seasons[title["season_id"]]
    # cross-studio scope: location's studio must match season's studio
    if location["studio_id"] != season["studio_id"]:
        raise err(ERR_NOT_FOUND, "location and title in different studios")
    ss_raw = parse_str(body["shoot_start"], "shoot_start")
    se_raw = parse_str(body["shoot_end"], "shoot_end")
    ss = parse_dt(ss_raw, "shoot_start")
    se = parse_dt(se_raw, "shoot_end")
    shoot_days = parse_int(body["shoot_days"], "shoot_days", minimum=1)
    # window shape
    if se <= ss:
        raise err(ERR_INVALID_WINDOW, "shoot_end must be after shoot_start")
    # shoot_days == ceil((shoot_end - shoot_start) / 86400s)
    delta_seconds = (se - ss).total_seconds()
    expected_days = math.ceil(delta_seconds / 86400)
    if shoot_days != expected_days:
        raise err(ERR_INVALID_REQUEST, "shoot_days must equal ceil((shoot_end - shoot_start)/86400)")
    # state legality: title must be APPROVED or IN_PRODUCTION to book
    if title["status"] not in ("APPROVED", "IN_PRODUCTION"):
        raise err(ERR_INVALID_STATE, "Title is not APPROVED or IN_PRODUCTION")
    # location overlap (priority 8)
    for slot in db.production_slots.values():
        if slot["location_id"] == location["id"] and slot["status"] == "BOOKED":
            es = parse_dt(slot["shoot_start"])
            ee = parse_dt(slot["shoot_end"])
            if ss < ee and es < se:
                raise err(ERR_LOCATION_OVERLAP, "Overlaps existing BOOKED slot")
    # blackout (priority 8)
    for b in location.get("blackout_windows") or []:
        bs = parse_dt(b["start"])
        be = parse_dt(b["end"])
        if ss < be and bs < se:
            raise err(ERR_LOCATION_BLACKOUT, "Intersects a blackout window")
    # day quota (priority 10): strict >
    booked = sum(
        s["shoot_days"] for s in db.production_slots.values()
        if s["season_id"] == season["id"] and s["status"] == "BOOKED"
    )
    if booked + shoot_days > season["max_shoot_days"]:
        raise err(ERR_PRODUCTION_QUOTA_EXCEEDED, "Would exceed max_shoot_days")
    # all clear — create
    sid = new_id()
    ts = now_iso()
    slot = {
        "id": sid,
        "season_id": season["id"],
        "title_id": body["title_id"],
        "location_id": body["location_id"],
        "shoot_start": ss_raw,
        "shoot_end": se_raw,
        "shoot_days": shoot_days,
        "status": "BOOKED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.production_slots[sid] = slot
    # side effects: season booked_shoot_days, title flips APPROVED -> IN_PRODUCTION
    recompute_booked_shoot_days(season["id"])
    bump(season)
    if title["status"] == "APPROVED":
        title["status"] = "IN_PRODUCTION"
        bump(title)
    return success_object(serialize(slot, SLOT_FIELDS), 201)


@bp.route("/slate/production-slots/<sid>", methods=["GET"])
@require_auth(LOC_READ_ROLES)
def get_production_slot(sid):
    slot = get_or_404(db.production_slots, sid, "production_slot")
    return success_object(serialize(slot, SLOT_FIELDS), 200)


@bp.route("/slate/production-slots", methods=["GET"])
@require_auth(LOC_READ_ROLES)
def list_production_slots():
    limit, offset = parse_pagination(request.args)
    season_filter = request.args.get("season_id")
    title_filter = request.args.get("title_id")
    location_filter = request.args.get("location_id")
    status_filter = request.args.get("status")
    items = list(db.production_slots.values())
    if season_filter:
        items = [s for s in items if s["season_id"] == season_filter]
    if title_filter:
        items = [s for s in items if s["title_id"] == title_filter]
    if location_filter:
        items = [s for s in items if s["location_id"] == location_filter]
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(s, SLOT_FIELDS) for s in page], limit, offset, total)


@bp.route("/slate/production-slots/<sid>/wrap", methods=["POST"])
@require_auth(["ProductionManager"])
def wrap_production_slot(sid):
    slot = get_or_404(db.production_slots, sid, "production_slot")
    if slot["status"] != "BOOKED":
        raise err(ERR_INVALID_STATE, "ProductionSlot is not BOOKED")
    slot["status"] = "WRAPPED"
    bump(slot)
    season = db.seasons[slot["season_id"]]
    recompute_booked_shoot_days(season["id"])
    bump(season)
    return success_object(serialize(slot, SLOT_FIELDS), 200)


@bp.route("/slate/production-slots/<sid>/cancel", methods=["POST"])
@require_auth(["ProductionManager"])
def cancel_production_slot(sid):
    slot = get_or_404(db.production_slots, sid, "production_slot")
    if slot["status"] != "BOOKED":
        raise err(ERR_INVALID_STATE, "ProductionSlot is not BOOKED")
    slot["status"] = "CANCELLED"
    bump(slot)
    season = db.seasons[slot["season_id"]]
    recompute_booked_shoot_days(season["id"])
    bump(season)
    return success_object(serialize(slot, SLOT_FIELDS), 200)
