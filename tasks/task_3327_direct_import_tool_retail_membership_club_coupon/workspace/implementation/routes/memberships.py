"""Membership endpoints."""
from datetime import timedelta
from flask import Blueprint, request
from db import DB, fmt_iso
from response import success
from middleware import require_roles, current_identity
from entities import stamp_new, touch, get_or_404, lazy_membership, membership_of
from errors import raise_err
from calc import renewal_fee

bp = Blueprint("memberships", __name__)

READ_ROLES = ("StoreClerk", "Customer", "WarrantyAdjuster", "OpsAdmin")
GET_ROLES = ("StoreClerk", "Customer", "WarrantyAdjuster", "OpsAdmin", "MarketingManager")


def m_view(m):
    return dict(m)


def _check_customer_access(customer_id):
    uid, role = current_identity()
    if role == "Customer" and uid != customer_id:
        raise_err("ERR_FORBIDDEN", "Customers may only access their own membership")


@bp.route("/customers/<id>/membership", methods=["POST"])
@require_roles("StoreClerk", "Customer")
def enroll(id):
    customer = get_or_404(DB.customers, id)
    _check_customer_access(customer["id"])
    b = request.get_json(silent=True) or {}
    tier = b.get("tier")
    if tier not in ("CLUB", "CLUB_PLUS"):
        raise_err("ERR_VALIDATION", "tier must be CLUB or CLUB_PLUS")
    if membership_of(customer["id"]):
        raise_err("ERR_MEMBERSHIP_EXISTS", "Customer already has a membership")
    now = DB.now()
    expires = now + timedelta(days=365)
    rec = stamp_new({
        "customer_id": customer["id"],
        "tier": tier,
        "status": "ACTIVE",
        "started_at": fmt_iso(now),
        "expires_at": fmt_iso(expires),
        "return_window_days": 90,
        "settled_savings_cents": 0,
        "optimistic_savings_cents": 0,
        "renewal_fee_cents": renewal_fee(tier, 0),
    })
    DB.memberships[rec["id"]] = rec
    return success(m_view(rec), status=201)


@bp.route("/customers/<id>/membership", methods=["GET"])
@require_roles(*READ_ROLES)
def get_customer_membership(id):
    customer = get_or_404(DB.customers, id)
    _check_customer_access(customer["id"])
    m = membership_of(customer["id"])
    if not m:
        raise_err("ERR_NOT_FOUND", "Customer has no membership")
    lazy_membership(m)
    from savings import recompute_membership_savings
    recompute_membership_savings(m["customer_id"])
    return success([m_view(m)], response_type="array")


@bp.route("/memberships/<membershipId>", methods=["GET"])
@require_roles(*GET_ROLES)
def get_membership(membershipId):
    m = get_or_404(DB.memberships, membershipId)
    _check_customer_access(m["customer_id"])
    lazy_membership(m)
    from savings import recompute_membership_savings
    recompute_membership_savings(m["customer_id"])
    return success(m_view(m))


@bp.route("/memberships/<membershipId>/renew", methods=["POST"])
@require_roles("StoreClerk", "Customer")
def renew(membershipId):
    m = get_or_404(DB.memberships, membershipId)
    _check_customer_access(m["customer_id"])
    lazy_membership(m)
    if m["status"] == "CANCELLED":
        raise_err("ERR_INVALID_STATE", "Membership CANCELLED")
    now = DB.now()
    from db import parse_iso
    exp = parse_iso(m["expires_at"])
    if m["status"] == "LAPSED":
        if now >= exp + timedelta(days=30):
            raise_err("ERR_RENEWAL_WINDOW_CLOSED", "Renewal grace window closed")
    new_exp = max(exp, now) + timedelta(days=365)
    m["expires_at"] = fmt_iso(new_exp)
    m["renewal_fee_cents"] = renewal_fee(m["tier"], m["settled_savings_cents"])
    m["status"] = "ACTIVE"
    touch(m)
    return success(m_view(m))


@bp.route("/memberships/<membershipId>/cancel", methods=["POST"])
@require_roles("StoreClerk", "Customer")
def cancel(membershipId):
    m = get_or_404(DB.memberships, membershipId)
    _check_customer_access(m["customer_id"])
    lazy_membership(m)
    if m["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Membership not ACTIVE")
    m["status"] = "CANCELLED"
    touch(m)
    return success(m_view(m))
