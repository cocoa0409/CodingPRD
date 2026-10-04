"""ProgramBlocks and AirSlots routes."""
from flask import Blueprint, request

import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_SEASON_NOT_LOCKED, ERR_PREMIERE_CADENCE_VIOLATION, ERR_AIRSLOT_OVERLAP,
    ERR_ENCORE_CAP_EXCEEDED, ERR_INVALID_WINDOW, ERR_AIRSLOT_TOO_EARLY,
    ERR_STALE_VERSION,
)
from helpers import (
    new_id, now_iso, parse_int, parse_str, parse_enum, parse_pagination,
    paginate, get_or_404, require_fields, parse_dt,
)
from middleware import require_auth
from response import success_object, success_list
from services import serialize, bump, recompute_premiered_title_count

bp = Blueprint("programming", __name__)

BLOCK_READ_ROLES = ["PlatformAdmin", "SlatePlanner", "ProductionManager", "ProgrammingExec",
                    "AdSalesRep", "StreamingCurator"]
AIR_READ_ROLES = BLOCK_READ_ROLES

BLOCK_FIELDS = ["season_id", "name", "block_start", "premiere_cadence_days",
                "max_encores_per_title", "min_minutes_between_airings", "status"]
AIR_FIELDS = ["block_id", "title_id", "season_id", "air_start", "kind", "status"]

AIR_KINDS = {"PREMIERE", "ENCORE"}
CADENCE_DAYS = {7, 14}


# ---------------- Program Blocks ----------------

