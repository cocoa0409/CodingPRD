"""Clock + tier config routes."""
from flask import Blueprint

from db import db
from errors import raise_err, ERR_VALIDATION, ERR_NOT_FOUND
from helpers import (
    ok, ok_list, body, new_common, touch, parse_iso_datetime,
)
from middleware import authenticate, authorize
from services_clock import evaluate_clock_events

bp = Blueprint("core", __name__)

TIER_CODES = {"PERSONAL", "EDUCATION", "PRO", "ENTERPRISE"}


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    b = body()
    to = b.get("to_iso8601")
    dt = parse_iso_datetime(to)
    if dt is None:
        raise_err(ERR_VALIDATION, "to_iso8601 must be a valid ISO 8601 timestamp")
    db.clock = dt
    evaluate_clock_events()
    s = db.clock.strftime("%Y-%m-%dT%H:%M:%S.")
    return ok({"current_utc": s + "%03dZ" % (db.clock.microsecond // 1000)})


@bp.route("/tiers", methods=["POST"])
def create_tier():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    b = body()
    tier_code = b.get("tier_code")
    if tier_code not in TIER_CODES:
        raise_err(ERR_VALIDATION, "tier_code must be one of PERSONAL/EDUCATION/PRO/ENTERPRISE")
    int_fields = ["revenue_ceiling_cents", "funding_ceiling_cents", "seat_minimum", "seat_overage_cents"]
    for f in int_fields:
        v = b.get(f)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise_err(ERR_VALIDATION, "%s must be a non-negative integer" % f)
    bool_fields = ["runtime_fee_exempt", "export_module_allowed", "marketplace_sell_allowed"]
    for f in bool_fields:
        if f not in b or not isinstance(b[f], bool):
            raise_err(ERR_VALIDATION, "%s must be a boolean" % f)
    supersedes = b.get("supersedes_tier_config_id")
    superseded = None
    if supersedes is not None:
        superseded = db.tiers.get(supersedes)
        if superseded is None:
            raise_err(ERR_NOT_FOUND, "supersedes_tier_config_id not found")
        if superseded["tier_config_status"] != "ACTIVE" or superseded["tier_code"] != tier_code:
            raise_err(ERR_VALIDATION, "superseded config must be ACTIVE with the same tier_code")
    ent = new_common()
    ent.update({
        "tier_code": tier_code,
        "revenue_ceiling_cents": b["revenue_ceiling_cents"],
        "funding_ceiling_cents": b["funding_ceiling_cents"],
        "seat_minimum": b["seat_minimum"],
        "seat_overage_cents": b["seat_overage_cents"],
        "runtime_fee_exempt": b["runtime_fee_exempt"],
        "export_module_allowed": b["export_module_allowed"],
        "marketplace_sell_allowed": b["marketplace_sell_allowed"],
        "supersedes_tier_config_id": supersedes,
        "tier_config_status": "ACTIVE",
    })
    db.tiers[ent["id"]] = ent
    if superseded is not None:
        superseded["tier_config_status"] = "SUPERSEDED"
        touch(superseded)
    return ok(ent, 201)


@bp.route("/tiers", methods=["GET"])
def list_tiers():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor", "ReviewBoard"})
    from flask import request
    items = sorted(db.tiers.values(), key=lambda t: t["created_at"])
    tc = request.args.get("tier_code")
    ts = request.args.get("tier_config_status")
    if tc:
        items = [t for t in items if t["tier_code"] == tc]
    if ts:
        items = [t for t in items if t["tier_config_status"] == ts]
    return ok_list(items)


@bp.route("/tiers/<tid>", methods=["GET"])
def get_tier(tid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor", "ReviewBoard"})
    t = db.tiers.get(tid)
    if t is None:
        raise_err(ERR_NOT_FOUND, "Tier config not found")
    return ok(t)
