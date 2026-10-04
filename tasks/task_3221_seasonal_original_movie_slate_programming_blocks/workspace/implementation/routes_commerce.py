"""Sponsorships, StreamingWindows, LicenseGrants routes."""
import math
from flask import Blueprint, request

import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_SEASON_NOT_LOCKED, ERR_AD_BUDGET_EXCEEDED, ERR_INVALID_WINDOW,
    ERR_AIRSLOT_TOO_EARLY, ERR_STREAMING_BEFORE_PREMIERE,
)
from helpers import (
    new_id, now_iso, parse_int, parse_str, parse_enum, parse_pagination,
    paginate, get_or_404, require_fields, parse_dt,
)
from middleware import require_auth
from response import success_object, success_list
from services import (
    serialize, bump, compute_projected_cost, compute_actual_cost,
    compute_provisional_royalty, compute_trued_royalty,
)

bp = Blueprint("commerce", __name__)

SPONSOR_READ_ROLES = ["PlatformAdmin", "ProgrammingExec", "AdSalesRep"]
STREAM_READ_ROLES = ["PlatformAdmin", "ProgrammingExec", "StreamingCurator"]
LICENSE_READ_ROLES = ["PlatformAdmin", "LicensingManager"]

SPONSOR_FIELDS = ["season_id", "advertiser", "season_cpm_cents", "viewership_thousands",
                  "projected_cost_cents", "actual_cost_cents", "status"]
STREAM_FIELDS = ["season_id", "title_id", "platform", "window_start", "window_end", "status"]
LICENSE_FIELDS = ["season_id", "title_id", "category", "licensee", "royalty_rate",
                  "reported_revenue_cents", "provisional_royalty_cents", "trued_royalty_cents", "status"]

PLATFORMS = {"OWN_STREAMER", "PARTNER_STREAMER"}
CATEGORIES = {"MERCHANDISE", "PUBLISHING"}


# ---------------- Sponsorships ----------------

@bp.route("/slate/sponsorships", methods=["POST"])
@require_auth(["AdSalesRep"])
def create_sponsorship():
    body = request.get_json(silent=True) or {}
    require_fields(body, ["season_id", "advertiser", "season_cpm_cents", "viewership_thousands"])
    season = db.seasons.get(body["season_id"])
    if season is None:
        raise err(ERR_NOT_FOUND, "season not found")
    advertiser = parse_str(body["advertiser"], "advertiser")
    cpm = parse_int(body["season_cpm_cents"], "season_cpm_cents", minimum=1)
    viewership = parse_int(body["viewership_thousands"], "viewership_thousands", minimum=0)
    sid = new_id()
    ts = now_iso()
    sponsorship = {
        "id": sid,
        "season_id": body["season_id"],
        "advertiser": advertiser,
        "season_cpm_cents": cpm,
        "viewership_thousands": viewership,
        "projected_cost_cents": 0,
        "actual_cost_cents": None,
        "status": "BOOKED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    sponsorship["projected_cost_cents"] = compute_projected_cost(sponsorship, season)
    db.sponsorships[sid] = sponsorship
    return success_object(serialize(sponsorship, SPONSOR_FIELDS), 201)


@bp.route("/slate/sponsorships/<sid>", methods=["GET"])
@require_auth(SPONSOR_READ_ROLES)
def get_sponsorship(sid):
    s = get_or_404(db.sponsorships, sid, "sponsorship")
    return success_object(serialize(s, SPONSOR_FIELDS), 200)


@bp.route("/slate/sponsorships", methods=["GET"])
@require_auth(SPONSOR_READ_ROLES)
def list_sponsorships():
    limit, offset = parse_pagination(request.args)
    season_filter = request.args.get("season_id")
    status_filter = request.args.get("status")
    items = list(db.sponsorships.values())
    if season_filter:
        items = [s for s in items if s["season_id"] == season_filter]
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(s, SPONSOR_FIELDS) for s in page], limit, offset, total)


