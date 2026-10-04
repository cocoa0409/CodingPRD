"""Dealer orders."""
from decimal import Decimal

from flask import Blueprint, request

import db
import services
from errors import (
    err_not_found, err_invalid_request, err_invalid_state,
    err_dealer_not_active, err_reference_inactive, err_min_inventory,
)
from response import (
    body, get_auth, require_roles, require_dealer_principal, success_obj,
    paginate, req_string, req_int, req_enum,
)

bp = Blueprint("orders", __name__)

READ = ["PlatformAdmin", "RegionManager", "ChannelDirector", "DealerPrincipal"]


def _serialize(o):
    return dict(o)


@bp.post("/orders")
def create_order():
    user_id, role = get_auth()
    require_roles(role, ["DealerPrincipal"])
    data = body()
    dealer_id = req_string(data, "dealer_id")
    product_line_id = req_string(data, "product_line_id")
    units = req_int(data, "units")
    purpose = req_enum(data, "purpose", {"INITIAL_STOCK", "RESTOCK"})
    dealer = db.dealers.get(dealer_id)
    if dealer is None:
        raise err_not_found("dealer_id not found")
    pl = db.product_lines.get(product_line_id)
    if pl is None:
        raise err_not_found("product_line_id not found")
    require_dealer_principal(user_id, role, dealer_id)
    if dealer["status"] not in ("ONBOARDING", "ACTIVE"):
        raise err_dealer_not_active("orders require dealer ONBOARDING or ACTIVE")
    if units <= 0:
        raise err_invalid_request("units must be > 0")
    if purpose == "INITIAL_STOCK":
        # need the licensed colorant system's minimum; dealer's license for
        # the ordered line's system determines the minimum.
        min_units = None
        for lic in db.licenses.values():
            if lic["dealer_id"] == dealer_id and lic["colorant_system_id"] == pl["colorant_system_id"]:
                cs = db.colorant_systems.get(lic["colorant_system_id"])
                if cs is not None:
                    min_units = cs["min_initial_inventory_units"] if min_units is None else max(min_units, cs["min_initial_inventory_units"])
        if min_units is None:
            cs = db.colorant_systems.get(pl["colorant_system_id"])
            min_units = cs["min_initial_inventory_units"] if cs else None
        if min_units is not None and units < min_units:
            raise err_min_inventory()
    if pl["status"] == "DISCONTINUED":
        raise err_reference_inactive("product line is DISCONTINUED")
    rec = db.new_common()
    unit_price = pl["base_price_cents"]
    rec.update({
        "dealer_id": dealer_id,
        "product_line_id": product_line_id,
        "units": units,
        "purpose": purpose,
        "unit_price_cents": unit_price,
        "invoice_cents": units * unit_price,
        "coop_accrued_cents": 0,
        "status": "SUBMITTED",
    })
    db.orders[rec["id"]] = rec
    return success_obj(_serialize(rec), 201)


@bp.get("/orders")
def list_orders():
    _, role = get_auth()
    require_roles(role, READ)
    items = list(db.orders.values())
    dealer_id = request.args.get("dealer_id")
    status = request.args.get("status")
    pl_id = request.args.get("product_line_id")
    if dealer_id is not None:
        items = [o for o in items if o["dealer_id"] == dealer_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if pl_id is not None:
        items = [o for o in items if o["product_line_id"] == pl_id]
    return paginate([_serialize(o) for o in items])


@bp.get("/orders/<oid>")
def get_order(oid):
    _, role = get_auth()
    require_roles(role, READ)
    o = db.orders.get(oid)
    if o is None:
        raise err_not_found("order not found")
    return success_obj(_serialize(o))


def _get_order_or_404(oid):
    o = db.orders.get(oid)
    if o is None:
        raise err_not_found("order not found")
    return o


def _transition(oid, allowed_from, to):
    o = _get_order_or_404(oid)
    if o["status"] != allowed_from:
        raise err_invalid_state(f"order is not {allowed_from}")
    o["status"] = to
    db.touch(o)
    return o


@bp.post("/orders/<oid>/approve")
def approve_order(oid):
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    o = _transition(oid, "SUBMITTED", "APPROVED")
    return success_obj(_serialize(o))


@bp.post("/orders/<oid>/reject")
def reject_order(oid):
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    o = _transition(oid, "SUBMITTED", "REJECTED")
    return success_obj(_serialize(o))


@bp.post("/orders/<oid>/fulfill")
def fulfill_order(oid):
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    o = _transition(oid, "APPROVED", "FULFILLED")
    return success_obj(_serialize(o))


@bp.post("/orders/<oid>/invoice")
def invoice_order(oid):
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    o = _transition(oid, "FULFILLED", "INVOICED")
    dealer = db.dealers.get(o["dealer_id"])
    if dealer is not None:
        if o["purpose"] == "INITIAL_STOCK":
            dealer["inventory_minimum_met"] = True
        services.refresh_annual_net_purchase(dealer)
        db.touch(dealer)
    return success_obj(_serialize(o))


@bp.post("/orders/<oid>/pay")
def pay_order(oid):
    user_id, role = get_auth()
    require_roles(role, ["DealerPrincipal"])
    o = _get_order_or_404(oid)
    require_dealer_principal(user_id, role, o["dealer_id"])
    if o["status"] != "INVOICED":
        raise err_invalid_state("order is not INVOICED")
    dealer = db.dealers.get(o["dealer_id"])
    rate = Decimal(str(dealer["coop_accrual_rate"])) if dealer is not None else Decimal("0")
    accrued = services.round_half_up_int(Decimal(o["invoice_cents"]) * rate)
    o["coop_accrued_cents"] = accrued
    o["status"] = "PAID"
    db.touch(o)
    if dealer is not None:
        dealer["coop_balance_cents"] = dealer.get("coop_balance_cents", 0) + accrued
        services.refresh_annual_net_purchase(dealer)
        db.touch(dealer)
    return success_obj(_serialize(o))


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = get_auth()
    require_roles(role, ["DealerPrincipal"])
    o = _get_order_or_404(oid)
    require_dealer_principal(user_id, role, o["dealer_id"])
    if o["status"] not in ("SUBMITTED", "APPROVED"):
        raise err_invalid_state("order is not SUBMITTED or APPROVED")
    o["status"] = "CANCELLED"
    db.touch(o)
    return success_obj(_serialize(o))
