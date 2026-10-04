"""Affiliate stores and partners endpoints."""
from flask import Blueprint, request

import db
import helpers
from errors import (
    err_validation, err_invalid_state, err_commercial_terms,
    err_store_settlement, err_unauthorized,
)
from middleware import get_auth, require_roles, require_owner
from response import ok_object, ok_list, paginate

bp = Blueprint("affiliates", __name__)


def store_view(s):
    return {
        "id": s["id"],
        "shop_name": s["shop_name"],
        "slug": s["slug"],
        "commission_pct": s["commission_pct"],
        "pool_opt_in": s["pool_opt_in"],
        "payout_threshold_cents": s["payout_threshold_cents"],
        "status": s["status"],
        "activated_at": s.get("activated_at"),
        "suspended_at": s.get("suspended_at"),
        "accrued_balance_cents": s["accrued_balance_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def partner_view(p):
    return {
        "id": p["id"],
        "display_name": p["display_name"],
        "partner_kind": p["partner_kind"],
        "commission_pct": p["commission_pct"],
        "payout_threshold_cents": p["payout_threshold_cents"],
        "status": p["status"],
        "accrued_balance_cents": p["accrued_balance_cents"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/bookshop/stores")
def create_store():
    require_roles(["PlatformAdmin"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    shop_name = body.get("shop_name")
    slug = body.get("slug")
    commission_pct = body.get("commission_pct")
    pool_opt_in = body.get("pool_opt_in", True)
    payout_threshold_cents = body.get("payout_threshold_cents", 2500)

    if not isinstance(shop_name, str) or not shop_name:
        raise err_validation("shop_name is required")
    if not isinstance(slug, str) or not slug:
        raise err_validation("slug is required")
    if not isinstance(commission_pct, (int, float)) or isinstance(commission_pct, bool):
        raise err_validation("commission_pct must be a number")
    if not isinstance(pool_opt_in, bool):
        raise err_validation("pool_opt_in must be a boolean")
    if not isinstance(payout_threshold_cents, int) or isinstance(payout_threshold_cents, bool):
        raise err_validation("payout_threshold_cents must be an integer")

    norm_slug = slug.lower()
    if any(s["slug"].lower() == norm_slug for s in db.DB.stores.values()):
        raise err_validation("slug must be unique")

    if not (0.10 <= commission_pct <= 0.30):
        raise err_commercial_terms("commission_pct must be within 0.10-0.30")
    if payout_threshold_cents < 2500:
        raise err_commercial_terms("payout_threshold_cents must be >= 2500")

    s = helpers.base_resource()
    s.update({
        "shop_name": shop_name,
        "slug": slug,
        "commission_pct": commission_pct,
        "pool_opt_in": pool_opt_in,
        "payout_threshold_cents": payout_threshold_cents,
        "status": "PENDING_ONBOARDING",
        "activated_at": None,
        "suspended_at": None,
        "accrued_balance_cents": 0,
    })
    db.DB.stores[s["id"]] = s
    return ok_object(store_view(s), 201)


@bp.get("/bookshop/stores/<sid>")
def get_store(sid):
    _, role = require_roles(["PlatformAdmin", "StoreManager", "FinanceOps", "CustomerService"])
    s = helpers.get_or_404(db.DB.stores, sid)
    if role == "StoreManager":
        require_owner(sid)
    return ok_object(store_view(s))


@bp.get("/bookshop/stores/<sid>/lists")
def list_store_lists(sid):
    _, role = require_roles(["PlatformAdmin", "StoreManager", "Partner", "Customer"])
    helpers.get_or_404(db.DB.stores, sid)
    if role == "StoreManager":
        require_owner(sid)
    lists = [l for l in db.DB.lists.values() if l["owner_store_id"] == sid]
    from routes.lists import list_view
    page, limit, offset, total = paginate([list_view(l) for l in lists], request.args)
    return ok_list(page, limit, offset, total)


@bp.post("/bookshop/stores/<sid>/actions")
def store_actions(sid):
    user_id, role = get_auth()
    s = helpers.get_or_404(db.DB.stores, sid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    action = body.get("action")
    if action not in ("activate", "suspend", "reactivate", "deactivate"):
        if action is None or not isinstance(action, str):
            raise err_validation("action is required")
        raise err_invalid_state("Unknown action: %s" % action)
    if role != "PlatformAdmin":
        raise err_unauthorized()

    if action == "activate":
        if s["status"] != "PENDING_ONBOARDING":
            raise err_invalid_state("store must be PENDING_ONBOARDING to activate")
        s["activated_at"] = db.logical_now_iso()
        s["_activated_at_dt"] = db.get_clock()
        s["suspended_at"] = None
        s["_suspended_at_dt"] = None
        s["status"] = "ACTIVE"
        helpers.touch(s)
    elif action == "suspend":
        if s["status"] != "ACTIVE":
            raise err_invalid_state("store must be ACTIVE to suspend")
        s["suspended_at"] = db.logical_now_iso()
        s["_suspended_at_dt"] = db.get_clock()
        s["status"] = "SUSPENDED"
        helpers.touch(s)
    elif action == "reactivate":
        if s["status"] != "SUSPENDED":
            raise err_invalid_state("store must be SUSPENDED to reactivate")
        s["activated_at"] = db.logical_now_iso()
        s["_activated_at_dt"] = db.get_clock()
        s["suspended_at"] = None
        s["_suspended_at_dt"] = None
        s["status"] = "ACTIVE"
        helpers.touch(s)
    elif action == "deactivate":
        if s["status"] not in ("ACTIVE", "SUSPENDED"):
            raise err_invalid_state("store must be ACTIVE or SUSPENDED to deactivate")
        open_payout = any(p for p in db.DB.payouts.values()
                          if p.get("affiliate_store_id") == sid
                          and p["status"] in ("PENDING", "PROCESSING"))
        if s["accrued_balance_cents"] != 0 or open_payout:
            raise err_store_settlement()
        s["status"] = "DEACTIVATED"
        helpers.touch(s)
    return ok_object(store_view(s))


@bp.post("/bookshop/partners")
def create_partner():
    require_roles(["PlatformAdmin"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    display_name = body.get("display_name")
    partner_kind = body.get("partner_kind")
    commission_pct = body.get("commission_pct")
    payout_threshold_cents = body.get("payout_threshold_cents", 1000)

    if not isinstance(display_name, str) or not display_name:
        raise err_validation("display_name is required")
    if partner_kind not in ("AUTHOR", "PUBLICATION", "INFLUENCER"):
        raise err_validation("partner_kind must be AUTHOR, PUBLICATION, or INFLUENCER")
    if not isinstance(commission_pct, (int, float)) or isinstance(commission_pct, bool):
        raise err_validation("commission_pct must be a number")
    if not isinstance(payout_threshold_cents, int) or isinstance(payout_threshold_cents, bool):
        raise err_validation("payout_threshold_cents must be an integer")

    if not (0.05 <= commission_pct <= 0.15):
        raise err_commercial_terms("commission_pct must be within 0.05-0.15")
    if payout_threshold_cents < 1000:
        raise err_commercial_terms("payout_threshold_cents must be >= 1000")

    p = helpers.base_resource()
    p.update({
        "display_name": display_name,
        "partner_kind": partner_kind,
        "commission_pct": commission_pct,
        "payout_threshold_cents": payout_threshold_cents,
        "status": "APPLIED",
        "accrued_balance_cents": 0,
    })
    db.DB.partners[p["id"]] = p
    return ok_object(partner_view(p), 201)


@bp.get("/bookshop/partners/<pid>")
def get_partner(pid):
    _, role = require_roles(["PlatformAdmin", "Partner", "FinanceOps"])
    p = helpers.get_or_404(db.DB.partners, pid)
    if role == "Partner":
        require_owner(pid)
    return ok_object(partner_view(p))


@bp.post("/bookshop/partners/<pid>/actions")
def partner_actions(pid):
    user_id, role = get_auth()
    p = helpers.get_or_404(db.DB.partners, pid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    action = body.get("action")
    if action not in ("approve", "reject", "activate", "suspend"):
        if action is None or not isinstance(action, str):
            raise err_validation("action is required")
        raise err_invalid_state("Unknown action: %s" % action)
    if role != "PlatformAdmin":
        raise err_unauthorized()

    if action == "approve":
        if p["status"] != "APPLIED":
            raise err_invalid_state("partner must be APPLIED to approve")
        p["status"] = "APPROVED"
        helpers.touch(p)
    elif action == "reject":
        if p["status"] != "APPLIED":
            raise err_invalid_state("partner must be APPLIED to reject")
        p["status"] = "REJECTED"
        helpers.touch(p)
    elif action == "activate":
        if p["status"] not in ("APPROVED", "SUSPENDED"):
            raise err_invalid_state("partner must be APPROVED or SUSPENDED to activate")
        p["status"] = "ACTIVE"
        helpers.touch(p)
    elif action == "suspend":
        if p["status"] != "ACTIVE":
            raise err_invalid_state("partner must be ACTIVE to suspend")
        p["status"] = "SUSPENDED"
        helpers.touch(p)
    return ok_object(partner_view(p))
