"""Payout endpoints."""
from flask import Blueprint, request

import db
import helpers
from errors import (
    err_validation, err_invalid_state, err_affiliate_not_active, err_unauthorized,
)
from middleware import get_auth, require_roles
from response import ok_object, ok_list, paginate

bp = Blueprint("payouts", __name__)


def payout_view(p):
    return {
        "id": p["id"],
        "affiliate_store_id": p.get("affiliate_store_id"),
        "affiliate_partner_id": p.get("affiliate_partner_id"),
        "amount_cents": p["amount_cents"],
        "status": p["status"],
        "failure_reason": p.get("failure_reason"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def _get_affiliate(p):
    if p.get("affiliate_store_id"):
        return db.DB.stores.get(p["affiliate_store_id"])
    return db.DB.partners.get(p.get("affiliate_partner_id"))


@bp.get("/bookshop/payouts/<pid>")
def get_payout(pid):
    require_roles(["FinanceOps", "PlatformAdmin", "StoreManager", "Partner"])
    p = helpers.get_or_404(db.DB.payouts, pid)
    return ok_object(payout_view(p))


@bp.get("/bookshop/payouts")
def list_payouts():
    require_roles(["FinanceOps", "PlatformAdmin", "StoreManager", "Partner"])
    args = request.args
    payouts = list(db.DB.payouts.values())
    for key in ("affiliate_store_id", "affiliate_partner_id", "status"):
        v = args.get(key)
        if v is not None:
            payouts = [p for p in payouts if p.get(key) == v]
    page, limit, offset, total = paginate([payout_view(p) for p in payouts], args)
    return ok_list(page, limit, offset, total)


@bp.post("/bookshop/payouts/<pid>/actions")
def payout_actions(pid):
    user_id, role = get_auth()
    p = helpers.get_or_404(db.DB.payouts, pid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    action = body.get("action")
    if action not in ("process", "mark-paid", "fail", "retry"):
        if action is None or not isinstance(action, str):
            raise err_validation("action is required")
        raise err_invalid_state("Unknown action: %s" % action)
    if role != "FinanceOps":
        raise err_unauthorized()

    if action == "process":
        if p["status"] != "PENDING":
            raise err_invalid_state("payout must be PENDING to process")
        affiliate = _get_affiliate(p)
        if affiliate is None or affiliate["status"] != "ACTIVE":
            raise err_affiliate_not_active()
        p["status"] = "PROCESSING"
        helpers.touch(p)
    elif action == "mark-paid":
        if p["status"] != "PROCESSING":
            raise err_invalid_state("payout must be PROCESSING to mark paid")
        p["status"] = "PAID"
        helpers.touch(p)
        helpers.reconcile_affiliate(store_id=p.get("affiliate_store_id"),
                                    partner_id=p.get("affiliate_partner_id"))
    elif action == "fail":
        if p["status"] != "PROCESSING":
            raise err_invalid_state("payout must be PROCESSING to fail")
        reason = body.get("failure_reason")
        if reason is not None and not isinstance(reason, str):
            raise err_validation("failure_reason must be a string")
        p["failure_reason"] = reason
        p["status"] = "FAILED"
        helpers.touch(p)
    elif action == "retry":
        if p["status"] != "FAILED":
            raise err_invalid_state("payout must be FAILED to retry")
        p["failure_reason"] = None
        p["status"] = "PENDING"
        helpers.touch(p)
    return ok_object(payout_view(p))
