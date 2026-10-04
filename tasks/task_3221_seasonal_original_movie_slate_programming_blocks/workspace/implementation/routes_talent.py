"""Talent, TalentDeal, Casting routes."""
from flask import Blueprint, request

import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_TALENT_UNAVAILABLE,
)
from helpers import (
    new_id, now_iso, parse_int, parse_str, parse_pagination, paginate,
    get_or_404, require_fields, parse_dt,
)
from middleware import require_auth
from response import success_object, success_list
from services import (
    serialize, bump, recompute_fulfilled_pictures, availability_containment_ok,
    studio_of_season,
)

bp = Blueprint("talent", __name__)

ALL_ROLES = ["PlatformAdmin", "SlatePlanner", "ProductionManager", "TalentAgent",
             "ProgrammingExec", "AdSalesRep", "StreamingCurator", "LicensingManager"]

TALENT_READ_ROLES = ALL_ROLES
DEAL_READ_ROLES = ["PlatformAdmin", "SlatePlanner", "ProductionManager", "TalentAgent", "ProgrammingExec"]

TALENT_FIELDS = ["studio_id", "stage_name", "availability_windows"]
DEAL_FIELDS = ["studio_id", "talent_id", "season_id", "picture_commitment", "fulfilled_pictures", "status"]
CASTING_FIELDS = ["season_id", "title_id", "talent_id", "status"]


def _validate_availability_windows(windows):
    if not isinstance(windows, list):
        raise err(ERR_INVALID_REQUEST, "availability_windows must be a list")
    for w in windows:
        if not isinstance(w, dict) or "start" not in w or "end" not in w:
            raise err(ERR_INVALID_REQUEST, "availability_windows entries need start/end")
        parse_dt(w["start"], "availability_windows.start")
        parse_dt(w["end"], "availability_windows.end")


# ---------------- Talent ----------------

@bp.route("/slate/talent", methods=["POST"])
@require_auth(["TalentAgent"])
def create_talent():
    body = request.get_json(silent=True) or {}
    require_fields(body, ["studio_id", "stage_name"])
    studio = db.studios.get(body["studio_id"])
    if studio is None:
        raise err(ERR_NOT_FOUND, "studio not found")
    stage_name = parse_str(body["stage_name"], "stage_name")
    windows = body.get("availability_windows") or []
    _validate_availability_windows(windows)
    tid = new_id()
    ts = now_iso()
    talent = {
        "id": tid,
        "studio_id": body["studio_id"],
        "stage_name": stage_name,
        "availability_windows": windows,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.talents[tid] = talent
    return success_object(serialize(talent, TALENT_FIELDS), 201)


@bp.route("/slate/talent/<tid>", methods=["GET"])
@require_auth(TALENT_READ_ROLES)
def get_talent(tid):
    talent = get_or_404(db.talents, tid, "talent")
    return success_object(serialize(talent, TALENT_FIELDS), 200)


@bp.route("/slate/talent", methods=["GET"])
@require_auth(TALENT_READ_ROLES)
def list_talent():
    limit, offset = parse_pagination(request.args)
    studio_filter = request.args.get("studio_id")
    items = list(db.talents.values())
    if studio_filter:
        items = [t for t in items if t["studio_id"] == studio_filter]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(t, TALENT_FIELDS) for t in page], limit, offset, total)


# ---------------- TalentDeal ----------------

