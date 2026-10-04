"""Membership-Based Furniture Retail API — Flask application."""
import os
from datetime import timedelta

from flask import Flask

import core
from core import (db, clock_now, set_clock, fmt_dt, parse_dt, parse_date,
                  err, ApiError, success_object, success_empty, success_list,
                  error_body, pagination_args, paginate, auth, require_role,
                  new_id, touch, init_common, member_pricing_tier, body,
                  require_fields, check_enum, check_int)
import services
from services import (recompute_order_pricing, order_lines_of,
                      recompute_reserved_production_minutes,
                      sync_booked_route_minutes,
                      recompute_quote_from_consultations,
                      cascade_member_lapsed, release_source_book,
                      run_daily_cycle,
                      MEMBERSHIP_FEE_CENTS, MEMBERSHIP_PERIOD_DAYS,
                      GRACE_DAYS, CANCEL_REFUND_WINDOW_DAYS, QUOTE_DAYS,
                      CONSULT_EXTENSION_DAYS, ROUTE_BUFFER_MINUTES,
                      RETURN_WINDOW_DAYS)

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_body(e)


@app.errorhandler(404)
def handle_404(e):
    return error_body(err("ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_body(err("ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, ApiError):
        return error_body(e)
    return error_body(err("ERR_INVALID_REQUEST", str(e))), 400


# ===========================================================================
# Serializers
# ===========================================================================

def member_view(m):
    return {
        "id": m["id"],
        "email": m["email"],
        "full_name": m["full_name"],
        "auto_renew": m["auto_renew"],
        "status": m["status"],
        "current_period_start": m["current_period_start"],
        "current_period_end": m["current_period_end"],
        "grace_end": m["grace_end"],
        "fee_paid_total_cents": m["fee_paid_total_cents"],
        "lifetime_gross_savings_cents": m["lifetime_gross_savings_cents"],
        "lifetime_net_savings_cents": m["lifetime_net_savings_cents"],
        "pricing_tier": member_pricing_tier(m),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def trade_account_view(t):
    return {
        "id": t["id"],
        "email": t["email"],
        "business_name": t["business_name"],
        "credential_document_id": t["credential_document_id"],
        "license_number": t["license_number"],
        "status": t["status"],
        "tier": t["tier"],
        "decided_at": t["decided_at"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def gallery_view(g):
    return {
        "id": g["id"],
        "name": g["name"],
        "region": g["region"],
        "daily_route_minutes_capacity": g["daily_route_minutes_capacity"],
        "booked_route_minutes": g["booked_route_minutes"],
        "reserved_production_minutes": g["reserved_production_minutes"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def product_view(p):
    return {
        "id": p["id"],
        "sku": p["sku"],
        "name": p["name"],
        "list_price_cents": p["list_price_cents"],
        "line_kind": p["line_kind"],
        "status": p["status"],
        "promo_active": p["promo_active"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def source_book_view(b):
    return {
        "id": b["id"],
        "title": b["title"],
        "product_ids": b["product_ids"],
        "print_ready_date": b["print_ready_date"],
        "status": b["status"],
        "released_at": b["released_at"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def order_view(o):
    return {
        "id": o["id"],
        "gallery_id": o["gallery_id"],
        "member_id": o["member_id"],
        "trade_account_id": o["trade_account_id"],
        "pricing_tier": o["pricing_tier"],
        "status": o["status"],
        "quote_expires_at": o["quote_expires_at"],
        "consultation_extensions_used": o["consultation_extensions_used"],
        "quote_total_cents": o["quote_total_cents"],
        "subtotal_cents": o["subtotal_cents"],
        "white_glove_fee_cents": o["white_glove_fee_cents"],
        "total_cents": o["total_cents"],
        "deposit_due_cents": o["deposit_due_cents"],
        "deposit_paid_cents": o["deposit_paid_cents"],
        "confirmed_at": o["confirmed_at"],
        "delivered_at": o["delivered_at"],
        "cancel_refund_cents": o["cancel_refund_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def order_line_view(l):
    return {
        "id": l["id"],
        "order_id": l["order_id"],
        "product_id": l["product_id"],
        "qty": l["qty"],
        "fabric_tier": l["fabric_tier"],
        "unit_list_price_cents": l["unit_list_price_cents"],
        "line_charged_cents": l["line_charged_cents"],
        "production_status": l["production_status"],
        "production_slot_id": l["production_slot_id"],
        "deposit_cents": l["deposit_cents"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def slot_view(s):
    return {
        "id": s["id"],
        "gallery_id": s["gallery_id"],
        "starts_at": s["starts_at"],
        "ends_at": s["ends_at"],
        "status": s["status"],
        "committed_order_line_id": s["committed_order_line_id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def consultation_view(c):
    return {
        "id": c["id"],
        "member_id": c["member_id"],
        "order_id": c["order_id"],
        "scheduled_at": c["scheduled_at"],
        "status": c["status"],
        "design_plan_notes": c["design_plan_notes"],
        "completed_at": c["completed_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def appointment_view(a):
    return {
        "id": a["id"],
        "order_id": a["order_id"],
        "gallery_id": a["gallery_id"],
        "delivery_date": a["delivery_date"],
        "duration_minutes": a["duration_minutes"],
        "room_placement": a["room_placement"],
        "assembly_required": a["assembly_required"],
        "packaging_removed": a["packaging_removed"],
        "status": a["status"],
        "failure_reason": a["failure_reason"],
        "replaced_by_id": a["replaced_by_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def return_view(r):
    return {
        "id": r["id"],
        "order_id": r["order_id"],
        "order_line_ids": r["order_line_ids"],
        "status": r["status"],
        "restocking_fee_cents": r["restocking_fee_cents"],
        "refund_cents": r["refund_cents"],
        "reason": r["reason"],
        "decided_at": r["decided_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


# ===========================================================================
# Ownership helpers
# ===========================================================================

def check_order_access(o, uid, role):
    """Member may only access own orders; TradeDesigner only own trade orders."""
    if role == "Member":
        if o.get("member_id") != uid:
            raise err("ERR_FORBIDDEN", "Member may only access own orders")
    elif role == "TradeDesigner":
        if o.get("trade_account_id") != uid:
            raise err("ERR_FORBIDDEN", "TradeDesigner may only access own orders")


def check_member_self(member_id, uid, role, admin_ok=True):
    if role == "Member":
        if uid != member_id:
            raise err("ERR_FORBIDDEN", "Member may only act on itself")
    elif role == "PlatformAdmin" and admin_ok:
        pass
    else:
        raise err("ERR_FORBIDDEN", "Not allowed")


# ===========================================================================
# Members
# ===========================================================================

@app.route("/members", methods=["POST"])
def create_member():
    uid, role = auth()
    require_role(role, {"Anonymous"})
    data = body()
    require_fields(data, ["email", "full_name", "auto_renew", "payment_token"])
    email = data["email"]
    if not isinstance(email, str) or not email:
        raise err("ERR_INVALID_REQUEST", "email must be a non-empty string")
    for m in db["members"].values():
        if m["email"] == email:
            raise err("ERR_DUPLICATE_EMAIL", "Member email already registered")
    if not isinstance(data["auto_renew"], bool):
        raise err("ERR_INVALID_REQUEST", "auto_renew must be a boolean")
    now = clock_now()
    m = init_common({
        "email": email,
        "full_name": data["full_name"],
        "auto_renew": data["auto_renew"],
        "status": "ACTIVE",
        "current_period_start": fmt_dt(now),
        "current_period_end": fmt_dt(now + timedelta(days=MEMBERSHIP_PERIOD_DAYS)),
        "grace_end": None,
        "fee_paid_total_cents": MEMBERSHIP_FEE_CENTS,
        "lifetime_gross_savings_cents": 0,
        "lifetime_net_savings_cents": 0 - MEMBERSHIP_FEE_CENTS,
    })
    db["members"][m["id"]] = m
    return success_object(member_view(m), 201)


@app.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    uid, role = auth()
    require_role(role, {"Member", "GalleryAssociate", "PlatformAdmin"})
    m = db["members"].get(mid)
    if not m:
        raise err("ERR_MEMBER_NOT_FOUND", "Member id does not exist")
    if role == "Member" and uid != mid:
        raise err("ERR_FORBIDDEN", "Member may only read itself")
    return success_object(member_view(m))


@app.route("/members/<mid>/renew", methods=["POST"])
def renew_member(mid):
    uid, role = auth()
    require_role(role, {"Member", "PlatformAdmin"})
    m = db["members"].get(mid)
    if not m:
        raise err("ERR_MEMBER_NOT_FOUND", "Member id does not exist")
    if role == "Member" and uid != mid:
        raise err("ERR_FORBIDDEN", "Member may only renew itself")
    if m["status"] != "GRACE":
        raise err("ERR_INVALID_STATE", "Renewal requires status GRACE")
    data = body()
    require_fields(data, ["payment_token"])
    now = clock_now()
    m["fee_paid_total_cents"] += MEMBERSHIP_FEE_CENTS
    m["current_period_start"] = fmt_dt(now)
    m["current_period_end"] = fmt_dt(now + timedelta(days=MEMBERSHIP_PERIOD_DAYS))
    m["grace_end"] = None
    m["status"] = "ACTIVE"
    m["lifetime_net_savings_cents"] = (
        m["lifetime_gross_savings_cents"] - m["fee_paid_total_cents"])
    touch(m)
    return success_object(member_view(m))


@app.route("/members/<mid>/cancel", methods=["POST"])
def cancel_member(mid):
    uid, role = auth()
    require_role(role, {"Member"})
    m = db["members"].get(mid)
    if not m:
        raise err("ERR_MEMBER_NOT_FOUND", "Member id does not exist")
    if uid != mid:
        raise err("ERR_FORBIDDEN", "Member may only cancel itself")
    if m["status"] not in ("ACTIVE", "GRACE"):
        raise err("ERR_INVALID_STATE", "Membership cannot be cancelled from this state")
    now = clock_now()
    if m["status"] == "ACTIVE":
        window_end = parse_dt(m["current_period_start"]) + timedelta(days=CANCEL_REFUND_WINDOW_DAYS)
        if now <= window_end:
            m["fee_paid_total_cents"] -= MEMBERSHIP_FEE_CENTS
            m["lifetime_net_savings_cents"] = (
                m["lifetime_gross_savings_cents"] - m["fee_paid_total_cents"])
            m["status"] = "CANCELLED_REFUNDED"
        else:
            m["status"] = "CANCELLED"
    else:
        m["status"] = "CANCELLED"
    m["grace_end"] = None
    touch(m)
    return success_object(member_view(m))


# ===========================================================================
# Trade accounts
# ===========================================================================

@app.route("/trade-accounts", methods=["POST"])
def create_trade_account():
    uid, role = auth()
    require_role(role, {"Anonymous"})
    data = body()
    require_fields(data, ["email", "business_name", "credential_document_id", "license_number"])
    email = data["email"]
    for t in db["trade_accounts"].values():
        if t["email"] == email:
            raise err("ERR_DUPLICATE_EMAIL", "Trade account email already registered")
    t = init_common({
        "email": email,
        "business_name": data["business_name"],
        "credential_document_id": data["credential_document_id"],
        "license_number": data["license_number"],
        "status": "APPLIED",
        "tier": None,
        "decided_at": None,
    })
    db["trade_accounts"][t["id"]] = t
    return success_object(trade_account_view(t), 201)


@app.route("/trade-accounts/<tid>/verify", methods=["POST"])
def verify_trade_account(tid):
    uid, role = auth()
    require_role(role, {"TradeReviewer"})
    t = db["trade_accounts"].get(tid)
    if not t:
        raise err("ERR_TRADE_ACCOUNT_NOT_FOUND", "TradeAccount id does not exist")
    data = body()
    require_fields(data, ["decision"])
    decision = check_enum(data["decision"], {"APPROVE", "REJECT"}, "decision")
    if t["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Trade account is not in APPLIED")
    if decision == "APPROVE":
        if "tier" not in data or data["tier"] is None:
            raise err("ERR_INVALID_REQUEST", "tier is required for APPROVE")
        tier = check_enum(data["tier"], {"TIER_1", "TIER_2"}, "tier")
        t["tier"] = tier
        t["status"] = "VERIFIED"
    else:
        t["status"] = "REJECTED"
    t["decided_at"] = fmt_dt(clock_now())
    touch(t)
    return success_object(trade_account_view(t))


# ===========================================================================
# Galleries
# ===========================================================================

@app.route("/galleries", methods=["POST"])
def create_gallery():
    uid, role = auth()
    require_role(role, {"PlatformAdmin"})
    data = body()
    require_fields(data, ["name", "region", "daily_route_minutes_capacity"])
    cap = check_int(data["daily_route_minutes_capacity"], "daily_route_minutes_capacity", minimum=0)
    g = init_common({
        "name": data["name"],
        "region": data["region"],
        "daily_route_minutes_capacity": cap,
        "booked_route_minutes": {},
        "reserved_production_minutes": 0,
    })
    db["galleries"][g["id"]] = g
    return success_object(gallery_view(g), 201)


@app.route("/galleries/<gid>", methods=["GET"])
def get_gallery(gid):
    uid, role = auth()
    require_role(role, {"PlatformAdmin", "GalleryAssociate", "HubOperator", "ProductionPlanner"})
    g = db["galleries"].get(gid)
    if not g:
        raise err("ERR_GALLERY_NOT_FOUND", "Gallery id does not exist")
    recompute_reserved_production_minutes(gid)
    sync_booked_route_minutes(gid)
    return success_object(gallery_view(g))


@app.route("/galleries/<gid>/production-slots", methods=["GET"])
def list_gallery_slots(gid):
    uid, role = auth()
    require_role(role, {"ProductionPlanner", "PlatformAdmin"})
    g = db["galleries"].get(gid)
    if not g:
        raise err("ERR_GALLERY_NOT_FOUND", "Gallery id does not exist")
    slots = [s for s in db["production_slots"].values() if s["gallery_id"] == gid]
    slots.sort(key=lambda s: (s["created_at"], s["id"]))
    limit, offset = pagination_args()
    page, total = paginate(slots, limit, offset)
    return success_list([slot_view(s) for s in page], limit, offset, total)


# ===========================================================================
# Products
# ===========================================================================

@app.route("/products", methods=["POST"])
def create_product():
    uid, role = auth()
    require_role(role, {"PlatformAdmin"})
    data = body()
    require_fields(data, ["sku", "name", "list_price_cents", "line_kind"])
    sku = data["sku"]
    for p in db["products"].values():
        if p["sku"] == sku:
            raise err("ERR_DUPLICATE_EMAIL", "SKU already registered")
    kind = check_enum(data["line_kind"], {"STOCK", "CUSTOM"}, "line_kind")
    price = check_int(data["list_price_cents"], "list_price_cents", minimum=0)
    status = data.get("status", "ACTIVE")
    if status is not None:
        status = check_enum(status, {"ACTIVE", "DISCONTINUED"}, "status")
    p = init_common({
        "sku": sku,
        "name": data["name"],
        "list_price_cents": price,
        "line_kind": kind,
        "status": status or "ACTIVE",
        "promo_active": False,
    })
    db["products"][p["id"]] = p
    return success_object(product_view(p), 201)


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    uid, role = auth()
    require_role(role, {"Anonymous", "Member", "TradeDesigner", "GalleryAssociate",
                        "PlatformAdmin", "ProductionPlanner"})
    p = db["products"].get(pid)
    if not p:
        raise err("ERR_PRODUCT_NOT_FOUND", "Product id does not exist")
    return success_object(product_view(p))


@app.route("/products/<pid>/order-lines", methods=["GET"])
def list_product_order_lines(pid):
    uid, role = auth()
    require_role(role, {"ProductionPlanner", "PlatformAdmin", "GalleryAssociate"})
    p = db["products"].get(pid)
    if not p:
        raise err("ERR_PRODUCT_NOT_FOUND", "Product id does not exist")
    lines = [l for l in db["order_lines"].values() if l["product_id"] == pid]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    limit, offset = pagination_args()
    page, total = paginate(lines, limit, offset)
    return success_list([order_line_view(l) for l in page], limit, offset, total)


# ===========================================================================
# Source books
# ===========================================================================

@app.route("/source-books", methods=["POST"])
def create_source_book():
    uid, role = auth()
    require_role(role, {"PlatformAdmin"})
    data = body()
    require_fields(data, ["title", "product_ids", "print_ready_date"])
    if not isinstance(data["product_ids"], list):
        raise err("ERR_INVALID_REQUEST", "product_ids must be an array")
    try:
        prd = parse_dt(data["print_ready_date"])
    except Exception:
        raise err("ERR_INVALID_REQUEST", "print_ready_date must be ISO 8601")
    b = init_common({
        "title": data["title"],
        "product_ids": list(data["product_ids"]),
        "print_ready_date": fmt_dt(prd),
        "status": "IN_PRINT",
        "released_at": None,
    })
    db["source_books"][b["id"]] = b
    return success_object(source_book_view(b), 201)


# ===========================================================================
# Orders
# ===========================================================================

@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = auth()
    require_role(role, {"Member", "TradeDesigner", "GalleryAssociate"})
    data = body()
    require_fields(data, ["gallery_id"])
    gid = data["gallery_id"]
    g = db["galleries"].get(gid)
    if not g:
        raise err("ERR_GALLERY_NOT_FOUND", "Gallery id does not exist")
    member_id = data.get("member_id")
    trade_account_id = data.get("trade_account_id")
    if member_id and trade_account_id:
        raise err("ERR_INVALID_REQUEST",
                  "Exactly one of member_id/trade_account_id may be supplied")
    if role == "Member":
        if not member_id or member_id != uid:
            raise err("ERR_FORBIDDEN", "Member may only create own orders")
        m = db["members"].get(member_id)
        if not m:
            raise err("ERR_MEMBER_NOT_FOUND", "Member id does not exist")
    elif role == "TradeDesigner":
        if not trade_account_id or trade_account_id != uid:
            raise err("ERR_FORBIDDEN", "TradeDesigner may only create own orders")
        t = db["trade_accounts"].get(trade_account_id)
        if not t:
            raise err("ERR_TRADE_ACCOUNT_NOT_FOUND", "TradeAccount id does not exist")
        if t["status"] != "VERIFIED":
            raise err("ERR_TRADE_NOT_VERIFIED", "Trade account is not VERIFIED")
    else:  # GalleryAssociate
        if member_id:
            m = db["members"].get(member_id)
            if not m:
                raise err("ERR_MEMBER_NOT_FOUND", "Member id does not exist")
        if trade_account_id:
            t = db["trade_accounts"].get(trade_account_id)
            if not t:
                raise err("ERR_TRADE_ACCOUNT_NOT_FOUND", "TradeAccount id does not exist")

    now = clock_now()
    o = init_common({
        "gallery_id": gid,
        "member_id": member_id,
        "trade_account_id": trade_account_id,
        "pricing_tier": "RETAIL",
        "status": "QUOTE",
        "quote_expires_at": fmt_dt(now + timedelta(days=QUOTE_DAYS)),
        "consultation_extensions_used": 0,
        "quote_total_cents": 0,
        "subtotal_cents": 0,
        "white_glove_fee_cents": 0,
        "total_cents": 0,
        "deposit_due_cents": 0,
        "deposit_paid_cents": 0,
        "confirmed_at": None,
        "delivered_at": None,
        "cancel_refund_cents": 0,
    })
    # Resolve pricing tier at creation
    if trade_account_id:
        o["pricing_tier"] = "TRADE"
    elif member_id:
        m = db["members"].get(member_id)
        o["pricing_tier"] = "MEMBER" if (m and m["status"] in ("ACTIVE", "GRACE")) else "RETAIL"
    db["orders"][o["id"]] = o
    return success_object(order_view(o), 201)


@app.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    uid, role = auth()
    require_role(role, {"Member", "TradeDesigner", "GalleryAssociate",
                        "HubOperator", "PlatformAdmin", "ProductionPlanner"})
    o = db["orders"].get(oid)
    if not o:
        raise err("ERR_ORDER_NOT_FOUND", "Order id does not exist")
    check_order_access(o, uid, role)
    return success_object(order_view(o))


@app.route("/orders", methods=["GET"])
def list_orders():
    uid, role = auth()
    require_role(role, {"GalleryAssociate", "PlatformAdmin"})
    from flask import request as freq
    member_id = freq.args.get("member_id")
    trade_account_id = freq.args.get("trade_account_id")
    gallery_id = freq.args.get("gallery_id")
    status = freq.args.get("status")
    orders = list(db["orders"].values())
    if member_id is not None:
        orders = [o for o in orders if o.get("member_id") == member_id]
    if trade_account_id is not None:
        orders = [o for o in orders if o.get("trade_account_id") == trade_account_id]
    if gallery_id is not None:
        orders = [o for o in orders if o["gallery_id"] == gallery_id]
    if status is not None:
        orders = [o for o in orders if o["status"] == status]
    orders.sort(key=lambda o: (o["created_at"], o["id"]))
    limit, offset = pagination_args()
    page, total = paginate(orders, limit, offset)
    return success_list([order_view(o) for o in page], limit, offset, total)


def _line_actor_can(o, uid, role):
    if role == "GalleryAssociate":
        return
    check_order_access(o, uid, role)


@app.route("/orders/<oid>/lines", methods=["POST"])
def add_order_line(oid):
    uid, role = auth()
    require_role(role, {"Member", "TradeDesigner", "GalleryAssociate"})
    o = db["orders"].get(oid)
    if not o:
        raise err("ERR_ORDER_NOT_FOUND", "Order id does not exist")
    _line_actor_can(o, uid, role)
    if o["status"] not in ("QUOTE", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Lines may only be added in QUOTE or CONFIRMED")
    data = body()
    require_fields(data, ["product_id", "qty"])
    pid = data["product_id"]
    p = db["products"].get(pid)
    if not p:
        raise err("ERR_PRODUCT_NOT_FOUND", "Product id does not exist")
    qty = check_int(data["qty"], "qty", minimum=1)
    fabric_tier = data.get("fabric_tier", "STANDARD")
    if fabric_tier is not None:
        fabric_tier = check_enum(fabric_tier, {"STANDARD", "PREMIUM"}, "fabric_tier")
    fabric_tier = fabric_tier or "STANDARD"
    # OCC for CONFIRMED
    if o["status"] == "CONFIRMED":
        if "expected_order_version" not in data or data["expected_order_version"] is None:
            raise err("ERR_STALE_VERSION", "expected_order_version is required")
        if data["expected_order_version"] != o["version"]:
            raise err("ERR_STALE_VERSION", "Order version mismatch")
    # Referential rules
    if p["status"] != "ACTIVE":
        raise err("ERR_PRODUCT_UNAVAILABLE", "Product is DISCONTINUED")
    if fabric_tier == "PREMIUM" and p["line_kind"] != "CUSTOM":
        raise err("ERR_PRODUCT_KIND_MISMATCH",
                  "fabric_tier PREMIUM requires a CUSTOM product")
    # Temporal: quote expiry (QUOTE only)
    if o["status"] == "QUOTE" and clock_now() > parse_dt(o["quote_expires_at"]):
        raise err("ERR_QUOTE_EXPIRED", "Quote has expired")

    base = p["list_price_cents"]
    if p["line_kind"] == "CUSTOM" and fabric_tier == "PREMIUM":
        base = core.rhu_frac(base, "1.25")
    had_lines = len(order_lines_of(oid)) > 0
    l = init_common({
        "order_id": oid,
        "product_id": pid,
        "qty": qty,
        "fabric_tier": fabric_tier,
        "unit_list_price_cents": base,
        "line_charged_cents": 0,
        "production_status": "PENDING_DEPOSIT" if p["line_kind"] == "CUSTOM" else "NONE",
        "production_slot_id": None,
        "deposit_cents": 0,
        "kind": p["line_kind"],
    })
    db["order_lines"][l["id"]] = l
    recompute_order_pricing(o)
    if not had_lines and o["status"] == "QUOTE" and o["quote_total_cents"] == 0:
        o["quote_total_cents"] = o["total_cents"]
    touch(o)
    return success_object(order_line_view(l), 201)


@app.route("/orders/<oid>/lines/<lid>", methods=["DELETE"])
def remove_order_line(oid, lid):
    uid, role = auth()
    require_role(role, {"Member", "TradeDesigner", "GalleryAssociate"})
    o = db["orders"].get(oid)
    if not o:
        raise err("ERR_ORDER_NOT_FOUND", "Order id does not exist")
    l = db["order_lines"].get(lid)
    if not l or l["order_id"] != oid:
        raise err("ERR_LINE_NOT_FOUND", "OrderLine id does not exist within the order")
    _line_actor_can(o, uid, role)
    if o["status"] not in ("QUOTE", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Lines may only be removed in QUOTE or CONFIRMED")
    data = body()
    if o["status"] == "CONFIRMED":
        if "expected_order_version" not in data or data["expected_order_version"] is None:
            raise err("ERR_STALE_VERSION", "expected_order_version is required")
        if data["expected_order_version"] != o["version"]:
            raise err("ERR_STALE_VERSION", "Order version mismatch")
    if l["kind"] == "CUSTOM" and l["production_status"] in ("IN_PRODUCTION", "COMPLETE"):
        raise err("ERR_LINE_NON_CANCELABLE",
                  "CUSTOM line in production cannot be removed")
    if o["status"] == "QUOTE" and clock_now() > parse_dt(o["quote_expires_at"]):
        raise err("ERR_QUOTE_EXPIRED", "Quote has expired")

    # Release committed slot
    if l["kind"] == "CUSTOM" and l["production_status"] in ("DEPOSIT_PAID", "COMMITTED"):
        if l.get("production_slot_id"):
            s = db["production_slots"].get(l["production_slot_id"])
            if s and s["status"] == "COMMITTED":
                s["status"] = "OPEN"
                s["committed_order_line_id"] = None
                touch(s)
                recompute_reserved_production_minutes(s["gallery_id"])
        l["production_status"] = "RELEASED"
    del db["order_lines"][lid]
    recompute_order_pricing(o)
    touch(o)
    return success_object(order_view(o))


@app.route("/orders/<oid>/lines", methods=["GET"])
def list_order_lines(oid):
    uid, role = auth()
    require_role(role, {"Member", "TradeDesigner", "GalleryAssociate",
                        "ProductionPlanner", "PlatformAdmin"})
    o = db["orders"].get(oid)
    if not o:
        raise err("ERR_ORDER_NOT_FOUND", "Order id does not exist")
    check_order_access(o, uid, role)
    lines = order_lines_of(oid)
    limit, offset = pagination_args()
    page, total = paginate(lines, limit, offset)
    return success_list([order_line_view(l) for l in page], limit, offset, total)


@app.route("/orders/<oid>/lines/<lid>/schedule-production", methods=["POST"])
def schedule_production(oid, lid):
    uid, role = auth()
    require_role(role, {"ProductionPlanner"})
    o = db["orders"].get(oid)
    if not o:
        raise err("ERR_ORDER_NOT_FOUND", "Order id does not exist")
    l = db["order_lines"].get(lid)
    if not l or l["order_id"] != oid:
        raise err("ERR_LINE_NOT_FOUND", "OrderLine id does not exist within the order")
    data = body()
    require_fields(data, ["production_slot_id"])
    s = db["production_slots"].get(data["production_slot_id"])
    if not s:
        raise err("ERR_SLOT_NOT_FOUND", "ProductionSlot id does not exist")
    if l["kind"] != "CUSTOM" or l["production_status"] != "DEPOSIT_PAID":
        raise err("ERR_CUSTOM_LINE_NOT_DEPOSIT_PAID",
                  "Line must be a CUSTOM line with production_status DEPOSIT_PAID")
    if s["status"] != "OPEN":
        raise err("ERR_SLOT_NOT_OPEN", "Production slot is not OPEN")
    if s["gallery_id"] != o["gallery_id"]:
        raise err("ERR_INVALID_REQUEST",
                  "Slot gallery does not match order gallery")
    s["status"] = "COMMITTED"
    s["committed_order_line_id"] = l["id"]
    touch(s)
    l["production_slot_id"] = s["id"]
    l["production_status"] = "COMMITTED"
    touch(l)
    recompute_reserved_production_minutes(s["gallery_id"])
    g = db["galleries"].get(s["gallery_id"])
    if g:
        touch(g)
    return success_object(slot_view(s))


@app.route("/orders/<oid>/confirm", methods=["POST"])
def confirm_order(oid):
    uid, role = auth()
    require_role(role, {"Member", "TradeDesigner", "GalleryAssociate"})
    o = db["orders"].get(oid)
    if not o:
        raise err("ERR_ORDER_NOT_FOUND", "Order id does not exist")
    _line_actor_can(o, uid, role)
    if o["status"] != "QUOTE":
        raise err("ERR_INVALID_STATE", "Order is not in QUOTE")
    lines = order_lines_of(oid)
    if not lines:
        raise err("ERR_ORDER_EMPTY", "Order has no lines")
    if clock_now() > parse_dt(o["quote_expires_at"]):
        raise err("ERR_QUOTE_EXPIRED", "Quote has expired")
    if o.get("member_id"):
        m = db["members"].get(o["member_id"])
        if not m or m["status"] not in ("ACTIVE", "GRACE"):
            raise err("ERR_MEMBERSHIP_NOT_ACTIVE",
                      "Member standing must be ACTIVE or GRACE")
    if o.get("trade_account_id"):
        t = db["trade_accounts"].get(o["trade_account_id"])
        if not t or t["status"] != "VERIFIED":
            raise err("ERR_TRADE_NOT_VERIFIED", "Trade account is not VERIFIED")
    # Final settlement re-price
    recompute_order_pricing(o)
    if o["deposit_due_cents"] > 0:
        data = body()
        if "deposit_payment_cents" not in data or data["deposit_payment_cents"] is None:
            raise err("ERR_DEPOSIT_REQUIRED", "deposit_payment_cents is required")
        if data["deposit_payment_cents"] != o["deposit_due_cents"]:
            raise err("ERR_DEPOSIT_AMOUNT_MISMATCH",
                      "deposit_payment_cents must equal deposit_due_cents")
        o["deposit_paid_cents"] = o["deposit_due_cents"]
    has_custom = False
    for l in lines:
        if l["kind"] == "CUSTOM":
            l["production_status"] = "DEPOSIT_PAID"
            touch(l)
            has_custom = True
    o["confirmed_at"] = fmt_dt(clock_now())
    o["status"] = "CONFIRMED" if has_custom else "READY_FOR_DELIVERY"
    touch(o)
    return success_object(order_view(o))


@app.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    uid, role = auth()
    require_role(role, {"Member", "TradeDesigner", "GalleryAssociate"})
    o = db["orders"].get(oid)
    if not o:
        raise err("ERR_ORDER_NOT_FOUND", "Order id does not exist")
    _line_actor_can(o, uid, role)
    if o["status"] not in ("QUOTE", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Order cannot be cancelled from this state")
    if o["status"] == "CONFIRMED":
        stock_sum = 0
        for l in order_lines_of(oid):
            if l["kind"] == "STOCK":
                stock_sum += l["line_charged_cents"]
            elif l["production_status"] == "COMMITTED" and l.get("production_slot_id"):
                s = db["production_slots"].get(l["production_slot_id"])
                if s and s["status"] == "COMMITTED":
                    s["status"] = "OPEN"
                    s["committed_order_line_id"] = None
                    touch(s)
                    recompute_reserved_production_minutes(s["gallery_id"])
                l["production_status"] = "RELEASED"
                touch(l)
        o["cancel_refund_cents"] = stock_sum
    o["status"] = "CANCELLED"
    touch(o)
    return success_object(order_view(o))


# ===========================================================================
# Production slots
# ===========================================================================

@app.route("/production-slots", methods=["POST"])
def create_slot():
    uid, role = auth()
    require_role(role, {"ProductionPlanner"})
    data = body()
    require_fields(data, ["gallery_id", "starts_at", "ends_at"])
    gid = data["gallery_id"]
    g = db["galleries"].get(gid)
    if not g:
        raise err("ERR_GALLERY_NOT_FOUND", "Gallery id does not exist")
    try:
        starts = parse_dt(data["starts_at"])
        ends = parse_dt(data["ends_at"])
    except Exception:
        raise err("ERR_INVALID_REQUEST", "starts_at/ends_at must be ISO 8601")
    if ends <= starts:
        raise err("ERR_INVALID_REQUEST", "ends_at must be strictly after starts_at")
    for s in db["production_slots"].values():
        if s["gallery_id"] == gid and s["status"] != "CONSUMED":
            if starts < parse_dt(s["ends_at"]) and parse_dt(s["starts_at"]) < ends:
                raise err("ERR_SLOT_OVERLAP",
                          "New production slot overlaps an existing slot")
    s = init_common({
        "gallery_id": gid,
        "starts_at": fmt_dt(starts),
        "ends_at": fmt_dt(ends),
        "status": "OPEN",
        "committed_order_line_id": None,
    })
    db["production_slots"][s["id"]] = s
    return success_object(slot_view(s), 201)


@app.route("/production-slots/<sid>", methods=["GET"])
def get_slot(sid):
    uid, role = auth()
    require_role(role, {"ProductionPlanner", "PlatformAdmin"})
    s = db["production_slots"].get(sid)
    if not s:
        raise err("ERR_SLOT_NOT_FOUND", "ProductionSlot id does not exist")
    return success_object(slot_view(s))


@app.route("/production-slots/<sid>/advance", methods=["POST"])
def advance_slot(sid):
    uid, role = auth()
    require_role(role, {"ProductionPlanner"})
    s = db["production_slots"].get(sid)
    if not s:
        raise err("ERR_SLOT_NOT_FOUND", "ProductionSlot id does not exist")
    data = body()
    require_fields(data, ["to_state"])
    to_state = check_enum(data["to_state"], {"IN_PROGRESS", "CONSUMED"}, "to_state")
    if to_state == "IN_PROGRESS":
        if s["status"] != "COMMITTED":
            raise err("ERR_INVALID_STATE", "Slot must be COMMITTED to advance to IN_PROGRESS")
        s["status"] = "IN_PROGRESS"
        l = db["order_lines"].get(s["committed_order_line_id"])
        if l:
            l["production_status"] = "IN_PRODUCTION"
            touch(l)
    else:  # CONSUMED
        if s["status"] != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE", "Slot must be IN_PROGRESS to advance to CONSUMED")
        s["status"] = "CONSUMED"
        l = db["order_lines"].get(s["committed_order_line_id"])
        if l:
            l["production_status"] = "COMPLETE"
            touch(l)
            # Bubble-up: all custom lines COMPLETE -> order READY_FOR_DELIVERY
            o = db["orders"].get(l["order_id"])
            if o and o["status"] == "CONFIRMED":
                custom_lines = [x for x in order_lines_of(o["id"]) if x["kind"] == "CUSTOM"]
                if custom_lines and all(x["production_status"] == "COMPLETE" for x in custom_lines):
                    o["status"] = "READY_FOR_DELIVERY"
                    touch(o)
    touch(s)
    recompute_reserved_production_minutes(s["gallery_id"])
    g = db["galleries"].get(s["gallery_id"])
    if g:
        touch(g)
    return success_object(slot_view(s))


# ===========================================================================
# Design consultations
# ===========================================================================

@app.route("/design-consultations", methods=["POST"])
def create_consultation():
    uid, role = auth()
    require_role(role, {"Member", "GalleryAssociate"})
    data = body()
    require_fields(data, ["member_id", "order_id", "scheduled_at"])
    mid = data["member_id"]
    m = db["members"].get(mid)
    if not m:
        raise err("ERR_MEMBER_NOT_FOUND", "Member id does not exist")
    o = db["orders"].get(data["order_id"])
    if not o:
        raise err("ERR_ORDER_NOT_FOUND", "Order id does not exist")
    if role == "Member":
        if uid != mid:
            raise err("ERR_FORBIDDEN", "Member may only book for itself")
        if o.get("member_id") != mid:
            raise err("ERR_FORBIDDEN", "Member must own the order")
    if m["status"] not in ("ACTIVE", "GRACE"):
        raise err("ERR_MEMBERSHIP_NOT_ACTIVE",
                  "Member standing must be ACTIVE or GRACE")
    if o["status"] not in ("QUOTE", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Order must be QUOTE or CONFIRMED")
    try:
        sched = parse_dt(data["scheduled_at"])
    except Exception:
        raise err("ERR_INVALID_REQUEST", "scheduled_at must be ISO 8601")
    c = init_common({
        "member_id": mid,
        "order_id": o["id"],
        "scheduled_at": fmt_dt(sched),
        "status": "SCHEDULED",
        "design_plan_notes": None,
        "completed_at": None,
    })
    db["consultations"][c["id"]] = c
    return success_object(consultation_view(c), 201)


@app.route("/design-consultations/<cid>", methods=["GET"])
def get_consultation(cid):
    uid, role = auth()
    require_role(role, {"Member", "GalleryAssociate", "PlatformAdmin"})
    c = db["consultations"].get(cid)
    if not c:
        raise err("ERR_CONSULTATION_NOT_FOUND", "DesignConsultation id does not exist")
    if role == "Member" and uid != c["member_id"]:
        raise err("ERR_FORBIDDEN", "Member may only read own consultations")
    return success_object(consultation_view(c))


@app.route("/design-consultations", methods=["GET"])
def list_consultations():
    uid, role = auth()
    require_role(role, {"GalleryAssociate", "PlatformAdmin"})
    from flask import request as freq
    member_id = freq.args.get("member_id")
    order_id = freq.args.get("order_id")
    status = freq.args.get("status")
    items = list(db["consultations"].values())
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    if order_id is not None:
        items = [c for c in items if c["order_id"] == order_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    limit, offset = pagination_args()
    page, total = paginate(items, limit, offset)
    return success_list([consultation_view(c) for c in page], limit, offset, total)


@app.route("/design-consultations/<cid>/complete", methods=["POST"])
def complete_consultation(cid):
    uid, role = auth()
    require_role(role, {"GalleryAssociate"})
    c = db["consultations"].get(cid)
    if not c:
        raise err("ERR_CONSULTATION_NOT_FOUND", "DesignConsultation id does not exist")
    if c["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Consultation is not SCHEDULED")
    data = body()
    require_fields(data, ["design_plan_notes"])
    c["design_plan_notes"] = data["design_plan_notes"]
    c["completed_at"] = fmt_dt(clock_now())
    c["status"] = "COMPLETED"
    touch(c)
    o = db["orders"].get(c["order_id"])
    if o and o["status"] == "QUOTE":
        o["quote_expires_at"] = fmt_dt(
            parse_dt(o["quote_expires_at"]) + timedelta(days=CONSULT_EXTENSION_DAYS))
        o["consultation_extensions_used"] += 1
        touch(o)
    return success_object(consultation_view(c))


# ===========================================================================
# Delivery appointments
# ===========================================================================

@app.route("/delivery-appointments", methods=["POST"])
def create_appointment():
    uid, role = auth()
    require_role(role, {"GalleryAssociate", "HubOperator"})
    data = body()
    require_fields(data, ["order_id", "gallery_id", "delivery_date",
                          "duration_minutes", "room_placement", "assembly_required"])
    o = db["orders"].get(data["order_id"])
    if not o:
        raise err("ERR_ORDER_NOT_FOUND", "Order id does not exist")
    g = db["galleries"].get(data["gallery_id"])
    if not g:
        raise err("ERR_GALLERY_NOT_FOUND", "Gallery id does not exist")
    if o["status"] != "READY_FOR_DELIVERY":
        raise err("ERR_INVALID_STATE", "Order must be READY_FOR_DELIVERY")
    for a in db["appointments"].values():
        if a["order_id"] == o["id"] and a["status"] in ("SCHEDULED", "OUT_FOR_DELIVERY"):
            raise err("ERR_APPOINTMENT_EXISTS",
                      "Order already has an active appointment")
    try:
        ddate = parse_date(data["delivery_date"])
    except Exception:
        raise err("ERR_INVALID_REQUEST", "delivery_date must be YYYY-MM-DD")
    dur = check_int(data["duration_minutes"], "duration_minutes", minimum=0)
    if not isinstance(data["room_placement"], bool) or not isinstance(data["assembly_required"], bool):
        raise err("ERR_INVALID_REQUEST", "room_placement and assembly_required must be booleans")
    date_str = ddate.isoformat()
    consumed = services.booked_minutes(g["id"], date_str)
    if consumed + dur + ROUTE_BUFFER_MINUTES > g["daily_route_minutes_capacity"]:
        raise err("ERR_ROUTE_CAPACITY_EXCEEDED",
                  "Daily route minute budget would be exceeded")
    a = init_common({
        "order_id": o["id"],
        "gallery_id": g["id"],
        "delivery_date": date_str,
        "duration_minutes": dur,
        "room_placement": data["room_placement"],
        "assembly_required": data["assembly_required"],
        "packaging_removed": False,
        "status": "SCHEDULED",
        "failure_reason": None,
        "replaced_by_id": None,
    })
    db["appointments"][a["id"]] = a
    # Prior FAILED appointment of same order -> RESCHEDULED
    for prev in db["appointments"].values():
        if prev["id"] != a["id"] and prev["order_id"] == o["id"] and prev["status"] == "FAILED":
            prev["status"] = "RESCHEDULED"
            prev["replaced_by_id"] = a["id"]
            touch(prev)
    sync_booked_route_minutes(g["id"])
    touch(g)
    return success_object(appointment_view(a), 201)


@app.route("/delivery-appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    uid, role = auth()
    require_role(role, {"GalleryAssociate", "HubOperator", "Member", "PlatformAdmin"})
    a = db["appointments"].get(aid)
    if not a:
        raise err("ERR_APPOINTMENT_NOT_FOUND", "DeliveryAppointment id does not exist")
    if role == "Member":
        o = db["orders"].get(a["order_id"])
        if not o or o.get("member_id") != uid:
            raise err("ERR_FORBIDDEN", "Member may only read own appointments")
    return success_object(appointment_view(a))


@app.route("/delivery-appointments", methods=["GET"])
def list_appointments():
    uid, role = auth()
    require_role(role, {"GalleryAssociate", "HubOperator", "PlatformAdmin"})
    from flask import request as freq
    gallery_id = freq.args.get("gallery_id")
    order_id = freq.args.get("order_id")
    delivery_date = freq.args.get("delivery_date")
    items = list(db["appointments"].values())
    if gallery_id is not None:
        items = [a for a in items if a["gallery_id"] == gallery_id]
    if order_id is not None:
        items = [a for a in items if a["order_id"] == order_id]
    if delivery_date is not None:
        items = [a for a in items if a["delivery_date"] == delivery_date]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    limit, offset = pagination_args()
    page, total = paginate(items, limit, offset)
    return success_list([appointment_view(a) for a in page], limit, offset, total)


@app.route("/delivery-appointments/<aid>/record-outcome", methods=["POST"])
def record_outcome(aid):
    uid, role = auth()
    require_role(role, {"HubOperator"})
    a = db["appointments"].get(aid)
    if not a:
        raise err("ERR_APPOINTMENT_NOT_FOUND", "DeliveryAppointment id does not exist")
    data = body()
    require_fields(data, ["outcome"])
    outcome = check_enum(data["outcome"], {"COMPLETED", "FAILED"}, "outcome")
    if a["status"] != "OUT_FOR_DELIVERY":
        raise err("ERR_INVALID_STATE", "Appointment must be OUT_FOR_DELIVERY")
    if outcome == "COMPLETED":
        a["packaging_removed"] = bool(data.get("packaging_removed", False))
        a["status"] = "COMPLETED"
        touch(a)
        sync_booked_route_minutes(a["gallery_id"])
        g = db["galleries"].get(a["gallery_id"])
        if g:
            touch(g)
        # Deliver the order on first COMPLETED appointment
        o = db["orders"].get(a["order_id"])
        if o and o["status"] == "READY_FOR_DELIVERY":
            o["status"] = "DELIVERED"
            o["delivered_at"] = fmt_dt(clock_now())
            touch(o)
            if o.get("member_id"):
                m = db["members"].get(o["member_id"])
                if m:
                    lines = order_lines_of(o["id"])
                    undisc = sum(l["unit_list_price_cents"] * l["qty"] for l in lines)
                    charged = sum(l["line_charged_cents"] for l in lines)
                    m["lifetime_gross_savings_cents"] += (undisc - charged)
                    m["lifetime_net_savings_cents"] = (
                        m["lifetime_gross_savings_cents"] - m["fee_paid_total_cents"])
                    touch(m)
    else:  # FAILED
        if not data.get("failure_reason"):
            raise err("ERR_INVALID_REQUEST", "failure_reason is required")
        a["failure_reason"] = data["failure_reason"]
        a["status"] = "FAILED"
        touch(a)
        sync_booked_route_minutes(a["gallery_id"])
        g = db["galleries"].get(a["gallery_id"])
        if g:
            touch(g)
    return success_object(appointment_view(a))


# ===========================================================================
# Returns
# ===========================================================================

@app.route("/returns", methods=["POST"])
def create_return():
    uid, role = auth()
    require_role(role, {"Member", "TradeDesigner", "GalleryAssociate"})
    data = body()
    require_fields(data, ["order_id", "order_line_ids"])
    o = db["orders"].get(data["order_id"])
    if not o:
        raise err("ERR_ORDER_NOT_FOUND", "Order id does not exist")
    check_order_access(o, uid, role)
    if o["status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "Order must be DELIVERED")
    if not isinstance(data["order_line_ids"], list) or not data["order_line_ids"]:
        raise err("ERR_INVALID_REQUEST", "order_line_ids must be a non-empty array")
    # Temporal: within 30 days of delivered_at
    if clock_now() > parse_dt(o["delivered_at"]) + timedelta(days=RETURN_WINDOW_DAYS):
        raise err("ERR_RETURN_WINDOW_CLOSED",
                  "Return created more than 30 days after delivered_at")
    lines = []
    for lid in data["order_line_ids"]:
        l = db["order_lines"].get(lid)
        if not l or l["order_id"] != o["id"]:
            raise err("ERR_LINE_NOT_FOUND", "OrderLine id does not exist within the order")
        lines.append(l)
    for l in lines:
        if l["kind"] != "STOCK":
            raise err("ERR_CUSTOM_NON_RETURNABLE", "Custom lines are non-returnable")
    r = init_common({
        "order_id": o["id"],
        "order_line_ids": list(data["order_line_ids"]),
        "status": "REQUESTED",
        "restocking_fee_cents": 0,
        "refund_cents": 0,
        "reason": None,
        "decided_at": None,
    })
    db["returns"][r["id"]] = r
    return success_object(return_view(r), 201)


@app.route("/returns/<rid>", methods=["GET"])
def get_return(rid):
    uid, role = auth()
    require_role(role, {"Member", "TradeDesigner", "GalleryAssociate", "PlatformAdmin"})
    r = db["returns"].get(rid)
    if not r:
        raise err("ERR_RETURN_NOT_FOUND", "ReturnRequest id does not exist")
    o = db["orders"].get(r["order_id"])
    if o:
        check_order_access(o, uid, role)
    return success_object(return_view(r))


@app.route("/returns", methods=["GET"])
def list_returns():
    uid, role = auth()
    require_role(role, {"GalleryAssociate", "PlatformAdmin"})
    from flask import request as freq
    order_id = freq.args.get("order_id")
    status = freq.args.get("status")
    items = list(db["returns"].values())
    if order_id is not None:
        items = [r for r in items if r["order_id"] == order_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    limit, offset = pagination_args()
    page, total = paginate(items, limit, offset)
    return success_list([return_view(r) for r in page], limit, offset, total)


@app.route("/returns/<rid>/settle", methods=["POST"])
def settle_return(rid):
    uid, role = auth()
    require_role(role, {"GalleryAssociate"})
    r = db["returns"].get(rid)
    if not r:
        raise err("ERR_RETURN_NOT_FOUND", "ReturnRequest id does not exist")
    data = body()
    require_fields(data, ["decision"])
    decision = check_enum(data["decision"], {"APPROVE", "REJECT"}, "decision")
    if r["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Return request is not REQUESTED")
    if decision == "APPROVE":
        fee = 0
        total_charged = 0
        for lid in r["order_line_ids"]:
            l = db["order_lines"].get(lid)
            if l:
                fee += core.rhu_frac(l["line_charged_cents"], "0.15")
                total_charged += l["line_charged_cents"]
        r["restocking_fee_cents"] = fee
        r["refund_cents"] = total_charged - fee
        r["status"] = "SETTLED"
    else:
        if not data.get("reason"):
            raise err("ERR_INVALID_REQUEST", "reason is required for REJECT")
        r["reason"] = data["reason"]
        r["refund_cents"] = 0
        r["status"] = "REJECTED"
    r["decided_at"] = fmt_dt(clock_now())
    touch(r)
    return success_object(return_view(r))


# ===========================================================================
# Clock and ops
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock_endpoint():
    uid, role = auth()
    require_role(role, {"PlatformAdmin"})
    data = body()
    require_fields(data, ["to_iso8601"])
    try:
        dt = parse_dt(data["to_iso8601"])
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be ISO 8601")
    set_clock(dt)
    return success_empty()


@app.route("/_ops/run_daily_cycle", methods=["POST"])
def run_daily_cycle_endpoint():
    uid, role = auth()
    require_role(role, {"PlatformAdmin"})
    run_daily_cycle()
    return success_empty()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
