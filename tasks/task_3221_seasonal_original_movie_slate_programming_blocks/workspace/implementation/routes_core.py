"""Clock + Studios + Seasons routes."""
from flask import Blueprint, request

import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_SEASON_HAS_OPEN_TITLES, ERR_INVALID_WINDOW,
)
from helpers import (
    new_id, now_iso, parse_dt, parse_int, parse_str, parse_pagination,
    paginate, get_or_404, require_fields,
)
from middleware import require_auth
from response import success_object, success_list
from services import serialize, bump, cascade_season_archive, studio_of_season

bp = Blueprint("core", __name__)

ALL_ROLES = ["PlatformAdmin", "SlatePlanner", "ProductionManager", "TalentAgent",
             "ProgrammingExec", "AdSalesRep", "StreamingCurator", "LicensingManager"]


# ---------------- Clock ----------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_auth(["PlatformAdmin"])
def set_clock():
    body = request.get_json(silent=True) or {}
    require_fields(body, ["current_utc"])
    value = body["current_utc"]
    # validate shape
    parse_dt(value, "current_utc")
    db.set_clock(value)
    return success_object({"current_utc": value}, 200)


# ---------------- Studios ----------------

STUDIO_FIELDS = ["name", "ad_budget_cents"]


@bp.route("/slate/studios", methods=["POST"])
@require_auth(["PlatformAdmin"])
def create_studio():
    body = request.get_json(silent=True) or {}
    require_fields(body, ["name", "ad_budget_cents"])
    name = parse_str(body["name"], "name")
    budget = parse_int(body["ad_budget_cents"], "ad_budget_cents", minimum=0)
    sid = new_id()
    ts = now_iso()
    studio = {
        "id": sid,
        "name": name,
        "ad_budget_cents": budget,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.studios[sid] = studio
    return success_object(serialize(studio, STUDIO_FIELDS), 201)


@bp.route("/slate/studios/<sid>", methods=["GET"])
@require_auth(ALL_ROLES)
def get_studio(sid):
    studio = get_or_404(db.studios, sid, "studio")
    return success_object(serialize(studio, STUDIO_FIELDS), 200)


@bp.route("/slate/studios", methods=["GET"])
@require_auth(ALL_ROLES)
def list_studios():
    limit, offset = parse_pagination(request.args)
    items = list(db.studios.values())
    page, total = paginate(items, limit, offset)
    return success_list([serialize(s, STUDIO_FIELDS) for s in page], limit, offset, total)


# ---------------- Seasons ----------------

SEASON_FIELDS = [
    "studio_id", "year", "label", "required_title_count",
    "air_window_start", "air_window_end", "delivery_deadline",
    "max_shoot_days", "booked_shoot_days", "committed_title_count",
    "premiered_title_count", "status",
]


@bp.route("/slate/seasons", methods=["POST"])
@require_auth(["PlatformAdmin"])
def create_season():
    body = request.get_json(silent=True) or {}
    require_fields(body, [
        "studio_id", "year", "label", "required_title_count",
        "air_window_start", "air_window_end", "delivery_deadline", "max_shoot_days",
    ])
    studio_id = body["studio_id"]
    # Body FK existence check (priority 4)
    studio = db.studios.get(studio_id)
    if studio is None:
        raise err(ERR_NOT_FOUND, "studio not found")
    year = parse_int(body["year"], "year")
    label = parse_str(body["label"], "label")
    required_title_count = parse_int(body["required_title_count"], "required_title_count", minimum=1, maximum=60)
    max_shoot_days = parse_int(body["max_shoot_days"], "max_shoot_days", minimum=1)
    aws_raw = parse_str(body["air_window_start"], "air_window_start")
    awe_raw = parse_str(body["air_window_end"], "air_window_end")
    dd_raw = parse_str(body["delivery_deadline"], "delivery_deadline")
    aws = parse_dt(aws_raw, "air_window_start")
    awe = parse_dt(awe_raw, "air_window_end")
    dd = parse_dt(dd_raw, "delivery_deadline")
    # Window shape: air_window_end > air_window_start AND delivery_deadline < air_window_start
    if awe <= aws:
        raise err(ERR_INVALID_WINDOW, "air_window_end must be after air_window_start")
    if dd >= aws:
        raise err(ERR_INVALID_WINDOW, "delivery_deadline must be before air_window_start")
    sid = new_id()
    ts = now_iso()
    season = {
        "id": sid,
        "studio_id": studio_id,
        "year": year,
        "label": label,
        "required_title_count": required_title_count,
        "air_window_start": aws_raw,
        "air_window_end": awe_raw,
        "delivery_deadline": dd_raw,
        "max_shoot_days": max_shoot_days,
        "booked_shoot_days": 0,
        "committed_title_count": 0,
        "premiered_title_count": 0,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.seasons[sid] = season
    return success_object(serialize(season, SEASON_FIELDS), 201)


@bp.route("/slate/seasons/<sid>", methods=["GET"])
@require_auth(ALL_ROLES)
def get_season(sid):
    season = get_or_404(db.seasons, sid, "season")
    return success_object(serialize(season, SEASON_FIELDS), 200)


@bp.route("/slate/seasons", methods=["GET"])
@require_auth(ALL_ROLES)
def list_seasons():
    limit, offset = parse_pagination(request.args)
    studio_filter = request.args.get("studio_id")
    status_filter = request.args.get("status")
    items = list(db.seasons.values())
    if studio_filter:
        items = [s for s in items if s["studio_id"] == studio_filter]
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(s, SEASON_FIELDS) for s in page], limit, offset, total)


@bp.route("/slate/seasons/<sid>/lock", methods=["POST"])
@require_auth(["ProgrammingExec"])
def lock_season(sid):
    season = get_or_404(db.seasons, sid, "season")
    if season["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Season is not DRAFT")
    season["status"] = "LOCKED"
    bump(season)
    return success_object(serialize(season, SEASON_FIELDS), 200)


@bp.route("/slate/seasons/<sid>/archive", methods=["POST"])
@require_auth(["ProgrammingExec"])
def archive_season(sid):
    season = get_or_404(db.seasons, sid, "season")
    if season["status"] != "LOCKED":
        raise err(ERR_INVALID_STATE, "Season is not LOCKED")
    # preconditions: no non-terminal titles, no PLANNED air slots
    for t in db.titles.values():
        if t["season_id"] == sid and t["status"] not in ("DELIVERED", "REJECTED", "CANCELLED"):
            raise err(ERR_SEASON_HAS_OPEN_TITLES, "Season has open titles")
    for a in db.air_slots.values():
        if a["season_id"] == sid and a["status"] == "PLANNED":
            raise err(ERR_SEASON_HAS_OPEN_TITLES, "Season has planned air slots")
    season["status"] = "ARCHIVED"
    bump(season)
    cascade_season_archive(season)
    return success_object(serialize(season, SEASON_FIELDS), 200)