@bp.route("/slate/deals", methods=["POST"])
@require_auth(["TalentAgent"])
def create_deal():
    body = request.get_json(silent=True) or {}
    require_fields(body, ["talent_id", "season_id", "picture_commitment"])
    talent = db.talents.get(body["talent_id"])
    if talent is None:
        raise err(ERR_NOT_FOUND, "talent not found")
    season = db.seasons.get(body["season_id"])
    if season is None:
        raise err(ERR_NOT_FOUND, "season not found")
    # Cross-studio scope check: talent's studio must match season's studio
    if talent["studio_id"] != season["studio_id"]:
        raise err(ERR_NOT_FOUND, "talent and season in different studios")
    commitment = parse_int(body["picture_commitment"], "picture_commitment", minimum=1, maximum=10)
    did = new_id()
    ts = now_iso()
    deal = {
        "id": did,
        "studio_id": talent["studio_id"],
        "talent_id": body["talent_id"],
        "season_id": body["season_id"],
        "picture_commitment": commitment,
        "fulfilled_pictures": 0,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.deals[did] = deal
    return success_object(serialize(deal, DEAL_FIELDS), 201)


@bp.route("/slate/deals/<did>", methods=["GET"])
@require_auth(DEAL_READ_ROLES)
def get_deal(did):
    deal = get_or_404(db.deals, did, "deal")
    return success_object(serialize(deal, DEAL_FIELDS), 200)


@bp.route("/slate/deals", methods=["GET"])
@require_auth(DEAL_READ_ROLES)
def list_deals():
    limit, offset = parse_pagination(request.args)
    talent_filter = request.args.get("talent_id")
    season_filter = request.args.get("season_id")
    studio_filter = request.args.get("studio_id")
    status_filter = request.args.get("status")
    items = list(db.deals.values())
    if talent_filter:
        items = [d for d in items if d["talent_id"] == talent_filter]
    if season_filter:
        items = [d for d in items if d["season_id"] == season_filter]
    if studio_filter:
        items = [d for d in items if d["studio_id"] == studio_filter]
    if status_filter:
        items = [d for d in items if d["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(d, DEAL_FIELDS) for d in page], limit, offset, total)


# ---------------- Casting ----------------

@bp.route("/slate/castings", methods=["POST"])
@require_auth(["TalentAgent"])
def create_casting():
    body = request.get_json(silent=True) or {}
    require_fields(body, ["title_id", "talent_id"])
    title = db.titles.get(body["title_id"])
    if title is None:
        raise err(ERR_NOT_FOUND, "title not found")
    talent = db.talents.get(body["talent_id"])
    if talent is None:
        raise err(ERR_NOT_FOUND, "talent not found")
    season = db.seasons[title["season_id"]]
    if talent["studio_id"] != season["studio_id"]:
        raise err(ERR_NOT_FOUND, "talent and title in different studios")
    cid = new_id()
    ts = now_iso()
    casting = {
        "id": cid,
        "season_id": title["season_id"],
        "title_id": body["title_id"],
        "talent_id": body["talent_id"],
        "status": "ATTACHED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.castings[cid] = casting
    return success_object(serialize(casting, CASTING_FIELDS), 201)


@bp.route("/slate/castings/<cid>", methods=["GET"])
@require_auth(DEAL_READ_ROLES)
def get_casting(cid):
    casting = get_or_404(db.castings, cid, "casting")
    return success_object(serialize(casting, CASTING_FIELDS), 200)


@bp.route("/slate/castings", methods=["GET"])
@require_auth(DEAL_READ_ROLES)
def list_castings():
    limit, offset = parse_pagination(request.args)
    title_filter = request.args.get("title_id")
    talent_filter = request.args.get("talent_id")
    season_filter = request.args.get("season_id")
    status_filter = request.args.get("status")
    items = list(db.castings.values())
    if title_filter:
        items = [c for c in items if c["title_id"] == title_filter]
    if talent_filter:
        items = [c for c in items if c["talent_id"] == talent_filter]
    if season_filter:
        items = [c for c in items if c["season_id"] == season_filter]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(c, CASTING_FIELDS) for c in page], limit, offset, total)


@bp.route("/slate/castings/<cid>/confirm", methods=["POST"])
@require_auth(["TalentAgent"])
def confirm_casting(cid):
    casting = get_or_404(db.castings, cid, "casting")
    if casting["status"] != "ATTACHED":
        raise err(ERR_INVALID_STATE, "Casting is not ATTACHED")
    title = db.titles[casting["title_id"]]
    if title["status"] not in ("APPROVED", "IN_PRODUCTION"):
        raise err(ERR_INVALID_STATE, "Title must be APPROVED or IN_PRODUCTION")
    # ACTIVE deal for this talent in title's season
    talent = db.talents[casting["talent_id"]]
    season = db.seasons[title["season_id"]]
    active_deal = None
    for d in db.deals.values():
        if (d["talent_id"] == casting["talent_id"]
                and d["season_id"] == title["season_id"]
                and d["status"] == "ACTIVE"):
            active_deal = d
            break
    if active_deal is None:
        raise err(ERR_TALENT_UNAVAILABLE, "No ACTIVE deal for this talent/season")
    # availability containment
    if not availability_containment_ok(talent, title, season):
        raise err(ERR_TALENT_UNAVAILABLE, "Availability containment failed")
    casting["status"] = "CONFIRMED"
    bump(casting)
    recompute_fulfilled_pictures(active_deal)
    if (active_deal["status"] == "ACTIVE"
            and active_deal["fulfilled_pictures"] == active_deal["picture_commitment"]):
        active_deal["status"] = "FULFILLED"
    bump(active_deal)
    return success_object(serialize(casting, CASTING_FIELDS), 200)


@bp.route("/slate/castings/<cid>/release", methods=["POST"])
@require_auth(["TalentAgent"])
def release_casting(cid):
    casting = get_or_404(db.castings, cid, "casting")
    if casting["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Casting is not CONFIRMED")
    casting["status"] = "RELEASED"
    bump(casting)
    # Recompute the deal(s) for this talent in this season
    for d in db.deals.values():
        if d["talent_id"] == casting["talent_id"] and d["season_id"] == casting["season_id"]:
            recompute_fulfilled_pictures(d)
            if d["status"] == "FULFILLED" and d["fulfilled_pictures"] < d["picture_commitment"]:
                d["status"] = "ACTIVE"
            bump(d)
    return success_object(serialize(casting, CASTING_FIELDS), 200)