@bp.route("/slate/program-blocks", methods=["POST"])
@require_auth(["ProgrammingExec"])
def create_program_block():
    body = request.get_json(silent=True) or {}
    require_fields(body, ["season_id", "name", "block_start", "premiere_cadence_days", "max_encores_per_title"])
    season = db.seasons.get(body["season_id"])
    if season is None:
        raise err(ERR_NOT_FOUND, "season not found")
    name = parse_str(body["name"], "name")
    block_start_raw = parse_str(body["block_start"], "block_start")
    block_start = parse_dt(block_start_raw, "block_start")
    cadence = parse_int(body["premiere_cadence_days"], "premiere_cadence_days")
    if cadence not in CADENCE_DAYS:
        raise err(ERR_INVALID_REQUEST, "premiere_cadence_days must be 7 or 14")
    max_enc = parse_int(body["max_encores_per_title"], "max_encores_per_title", minimum=1, maximum=5)
    min_minutes = body.get("min_minutes_between_airings", 1440)
    min_minutes = parse_int(min_minutes, "min_minutes_between_airings", minimum=0)
    # block_start inside season air window [start, end)
    aws = parse_dt(season["air_window_start"])
    awe = parse_dt(season["air_window_end"])
    if not (aws <= block_start < awe):
        raise err(ERR_INVALID_WINDOW, "block_start must lie within season air window")
    bid = new_id()
    ts = now_iso()
    block = {
        "id": bid,
        "season_id": body["season_id"],
        "name": name,
        "block_start": block_start_raw,
        "premiere_cadence_days": cadence,
        "max_encores_per_title": max_enc,
        "min_minutes_between_airings": min_minutes,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.program_blocks[bid] = block
    return success_object(serialize(block, BLOCK_FIELDS), 201)


@bp.route("/slate/program-blocks/<bid>", methods=["GET"])
@require_auth(BLOCK_READ_ROLES)
def get_program_block(bid):
    block = get_or_404(db.program_blocks, bid, "program_block")
    return success_object(serialize(block, BLOCK_FIELDS), 200)


@bp.route("/slate/program-blocks", methods=["GET"])
@require_auth(BLOCK_READ_ROLES)
def list_program_blocks():
    limit, offset = parse_pagination(request.args)
    season_filter = request.args.get("season_id")
    status_filter = request.args.get("status")
    items = list(db.program_blocks.values())
    if season_filter:
        items = [b for b in items if b["season_id"] == season_filter]
    if status_filter:
        items = [b for b in items if b["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(b, BLOCK_FIELDS) for b in page], limit, offset, total)


@bp.route("/slate/program-blocks/<bid>/publish", methods=["POST"])
@require_auth(["ProgrammingExec"])
def publish_program_block(bid):
    block = get_or_404(db.program_blocks, bid, "program_block")
    if block["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Block is not DRAFT")
    season = db.seasons[block["season_id"]]
    if season["status"] != "LOCKED":
        raise err(ERR_SEASON_NOT_LOCKED, "Season is not LOCKED")
    block["status"] = "PUBLISHED"
    bump(block)
    return success_object(serialize(block, BLOCK_FIELDS), 200)


# ---------------- Air Slots ----------------

@bp.route("/slate/air-slots", methods=["POST"])
@require_auth(["ProgrammingExec"])
def create_air_slot():
    body = request.get_json(silent=True) or {}
    require_fields(body, ["block_id", "title_id", "air_start", "kind", "expected_block_version"])
    block = db.program_blocks.get(body["block_id"])
    if block is None:
        raise err(ERR_NOT_FOUND, "program_block not found")
    title = db.titles.get(body["title_id"])
    if title is None:
        raise err(ERR_NOT_FOUND, "title not found")
    season = db.seasons[block["season_id"]]
    # cross-studio: title's season's studio must equal block's season's studio
    title_season = db.seasons[title["season_id"]]
    if title_season["studio_id"] != season["studio_id"]:
        raise err(ERR_NOT_FOUND, "title and block in different studios")
    # OCC check
    if body["expected_block_version"] != block["version"]:
        raise err(ERR_STALE_VERSION, "Block version mismatch")
    # state legality: block must be PUBLISHED
    if block["status"] != "PUBLISHED":
        raise err(ERR_INVALID_STATE, "Block is not PUBLISHED")
    air_start_raw = parse_str(body["air_start"], "air_start")
    air_start = parse_dt(air_start_raw, "air_start")
    kind = parse_enum(body["kind"], "kind", AIR_KINDS)
    # air-window containment
    aws = parse_dt(season["air_window_start"])
    awe = parse_dt(season["air_window_end"])
    if not (aws <= air_start < awe):
        raise err(ERR_INVALID_WINDOW, "air_start outside season air window")
    # premiere cadence (only for PREMIERE)
    if kind == "PREMIERE":
        block_start = parse_dt(block["block_start"])
        delta_seconds = (air_start - block_start).total_seconds()
        cadence_seconds = block["premiere_cadence_days"] * 86400
        if int(delta_seconds) % cadence_seconds != 0:
            raise err(ERR_PREMIERE_CADENCE_VIOLATION, "air_start off cadence grid")
    # same-title buffer
    min_gap_seconds = block["min_minutes_between_airings"] * 60
    for existing in db.air_slots.values():
        if (existing["block_id"] == block["id"]
                and existing["title_id"] == title["id"]
                and existing["status"] in ("PLANNED", "AIRED")):
            existing_start = parse_dt(existing["air_start"])
            gap = abs((air_start - existing_start).total_seconds())
            if gap < min_gap_seconds:
                raise err(ERR_AIRSLOT_OVERLAP, "Same-title buffer violated")
    # encore cap (only for ENCORE)
    if kind == "ENCORE":
        encore_count = sum(
            1 for a in db.air_slots.values()
            if a["block_id"] == block["id"]
            and a["title_id"] == title["id"]
            and a["kind"] == "ENCORE"
            and a["status"] in ("PLANNED", "AIRED")
        )
        if encore_count >= block["max_encores_per_title"]:
            raise err(ERR_ENCORE_CAP_EXCEEDED, "Encore cap reached")
    aid = new_id()
    ts = now_iso()
    air = {
        "id": aid,
        "block_id": block["id"],
        "title_id": title["id"],
        "season_id": season["id"],
        "air_start": air_start_raw,
        "kind": kind,
        "status": "PLANNED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.air_slots[aid] = air
    # OCC parent bump
    bump(block)
    return success_object(serialize(air, AIR_FIELDS), 201)


@bp.route("/slate/air-slots/<aid>", methods=["GET"])
@require_auth(AIR_READ_ROLES)
def get_air_slot(aid):
    air = get_or_404(db.air_slots, aid, "air_slot")
    return success_object(serialize(air, AIR_FIELDS), 200)


@bp.route("/slate/air-slots", methods=["GET"])
@require_auth(AIR_READ_ROLES)
def list_air_slots():
    limit, offset = parse_pagination(request.args)
    block_filter = request.args.get("block_id")
    title_filter = request.args.get("title_id")
    season_filter = request.args.get("season_id")
    kind_filter = request.args.get("kind")
    status_filter = request.args.get("status")
    items = list(db.air_slots.values())
    if block_filter:
        items = [a for a in items if a["block_id"] == block_filter]
    if title_filter:
        items = [a for a in items if a["title_id"] == title_filter]
    if season_filter:
        items = [a for a in items if a["season_id"] == season_filter]
    if kind_filter:
        items = [a for a in items if a["kind"] == kind_filter]
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(a, AIR_FIELDS) for a in page], limit, offset, total)


@bp.route("/slate/air-slots/<aid>/mark-aired", methods=["POST"])
@require_auth(["ProgrammingExec"])
def mark_air_slot_aired(aid):
    air = get_or_404(db.air_slots, aid, "air_slot")
    if air["status"] != "PLANNED":
        raise err(ERR_INVALID_STATE, "AirSlot is not PLANNED")
    clock = parse_dt(db.get_clock())
    air_start = parse_dt(air["air_start"])
    if clock < air_start:
        raise err(ERR_AIRSLOT_TOO_EARLY, "Logical clock has not reached air_start")
    air["status"] = "AIRED"
    bump(air)
    if air["kind"] == "PREMIERE":
        season = db.seasons[air["season_id"]]
        recompute_premiered_title_count(season["id"])
        bump(season)
    return success_object(serialize(air, AIR_FIELDS), 200)


@bp.route("/slate/air-slots/<aid>/cancel", methods=["POST"])
@require_auth(["ProgrammingExec"])
def cancel_air_slot(aid):
    air = get_or_404(db.air_slots, aid, "air_slot")
    if air["status"] != "PLANNED":
        raise err(ERR_INVALID_STATE, "AirSlot is not PLANNED")
    air["status"] = "CANCELLED"
    bump(air)
    return success_object(serialize(air, AIR_FIELDS), 200)
