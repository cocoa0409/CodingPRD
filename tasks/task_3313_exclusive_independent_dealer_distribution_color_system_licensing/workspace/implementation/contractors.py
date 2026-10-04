"""Contractor accounts and purchases."""
from decimal import Decimal

from flask import Blueprint, request

import db
import services
from errors import (
    err_not_found, err_invalid_request, err_invalid_state,
    err_dealer_not_active, err_license_not_active, err_equipment_not_calibrated,
    err_rematch_required, err_reference_inactive,
)
from response import (
    body, get_auth, require_roles, require_dealer_principal, success_obj,
    paginate, req_string, req_int,
)

bp = Blueprint("contractors", __name__)

READ = ["PlatformAdmin", "RegionManager", "ChannelDirector", "DealerPrincipal"]


def _serialize_account(c):
    return dict(c)


def _serialize_purchase(p):
    return dict(p)


# ---------------- accounts ----------------

@bp.post("/contractors")
def create_contractor():
    user_id, role = get_auth()
    require_roles(role, ["DealerPrincipal"])
    data = body()
    dealer_id = req_string(data, "dealer_id")
    company_name = req_string(data, "company_name")
    dealer = db.dealers.get(dealer_id)
    if dealer is None:
        raise err_not_found("dealer_id not found")
    require_dealer_principal(user_id, role, dealer_id)
    if dealer["status"] != "ACTIVE":
        raise err_dealer_not_active("contractor enrollment requires dealer ACTIVE")
    rec = db.new_common()
    rec.update({
        "dealer_id": dealer_id,
        "company_name": company_name,
        "enrolled_on": db.fmt_ts(db.now()),
        "rolling_net_spend_cents": 0,
        "tier": "STANDARD",
        "status": "ACTIVE",
    })
    db.contractors[rec["id"]] = rec
    return success_obj(_serialize_account(rec), 201)


@bp.get("/contractors")
def list_contractors():
    _, role = get_auth()
    require_roles(role, READ)
    items = list(db.contractors.values())
    dealer_id = request.args.get("dealer_id")
    if dealer_id is not None:
        items = [c for c in items if c["dealer_id"] == dealer_id]
    for c in items:
        services.recompute_contractor_spend(c)
    return paginate([_serialize_account(c) for c in items])


@bp.get("/contractors/<cid>")
def get_contractor(cid):
    _, role = get_auth()
    require_roles(role, READ)
    c = db.contractors.get(cid)
    if c is None:
        raise err_not_found("contractor account not found")
    services.recompute_contractor_spend(c)
    return success_obj(_serialize_account(c))


@bp.post("/contractors/<cid>/close")
def close_contractor(cid):
    user_id, role = get_auth()
    require_roles(role, ["DealerPrincipal"])
    c = db.contractors.get(cid)
    if c is None:
        raise err_not_found("contractor account not found")
    require_dealer_principal(user_id, role, c["dealer_id"])
    if c["status"] != "ACTIVE":
        raise err_invalid_state("contractor account is not ACTIVE")
    c["status"] = "CLOSED"
    db.touch(c)
    return success_obj(_serialize_account(c))


# ---------------- purchases ----------------

