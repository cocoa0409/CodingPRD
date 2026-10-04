"""Titles routes: create/get/list/approve/reject/cancel/deliver."""
from flask import Blueprint, request

import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_SEASON_NOT_LOCKED, ERR_SLATE_FULL, ERR_BRAND_VIOLATION,
    ERR_NO_WRAPPED_SHOOT, ERR_DELIVERY_LATE, ERR_STALE_VERSION,
)
from helpers import (
    new_id, now_iso, parse_dt, parse_int, parse_str, parse_enum,
    parse_pagination, paginate, get_or_404, require_fields,
)
from middleware import require_auth
from response import success_object, success_list
from services import (
    serialize, bump, recompute_committed_title_count, cascade_title_cancel,
    studio_of_season,
)

bp = Blueprint("titles", __name__)

ALL_ROLES = ["PlatformAdmin", "SlatePlanner", "ProductionManager", "TalentAgent",
             "ProgrammingExec", "AdSalesRep", "StreamingCurator", "LicensingManager"]

TITLE_FIELDS = [
    "season_id", "name", "genre", "tone_rating", "content_flags",
    "duration_minutes", "status", "delivered_at",
]

GENRES = {"ROMANCE", "FAMILY", "MYSTERY", "COMEDY"}
TONES = {"GENTLE", "WARM", "FESTIVE"}
CONTENT_FLAGS = {"VIOLENCE", "ALCOHOL", "GAMBLING", "HORROR"}
BRAND_FORBIDDEN_FLAGS = {"VIOLENCE", "GAMBLING", "HORROR"}


@bp.route("/slate/titles", methods=["POST"])
@require_auth(["SlatePlanner"])
def create_title():
    body = request.get_json(silent=True) or {}
    require_fields(body, ["season_id", "name", "genre", "tone_rating", "duration_minutes"])
    season_id = body["season_id"]
    season = db.seasons.get(season_id)
    if season is None:
        raise err(ERR_NOT_FOUND, "season not found")
    name = parse_str(body["name"], "name")
    genre = parse_enum(body["genre"], "genre", GENRES)
    tone = parse_enum(body["tone_rating"], "tone_rating", TONES)
    flags = body.get("content_flags") or []
    if not isinstance(flags, list):
        raise err(ERR_INVALID_REQUEST, "content_flags must be a list")
    for f in flags:
        parse_enum(f, "content_flags", CONTENT_FLAGS)
    duration = parse_int(body["duration_minutes"], "duration_minutes", minimum=60, maximum=180)
    tid = new_id()
    ts = now_iso()
    title = {
        "id": tid,
        "season_id": season_id,
        "name": name,
        "genre": genre,
        "tone_rating": tone,
        "content_flags": flags,
        "duration_minutes": duration,
        "status": "PITCHED",
        "delivered_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.titles[tid] = title
    return success_object(serialize(title, TITLE_FIELDS), 201)


@bp.route("/slate/titles/<tid>", methods=["GET"])
@require_auth(ALL_ROLES)
def get_title(tid):
    title = get_or_404(db.titles, tid, "title")
    return success_object(serialize(title, TITLE_FIELDS), 200)


@bp.route("/slate/titles", methods=["GET"])
@require_auth(ALL_ROLES)
def list_titles():
    limit, offset = parse_pagination(request.args)
    season_filter = request.args.get("season_id")
    status_filter = request.args.get("status")
    items = list(db.titles.values())
    if season_filter:
        items = [t for t in items if t["season_id"] == season_filter]
    if status_filter:
        items = [t for t in items if t["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(t, TITLE_FIELDS) for t in page], limit, offset, total)


@bp.route("/slate/titles/<tid>/approve", methods=["POST"])
@require_auth(["SlatePlanner"])
def approve_title(tid):
    title = get_or_404(db.titles, tid, "title")
    body = request.get_json(silent=True) or {}
    # OCC: expected_season_version required (priority 5)
    if "expected_season_version" not in body:
        raise err(ERR_INVALID_REQUEST, "expected_season_version is required")
    expected = body["expected_season_version"]
    season = db.seasons[title["season_id"]]
    if expected != season["version"]:
        raise err(ERR_STALE_VERSION, "Season version mismatch")
    # State legality (priority 6)
    if title["status"] != "PITCHED":
        raise err(ERR_INVALID_STATE, "Title is not PITCHED")
    # Brand consistency (priority 7)
    flags = set(title.get("content_flags") or [])
    if flags & BRAND_FORBIDDEN_FLAGS:
        raise err(ERR_BRAND_VIOLATION, "Forbidden content flags")
    if title["tone_rating"] == "FESTIVE" and title["genre"] not in ("ROMANCE", "FAMILY"):
        raise err(ERR_BRAND_VIOLATION, "FESTIVE tone requires ROMANCE or FAMILY genre")
    # Cross-entity referential (priority 9): season must be LOCKED
    if season["status"] != "LOCKED":
        raise err(ERR_SEASON_NOT_LOCKED, "Season is not LOCKED")
    # Aggregate quota (priority 10): slate title count
    if season["committed_title_count"] >= season["required_title_count"]:
        raise err(ERR_SLATE_FULL, "Slate is full")
    title["status"] = "APPROVED"
    bump(title)
    recompute_committed_title_count(title["season_id"])
    bump(season)
    return success_object(serialize(title, TITLE_FIELDS), 200)


@bp.route("/slate/titles/<tid>/reject", methods=["POST"])
@require_auth(["SlatePlanner"])
def reject_title(tid):
    title = get_or_404(db.titles, tid, "title")
    if title["status"] != "PITCHED":
        raise err(ERR_INVALID_STATE, "Title is not PITCHED")
    title["status"] = "REJECTED"
    bump(title)
    return success_object(serialize(title, TITLE_FIELDS), 200)


@bp.route("/slate/titles/<tid>/cancel", methods=["POST"])
@require_auth(["SlatePlanner"])
def cancel_title(tid):
    title = get_or_404(db.titles, tid, "title")
    if title["status"] not in ("APPROVED", "IN_PRODUCTION"):
        raise err(ERR_INVALID_STATE, "Title is not APPROVED or IN_PRODUCTION")
    title["status"] = "CANCELLED"
    bump(title)
    cascade_title_cancel(title)
    return success_object(serialize(title, TITLE_FIELDS), 200)


@bp.route("/slate/titles/<tid>/deliver", methods=["POST"])
@require_auth(["ProductionManager"])
def deliver_title(tid):
    title = get_or_404(db.titles, tid, "title")
    if title["status"] != "IN_PRODUCTION":
        raise err(ERR_INVALID_STATE, "Title is not IN_PRODUCTION")
    # require at least one WRAPPED slot
    has_wrapped = any(
        s for s in db.production_slots.values()
        if s["title_id"] == tid and s["status"] == "WRAPPED"
    )
    if not has_wrapped:
        raise err(ERR_NO_WRAPPED_SHOOT, "No WRAPPED production slot exists")
    season = db.seasons[title["season_id"]]
    clock = parse_dt(db.get_clock())
    deadline = parse_dt(season["delivery_deadline"])
    if clock > deadline:
        raise err(ERR_DELIVERY_LATE, "Logical clock past delivery_deadline")
    title["status"] = "DELIVERED"
    title["delivered_at"] = db.get_clock()
    bump(title)
    return success_object(serialize(title, TITLE_FIELDS), 200)
