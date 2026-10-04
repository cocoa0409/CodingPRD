"""Co-op claims."""
from flask import Blueprint, request

import db
import services
from errors import (
    err_not_found, err_invalid_request, err_invalid_state,
    err_dealer_not_active, err_claim_window, err_coop_funds,
)
from response import (
    body, get_auth, require_roles, require_dealer_principal, success_obj,
    paginate, req_string, req_int, req_ts,
)

bp = Blueprint("coop", __name__)

READ = ["PlatformAdmin", "RegionManager", "ChannelDirector", "DealerPrincipal"]


def _serialize(c):
    return dict(c)


@bp.post("/coop-claims")
def create_claim():
    user_id, role = get_auth()
    require_roles(role, ["DealerPrincipal"])
    data = body()
    dealer_id = req_string(data, "dealer_id")
    amount = req_int(data, "amount_cents")
    description = req_string(data, "description")
    activity_date = req_ts(data, "activity_date")
    dealer = db.dealers.get(dealer_id)
    if dealer is None:
        raise err_not_found("dealer_id not found")
    require_dealer_principal(user_id, role, dealer_id)
    if dealer["status"] != "ACTIVE":
        raise err_dealer_not_active("co-op claims require dealer ACTIVE")
    if not services.claim_window_ok(activity_date):
        raise err_claim_window()
    if amount <= 0:
        raise err_invalid_request("amount_cents must be > 0")
    rec = db.new_common()
    rec.update({
        "dealer_id": dealer_id,
        "amount_cents": amount,
        "description": description,
        "activity_date": db.fmt_ts(activity_date),
        "status": "SUBMITTED",
    })
    db.coop_claims[rec["id"]] = rec
    return success_obj(_serialize(rec), 201)


@bp.get("/coop-claims")
def list_claims():
    _, role = get_auth()
    require_roles(role, READ)
    items = list(db.coop_claims.values())
    dealer_id = request.args.get("dealer_id")
    if dealer_id is not None:
        items = [c for c in items if c["dealer_id"] == dealer_id]
    return paginate([_serialize(c) for c in items])


@bp.get("/coop-claims/<cid>")
def get_claim(cid):
    _, role = get_auth()
    require_roles(role, READ)
    c = db.coop_claims.get(cid)
    if c is None:
        raise err_not_found("coop claim not found")
    return success_obj(_serialize(c))


def _get_claim_or_404(cid):
    c = db.coop_claims.get(cid)
    if c is None:
        raise err_not_found("coop claim not found")
    return c


@bp.post("/coop-claims/<cid>/approve")
def approve_claim(cid):
    _, role = get_auth()
    require_roles(role, ["ChannelDirector"])
    c = _get_claim_or_404(cid)
    if c["status"] != "SUBMITTED":
        raise err_invalid_state("claim is not SUBMITTED")
    dealer = db.dealers.get(c["dealer_id"])
    if dealer is None:
        raise err_not_found("dealer not found")
    activity = db.parse_ts(c["activity_date"])
    if activity is None or not services.claim_window_ok(activity):
        raise err_claim_window()
    if dealer["status"] != "ACTIVE":
        raise err_dealer_not_active("claim approval requires dealer ACTIVE")
    if not dealer.get("branding_compliant") or dealer.get("coop_balance_cents", 0) < c["amount_cents"]:
        raise err_coop_funds()
    c["status"] = "APPROVED"
    db.touch(c)
    dealer["coop_pending_cents"] = dealer.get("coop_pending_cents", 0) + c["amount_cents"]
    db.touch(dealer)
    return success_obj(_serialize(c))


@bp.post("/coop-claims/<cid>/reject")
def reject_claim(cid):
    _, role = get_auth()
    require_roles(role, ["ChannelDirector"])
    c = _get_claim_or_404(cid)
    if c["status"] != "SUBMITTED":
        raise err_invalid_state("claim is not SUBMITTED")
    c["status"] = "REJECTED"
    db.touch(c)
    return success_obj(_serialize(c))


@bp.post("/coop-claims/<cid>/pay")
def pay_claim(cid):
    _, role = get_auth()
    require_roles(role, ["ChannelDirector"])
    c = _get_claim_or_404(cid)
    if c["status"] != "APPROVED":
        raise err_invalid_state("claim is not APPROVED")
    dealer = db.dealers.get(c["dealer_id"])
    c["status"] = "PAID"
    db.touch(c)
    if dealer is not None:
        dealer["coop_pending_cents"] = dealer.get("coop_pending_cents", 0) - c["amount_cents"]
        dealer["coop_balance_cents"] = dealer.get("coop_balance_cents", 0) - c["amount_cents"]
        db.touch(dealer)
    return success_obj(_serialize(c))