@bp.post("/purchases")
def create_purchase():
    user_id, role = get_auth()
    require_roles(role, ["DealerPrincipal"])
    data = body()
    account_id = req_string(data, "contractor_account_id")
    product_line_id = req_string(data, "product_line_id")
    units = req_int(data, "units")
    account = db.contractors.get(account_id)
    if account is None:
        raise err_not_found("contractor_account_id not found")
    pl = db.product_lines.get(product_line_id)
    if pl is None:
        raise err_not_found("product_line_id not found")
    dealer_id = account["dealer_id"]
    require_dealer_principal(user_id, role, dealer_id)
    dealer = db.dealers.get(dealer_id)
    # state gate: dealer ACTIVE
    if dealer is None or dealer["status"] != "ACTIVE":
        raise err_dealer_not_active("purchases require dealer ACTIVE")
    # license gate
    services.sweep_licenses([l for l in db.licenses.values() if l["dealer_id"] == dealer_id])
    has_license = any(
        l["dealer_id"] == dealer_id
        and l["colorant_system_id"] == pl["colorant_system_id"]
        and l["status"] == "ACTIVE"
        for l in db.licenses.values()
    )
    if not has_license:
        raise err_license_not_active()
    # calibrated-equipment gate for DEALER_EXCLUSIVE lines
    if pl["channel_class"] == "DEALER_EXCLUSIVE":
        services.sweep_equipment([u for u in db.equipment.values() if u["dealer_id"] == dealer_id])
        has_calibrated = any(
            u["dealer_id"] == dealer_id
            and u["colorant_system_id"] == pl["colorant_system_id"]
            and u["status"] == "CALIBRATED"
            for u in db.equipment.values()
        )
        if not has_calibrated:
            raise err_equipment_not_calibrated()
    # rematch gate
    if services.dealer_has_pending_rematch_for_line(dealer_id, product_line_id):
        raise err_rematch_required()
    # reward-points shape (priority 21) before general shape (22)
    points = data.get("reward_points_redeemed", 0)
    if isinstance(points, bool) or not isinstance(points, int):
        raise err_invalid_request("reward_points_redeemed must be an integer")
    if points < 0:
        raise err_invalid_request("reward_points_redeemed must be >= 0")
    refund = data.get("refund_cents", 0)
    if isinstance(refund, bool) or not isinstance(refund, int):
        raise err_invalid_request("refund_cents must be an integer")
    if units <= 0:
        raise err_invalid_request("units must be > 0")
    if refund < 0:
        raise err_invalid_request("refund_cents must be >= 0")
    # reference-active gate
    if pl["status"] == "DISCONTINUED":
        raise err_reference_inactive("product line is DISCONTINUED")
    # pricing
    services.recompute_contractor_spend(account)
    tier_at_post = account["tier"]
    discount = services.TIER_DISCOUNT[tier_at_post]
    unit_price = services.round_half_up_int(Decimal(pl["base_price_cents"]) * (Decimal(1) - discount))
    invoice = units * unit_price
    if refund > invoice:
        raise err_invalid_request("refund_cents exceeds invoice_cents")
    redemption = min(points, invoice)
    rec = {
        "id": db.new_id(),
        "created_at": db.fmt_ts(db.now()),
    }
    rec.update({
        "contractor_account_id": account_id,
        "product_line_id": product_line_id,
        "units": units,
        "reward_points_redeemed": points,
        "unit_price_cents": unit_price,
        "invoice_cents": invoice,
        "reward_points_redemption_cents": redemption,
        "refund_cents": refund,
        "tier_at_post": tier_at_post,
        "status": "POSTED",
    })
    db.purchases[rec["id"]] = rec
    services.recompute_contractor_spend(account)
    db.touch(account)
    return success_obj(_serialize_purchase(rec), 201)


@bp.get("/purchases")
def list_purchases():
    _, role = get_auth()
    require_roles(role, READ)
    items = list(db.purchases.values())
    account_id = request.args.get("contractor_account_id")
    pl_id = request.args.get("product_line_id")
    if account_id is not None:
        items = [p for p in items if p["contractor_account_id"] == account_id]
    if pl_id is not None:
        items = [p for p in items if p["product_line_id"] == pl_id]
    return paginate([_serialize_purchase(p) for p in items])


@bp.get("/purchases/<pid>")
def get_purchase(pid):
    _, role = get_auth()
    require_roles(role, READ)
    p = db.purchases.get(pid)
    if p is None:
        raise err_not_found("purchase not found")
    return success_obj(_serialize_purchase(p))


@bp.post("/purchases/<pid>/void")
def void_purchase(pid):
    user_id, role = get_auth()
    require_roles(role, ["DealerPrincipal"])
    p = db.purchases.get(pid)
    if p is None:
        raise err_not_found("purchase not found")
    account = db.contractors.get(p["contractor_account_id"])
    if account is None:
        raise err_not_found("contractor account not found")
    require_dealer_principal(user_id, role, account["dealer_id"])
    if p["status"] != "POSTED":
        raise err_invalid_state("purchase is not POSTED")
    p["status"] = "VOIDED"
    services.recompute_contractor_spend(account)
    db.touch(account)
    return success_obj(_serialize_purchase(p))
