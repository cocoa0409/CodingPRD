"""Coupon endpoints."""
from flask import Blueprint, request
from db import DB, parse_iso
from response import success, success_list, parse_pagination, paginate
from middleware import require_roles
from entities import stamp_new, touch, get_or_404, lazy_coupon
from errors import raise_err

bp = Blueprint("coupons", __name__)

READ_ROLES = ("OpsAdmin", "MarketingManager", "StoreClerk")


def c_view(c):
    return dict(c)


@bp.route("/coupons", methods=["POST"])
@require_roles("MarketingManager")
def create_coupon():
    b = request.get_json(silent=True) or {}
    required = ["code", "channel", "audience", "discount_type", "discount_value",
                "per_customer_limit", "budget_cents", "window_start", "window_end"]
    for f in required:
        if b.get(f) is None:
            raise_err("ERR_VALIDATION", f"Missing field: {f}")
    if b["channel"] not in ("PRINT", "EMAIL", "APP"):
        raise_err("ERR_VALIDATION", "Invalid channel")
    if b["audience"] not in ("ALL", "MEMBERS_ONLY"):
        raise_err("ERR_VALIDATION", "Invalid audience")
    if b["discount_type"] not in ("PERCENT_OFF_ITEM", "AMOUNT_OFF_ITEM",
                                  "PERCENT_OFF_BASKET", "FIXED_AMOUNT_OFF_BASKET"):
        raise_err("ERR_VALIDATION", "Invalid discount_type")
    dv = b["discount_value"]
    if b["discount_type"] in ("PERCENT_OFF_ITEM", "PERCENT_OFF_BASKET"):
        if not (isinstance(dv, (int, float)) and 0 < dv < 100):
            raise_err("ERR_VALIDATION", "Percent discount must be in (0,100)")
    else:
        if not (isinstance(dv, int) and dv > 0):
            raise_err("ERR_VALIDATION", "Amount discount must be > 0 cents")
    if not isinstance(b["per_customer_limit"], int) or b["per_customer_limit"] < 1:
        raise_err("ERR_VALIDATION", "per_customer_limit must be >= 1")
    if not isinstance(b["budget_cents"], int) or b["budget_cents"] < 1:
        raise_err("ERR_VALIDATION", "budget_cents must be >= 1")
    ws = parse_iso(b["window_start"])
    we = parse_iso(b["window_end"])
    if ws is None or we is None:
        raise_err("ERR_VALIDATION", "window_start/window_end must be ISO 8601")
    if we <= ws:
        raise_err("ERR_VALIDATION", "window_end must be > window_start")
    mes = b.get("member_early_start")
    if mes is not None:
        mes_dt = parse_iso(mes)
        if mes_dt is None:
            raise_err("ERR_VALIDATION", "member_early_start must be ISO 8601")
        if mes_dt > ws:
            raise_err("ERR_VALIDATION", "member_early_start must be <= window_start")
    min_basket = b.get("min_basket_cents", 0)
    if not isinstance(min_basket, int) or min_basket < 0:
        raise_err("ERR_VALIDATION", "min_basket_cents must be >= 0")
    max_disc = b.get("max_discount_cents")
    if max_disc is not None and (not isinstance(max_disc, int) or max_disc < 0):
        raise_err("ERR_VALIDATION", "max_discount_cents must be >= 0 or null")
    for c in DB.coupons.values():
        if c["code"].lower() == b["code"].lower():
            raise_err("ERR_VALIDATION", "Duplicate coupon code")
    rec = stamp_new({
        "code": b["code"],
        "channel": b["channel"],
        "audience": b["audience"],
        "discount_type": b["discount_type"],
        "discount_value": dv,
        "min_basket_cents": min_basket,
        "max_discount_cents": max_disc,
        "per_customer_limit": b["per_customer_limit"],
        "budget_cents": b["budget_cents"],
        "budget_spent_cents": 0,
        "budget_reserved_cents": 0,
        "usage_records": [],
        "window_start": b["window_start"],
        "window_end": b["window_end"],
        "member_early_start": mes,
        "status": "DRAFT",
    })
    DB.coupons[rec["id"]] = rec
    return success(c_view(rec), status=201)


@bp.route("/coupons", methods=["GET"])
@require_roles(*READ_ROLES)
def list_coupons():
    limit, offset = parse_pagination(request.args)
    rows = sorted(DB.coupons.values(), key=lambda r: r["created_at"])
    st = request.args.get("status")
    ch = request.args.get("channel")
    for r in rows:
        lazy_coupon(r)
    if st:
        rows = [r for r in rows if r["status"] == st]
    if ch:
        rows = [r for r in rows if r["channel"] == ch]
    page, total = paginate(rows, limit, offset)
    return success_list([c_view(r) for r in page], limit, offset, total)


@bp.route("/coupons/<couponId>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_coupon(couponId):
    c = get_or_404(DB.coupons, couponId)
    lazy_coupon(c)
    return success(c_view(c))


@bp.route("/coupons/<couponId>/activate", methods=["POST"])
@require_roles("MarketingManager")
def activate_coupon(couponId):
    c = get_or_404(DB.coupons, couponId)
    lazy_coupon(c)
    if c["status"] not in ("DRAFT", "PAUSED"):
        raise_err("ERR_INVALID_STATE", "Coupon not DRAFT/PAUSED")
    c["status"] = "ACTIVE"
    touch(c)
    return success(c_view(c))


@bp.route("/coupons/<couponId>/pause", methods=["POST"])
@require_roles("MarketingManager")
def pause_coupon(couponId):
    c = get_or_404(DB.coupons, couponId)
    lazy_coupon(c)
    if c["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Coupon not ACTIVE")
    c["status"] = "PAUSED"
    touch(c)
    return success(c_view(c))