@bp.route("/slate/sponsorships/<sid>/reconcile", methods=["POST"])
@require_auth(["AdSalesRep"])
def reconcile_sponsorship(sid):
    s = get_or_404(db.sponsorships, sid, "sponsorship")
    if s["status"] != "BOOKED":
        raise err(ERR_INVALID_STATE, "Sponsorship is not BOOKED")
    season = db.seasons[s["season_id"]]
    if season["status"] != "ARCHIVED":
        raise err(ERR_SEASON_NOT_LOCKED, "Season is not ARCHIVED")
    actual = compute_actual_cost(s, season)
    studio = db.studios[season["studio_id"]]
    if studio["ad_budget_cents"] - actual < 0:
        raise err(ERR_AD_BUDGET_EXCEEDED, "Ad budget would go negative")
    studio["ad_budget_cents"] -= actual
    bump(studio)
    s["actual_cost_cents"] = actual
    s["status"] = "RECONCILED"
    bump(s)
    return success_object(serialize(s, SPONSOR_FIELDS), 200)


@bp.route("/slate/sponsorships/<sid>/cancel", methods=["POST"])
@require_auth(["AdSalesRep"])
def cancel_sponsorship(sid):
    s = get_or_404(db.sponsorships, sid, "sponsorship")
    if s["status"] != "BOOKED":
        raise err(ERR_INVALID_STATE, "Sponsorship is not BOOKED")
    s["status"] = "CANCELLED"
    bump(s)
    return success_object(serialize(s, SPONSOR_FIELDS), 200)


# ---------------- Streaming Windows ----------------

@bp.route("/slate/streaming-windows", methods=["POST"])
@require_auth(["StreamingCurator"])
def create_streaming_window():
    body = request.get_json(silent=True) or {}
    require_fields(body, ["season_id", "title_id", "platform", "window_start", "window_end"])
    season = db.seasons.get(body["season_id"])
    if season is None:
        raise err(ERR_NOT_FOUND, "season not found")
    title = db.titles.get(body["title_id"])
    if title is None:
        raise err(ERR_NOT_FOUND, "title not found")
    # cross-scope: title must belong to the given season
    if title["season_id"] != season["id"]:
        raise err(ERR_NOT_FOUND, "title not in given season")
    platform = parse_enum(body["platform"], "platform", PLATFORMS)
    ws_raw = parse_str(body["window_start"], "window_start")
    we_raw = parse_str(body["window_end"], "window_end")
    ws = parse_dt(ws_raw, "window_start")
    we = parse_dt(we_raw, "window_end")
    if we <= ws:
        raise err(ERR_INVALID_WINDOW, "window_end must be after window_start")
    sid = new_id()
    ts = now_iso()
    sw = {
        "id": sid,
        "season_id": body["season_id"],
        "title_id": body["title_id"],
        "platform": platform,
        "window_start": ws_raw,
        "window_end": we_raw,
        "status": "SCHEDULED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.streaming_windows[sid] = sw
    return success_object(serialize(sw, STREAM_FIELDS), 201)


@bp.route("/slate/streaming-windows/<sid>", methods=["GET"])
@require_auth(STREAM_READ_ROLES)
def get_streaming_window(sid):
    sw = get_or_404(db.streaming_windows, sid, "streaming_window")
    return success_object(serialize(sw, STREAM_FIELDS), 200)


@bp.route("/slate/streaming-windows", methods=["GET"])
@require_auth(STREAM_READ_ROLES)
def list_streaming_windows():
    limit, offset = parse_pagination(request.args)
    season_filter = request.args.get("season_id")
    title_filter = request.args.get("title_id")
    platform_filter = request.args.get("platform")
    status_filter = request.args.get("status")
    items = list(db.streaming_windows.values())
    if season_filter:
        items = [s for s in items if s["season_id"] == season_filter]
    if title_filter:
        items = [s for s in items if s["title_id"] == title_filter]
    if platform_filter:
        items = [s for s in items if s["platform"] == platform_filter]
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(s, STREAM_FIELDS) for s in page], limit, offset, total)


