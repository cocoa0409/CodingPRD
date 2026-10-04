"""Referral, locator, clock, and sweep endpoints."""
from flask import Blueprint, request

import calc
import sweep
from db import db, serialize
from util import (ApiError, bump, get_json, iso_ms, now_logical, ok, paginate,
                  parse_dt, sort_by_created, new_common)
from routes.shops import require_roles

bp = Blueprint("referrals", __name__)

ROLES_READ_REF = {"NetworkAdmin", "DealerRep", "InsurerRep", "ShopManager"}
SOURCE_TYPES = {"DEALER", "INSURER", "CONSUMER_DIRECT"}


def get_referral_or_404(ref_id):
    ref = db.referrals.get(ref_id)
    if not ref:
        raise ApiError("ERR_NOT_FOUND", 404, "Referral not found")
    return ref


def _route_referral(ref):
    """Run the ranking selector; route if a candidate exists. Returns routed shop or None."""
    candidates = calc.rank_candidates(ref["consumer_zip"], ref["source_type"],
                                      ref.get("insurer_code"))
    if not candidates:
        return None
    shop = candidates[0]
    ref["status"] = "ROUTED"
    ref["routed_shop_id"] = shop["id"]
    ref["routed_at"] = iso_ms(now_logical())
    bump(ref)
    shop["pending_referral_count"] = shop.get("pending_referral_count", 0) + 1
    bump(shop)
    return shop


@bp.post("/network/referrals")
def create_referral():
    require_roles("DealerRep", "InsurerRep", "NetworkAdmin")
    body = get_json()
    consumer_zip = body.get("consumer_zip")
    source_type = body.get("source_type")
    source_reference = body.get("source_reference")
    insurer_code = body.get("insurer_code")
    vin = body.get("vin")
    if source_type not in SOURCE_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"source_type must be one of {sorted(SOURCE_TYPES)}")
    if not isinstance(consumer_zip, str) or not consumer_zip:
        raise ApiError("ERR_INVALID_REQUEST", 400, "consumer_zip is required")
    if not isinstance(source_reference, str) or not source_reference:
        raise ApiError("ERR_INVALID_REQUEST", 400, "source_reference is required")
    if not isinstance(vin, str) or len(vin) != 17:
        raise ApiError("ERR_INVALID_REQUEST", 400, "vin must be 17 characters")
    if source_type == "INSURER":
        if not isinstance(insurer_code, str) or not insurer_code:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "insurer_code is required for INSURER referrals")
    else:
        insurer_code = None
    ref = new_common()
    ref.update({
        "consumer_zip": consumer_zip,
        "source_type": source_type,
        "source_reference": source_reference,
        "insurer_code": insurer_code,
        "vin": vin,
        "routed_shop_id": None,
        "status": "UNROUTED",
        "routed_at": None,
    })
    db.referrals[ref["id"]] = ref
    _route_referral(ref)
    return ok(serialize(ref), 201)


@bp.get("/network/referrals")
def list_referrals():
    require_roles(*ROLES_READ_REF)
    routed_shop_id = request.args.get("routed_shop_id")
    status = request.args.get("status")
    source_type = request.args.get("source_type")
    insurer_code = request.args.get("insurer_code")
    items = list(db.referrals.values())
    if routed_shop_id is not None:
        items = [r for r in items if r["routed_shop_id"] == routed_shop_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if source_type is not None:
        items = [r for r in items if r["source_type"] == source_type]
    if insurer_code is not None:
        items = [r for r in items if r["insurer_code"] == insurer_code]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(r) for r in page], 200, meta)


@bp.get("/network/referrals/<ref_id>")
def get_referral(ref_id):
    require_roles(*ROLES_READ_REF)
    return ok(serialize(get_referral_or_404(ref_id)))


@bp.get("/network/referrals/<ref_id>/repair-orders")
def list_referral_orders(ref_id):
    require_roles(*ROLES_READ_REF)
    get_referral_or_404(ref_id)
    items = sort_by_created([o for o in db.repair_orders.values()
                             if o.get("referral_id") == ref_id])
    page, meta = paginate(items)
    return ok([serialize(o) for o in page], 200, meta)


@bp.post("/network/referrals/<ref_id>/route")
def route_referral(ref_id):
    require_roles("NetworkAdmin")
    ref = get_referral_or_404(ref_id)
    if ref["status"] != "UNROUTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Referral is not UNROUTED")
    _route_referral(ref)
    return ok(serialize(ref))


@bp.post("/network/referrals/<ref_id>/accept")
def accept_referral(ref_id):
    require_roles("ShopManager")
    ref = get_referral_or_404(ref_id)
    if ref["status"] != "ROUTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Referral is not ROUTED")
    shop_id = request.headers.get("X-User-ID")
    if ref["routed_shop_id"] != shop_id:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Only the routed shop may accept this referral")
    shop = db.shops.get(ref["routed_shop_id"])
    from datetime import timedelta
    expiry = parse_dt(ref["routed_at"], "routed_at") + timedelta(
        hours=calc.REFERRAL_TTL_HOURS)
    if now_logical() >= expiry or not shop \
            or shop["certification_status"] not in ("CERTIFIED", "PROBATION"):
        raise ApiError("ERR_REFERRAL_EXPIRED", 422,
                       "Referral TTL has passed or the shop is no longer steerable")
    ref["status"] = "ACCEPTED"
    bump(ref)
    shop["pending_referral_count"] = max(0, shop["pending_referral_count"] - 1)
    bump(shop)
    return ok(serialize(ref))


@bp.post("/network/referrals/<ref_id>/decline")
def decline_referral(ref_id):
    require_roles("ShopManager")
    ref = get_referral_or_404(ref_id)
    if ref["status"] != "ROUTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Referral is not ROUTED")
    shop_id = request.headers.get("X-User-ID")
    if ref["routed_shop_id"] != shop_id:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Only the routed shop may decline this referral")
    ref["status"] = "DECLINED"
    bump(ref)
    shop = db.shops.get(ref["routed_shop_id"])
    if shop:
        shop["pending_referral_count"] = max(0, shop["pending_referral_count"] - 1)
        bump(shop)
    return ok(serialize(ref))


# ---------------------------------------------------------------------------
# Public locator (anonymous)
# ---------------------------------------------------------------------------
@bp.post("/network/locator/search")
def locator_search():
    body = get_json()
    zip_code = body.get("zip_code")
    radius = body.get("radius_miles", calc.LOCATOR_RADIUS_MILES)
    if not isinstance(zip_code, str) or not zip_code:
        raise ApiError("ERR_INVALID_REQUEST", 400, "zip_code is required")
    if not isinstance(radius, (int, float)) or isinstance(radius, bool) or radius <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "radius_miles must be positive")
    shops = calc.rank_candidates(zip_code, radius_miles=float(radius))
    page, meta = paginate(shops)
    return ok([serialize(s) for s in page], 200, meta)


# ---------------------------------------------------------------------------
# Test-driving endpoints
# ---------------------------------------------------------------------------
@bp.post("/network/_clock/set_current_utc")
def set_clock():
    require_roles("NetworkAdmin")
    body = get_json()
    target = parse_dt(body.get("to_iso8601"), "to_iso8601")
    db.clock = target
    counts = sweep.run_sweep()
    return ok({"current_utc": iso_ms(db.clock), "swept_counts": counts})


@bp.post("/network/_sweep/run")
def run_sweep_endpoint():
    require_roles("NetworkAdmin")
    counts = sweep.run_sweep()
    return ok({"swept_counts": counts})