@bp.route("/slate/streaming-windows/<sid>/open", methods=["POST"])
@require_auth(["StreamingCurator"])
def open_streaming_window(sid):
    sw = get_or_404(db.streaming_windows, sid, "streaming_window")
    if sw["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "StreamingWindow is not SCHEDULED")
    title = db.titles[sw["title_id"]]
    if title["status"] != "DELIVERED":
        raise err(ERR_INVALID_STATE, "Title is not DELIVERED")
    clock = parse_dt(db.get_clock())
    ws = parse_dt(sw["window_start"])
    if clock < ws:
        raise err(ERR_AIRSLOT_TOO_EARLY, "Logical clock before window_start")
    if sw["platform"] == "OWN_STREAMER":
        has_aired_premiere = any(
            a for a in db.air_slots.values()
            if a["title_id"] == sw["title_id"]
            and a["kind"] == "PREMIERE"
            and a["status"] == "AIRED"
        )
        if not has_aired_premiere:
            raise err(ERR_STREAMING_BEFORE_PREMIERE, "No AIRED PREMIERE for title")
    sw["status"] = "OPEN"
    bump(sw)
    return success_object(serialize(sw, STREAM_FIELDS), 200)


@bp.route("/slate/streaming-windows/<sid>/close", methods=["POST"])
@require_auth(["StreamingCurator"])
def close_streaming_window(sid):
    sw = get_or_404(db.streaming_windows, sid, "streaming_window")
    if sw["status"] not in ("SCHEDULED", "OPEN"):
        raise err(ERR_INVALID_STATE, "StreamingWindow is not SCHEDULED or OPEN")
    sw["status"] = "CLOSED"
    bump(sw)
    return success_object(serialize(sw, STREAM_FIELDS), 200)


# ---------------- License Grants ----------------

@bp.route("/slate/licenses", methods=["POST"])
@require_auth(["LicensingManager"])
def create_license():
    body = request.get_json(silent=True) or {}
    require_fields(body, ["season_id", "title_id", "category", "licensee", "royalty_rate", "reported_revenue_cents"])
    season = db.seasons.get(body["season_id"])
    if season is None:
        raise err(ERR_NOT_FOUND, "season not found")
    title = db.titles.get(body["title_id"])
    if title is None:
        raise err(ERR_NOT_FOUND, "title not found")
    if title["season_id"] != season["id"]:
        raise err(ERR_NOT_FOUND, "title not in given season")
    category = parse_enum(body["category"], "category", CATEGORIES)
    licensee = parse_str(body["licensee"], "licensee")
    rate = body["royalty_rate"]
    if isinstance(rate, bool) or not isinstance(rate, (int, float)):
        raise err(ERR_INVALID_REQUEST, "royalty_rate must be a number")
    if rate <= 0 or rate > 1:
        raise err(ERR_INVALID_REQUEST, "royalty_rate must be in (0, 1]")
    revenue = parse_int(body["reported_revenue_cents"], "reported_revenue_cents", minimum=0)
    provisional = compute_provisional_royalty(revenue, rate)
    sid = new_id()
    ts = now_iso()
    lic = {
        "id": sid,
        "season_id": body["season_id"],
        "title_id": body["title_id"],
        "category": category,
        "licensee": licensee,
        "royalty_rate": rate,
        "reported_revenue_cents": revenue,
        "provisional_royalty_cents": provisional,
        "trued_royalty_cents": None,
        "status": "REPORTED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.licenses[sid] = lic
    return success_object(serialize(lic, LICENSE_FIELDS), 201)


@bp.route("/slate/licenses/<sid>", methods=["GET"])
@require_auth(LICENSE_READ_ROLES)
def get_license(sid):
    lic = get_or_404(db.licenses, sid, "license")
    return success_object(serialize(lic, LICENSE_FIELDS), 200)


@bp.route("/slate/licenses", methods=["GET"])
@require_auth(LICENSE_READ_ROLES)
def list_licenses():
    limit, offset = parse_pagination(request.args)
    season_filter = request.args.get("season_id")
    title_filter = request.args.get("title_id")
    category_filter = request.args.get("category")
    status_filter = request.args.get("status")
    items = list(db.licenses.values())
    if season_filter:
        items = [l for l in items if l["season_id"] == season_filter]
    if title_filter:
        items = [l for l in items if l["title_id"] == title_filter]
    if category_filter:
        items = [l for l in items if l["category"] == category_filter]
    if status_filter:
        items = [l for l in items if l["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(l, LICENSE_FIELDS) for l in page], limit, offset, total)


@bp.route("/slate/licenses/<sid>/audit", methods=["POST"])
@require_auth(["LicensingManager"])
def audit_license(sid):
    lic = get_or_404(db.licenses, sid, "license")
    if lic["status"] != "REPORTED":
        raise err(ERR_INVALID_STATE, "LicenseGrant is not REPORTED")
    title = db.titles[lic["title_id"]]
    if title["status"] != "DELIVERED":
        raise err(ERR_INVALID_STATE, "Title is not DELIVERED")
    lic["trued_royalty_cents"] = compute_trued_royalty(
        lic["reported_revenue_cents"], lic["royalty_rate"], lic["provisional_royalty_cents"]
    )
    lic["status"] = "AUDITED"
    bump(lic)
    return success_object(serialize(lic, LICENSE_FIELDS), 200)
