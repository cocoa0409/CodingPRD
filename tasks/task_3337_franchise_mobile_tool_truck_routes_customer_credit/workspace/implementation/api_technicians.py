"""Technician onboarding, attributes and standing."""

from flask import Blueprint

import auth
import clock
import envelope
import lookup
import recompute
import store
from errors import fail

bp = Blueprint("technicians", __name__, url_prefix="/retail")

TECH_ROLES = ("PlatformAdmin", "FranchiseOwner", "FranchiseManager", "CreditOfficer",
              "RouteSalesRep")
STANDING_ACTIONS = ("CHANGE_SHOP", "CONFIRM_SHOP", "CANCEL_SHOP", "EXIT_TRADE")


@bp.post("/technicians")
def onboard_technician():
    user_id, role = auth.require("FranchiseOwner")
    payload = envelope.body()
    full_name = envelope.as_str(payload, "full_name")
    shop_id = envelope.as_str(payload, "current_shop_location_id")
    credit_line_limit_cents = envelope.as_int(payload, "credit_line_limit_cents", minimum=0)
    months_in_trade = envelope.as_int(payload, "months_in_trade", minimum=0)
    employment_verified = envelope.as_bool(payload, "employment_verified")

    shop = lookup.shop(shop_id)
    auth.ensure_owned(user_id, role, auth.shop_owner_id(shop))

    technician = store.create(
        store.technicians,
        full_name=full_name,
        current_shop_location_id=shop["id"],
        technician_status="ACTIVE",
        credit_line_limit_cents=credit_line_limit_cents,
        credit_line_status="ACTIVE",
        home_route_id=shop.get("route_id"),
        last_known_shop_name=None,
        revolving_used_cents=0,
        revolving_available_cents=credit_line_limit_cents,
        open_account_count=0,
        months_in_trade=months_in_trade,
        employment_verified=employment_verified,
    )
    recompute.recompute_technician(technician)
    recompute.recompute_shop(shop)
    return envelope.ok(technician, 201)


@bp.get("/technicians")
def list_technicians():
    user_id, role = auth.require(*TECH_ROLES)
    rows = envelope.filter_query(store.ordered(store.technicians), {
        "current_shop_location_id": "current_shop_location_id",
        "technician_status": "technician_status",
    })
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.get("/technicians/<technician_id>")
def get_technician(technician_id):
    user_id, role = auth.require(*TECH_ROLES, "Technician")
    technician = lookup.technician(technician_id)
    auth.ensure_technician_self(user_id, role, technician["id"])
    recompute.recompute_technician(technician)
    return envelope.ok(technician)


@bp.put("/technicians/<technician_id>")
def update_technician(technician_id):
    user_id, role = auth.require("FranchiseOwner")
    technician = lookup.technician(technician_id)
    if technician.get("technician_status") == "TRADE_EXITED":
        fail("ERR_TECHNICIAN_EXITED")
    auth.ensure_owned(user_id, role, auth.technician_owner_id(technician))
    payload = envelope.body()
    if payload.get("full_name") is not None:
        store.set_field(technician, "full_name", envelope.as_str(payload, "full_name"))
    if payload.get("credit_line_limit_cents") is not None:
        store.set_field(technician, "credit_line_limit_cents",
                        envelope.as_int(payload, "credit_line_limit_cents", minimum=0))
    if payload.get("months_in_trade") is not None:
        store.set_field(technician, "months_in_trade",
                        envelope.as_int(payload, "months_in_trade", minimum=0))
    if payload.get("employment_verified") is not None:
        store.set_field(technician, "employment_verified",
                        envelope.as_bool(payload, "employment_verified"))
    store.stamp(technician)
    recompute.recompute_technician(technician)
    return envelope.ok(technician)


@bp.post("/technicians/<technician_id>/status")
def advance_technician(technician_id):
    user_id, role = auth.require("FranchiseOwner", "FranchiseManager")
    technician = lookup.technician(technician_id)
    if technician.get("technician_status") == "TRADE_EXITED":
        fail("ERR_TECHNICIAN_EXITED")
    auth.ensure_owned(user_id, role, auth.technician_owner_id(technician))
    payload = envelope.body()
    action = envelope.as_enum(payload, "action", STANDING_ACTIONS)

    status = technician.get("technician_status")

    if action == "CHANGE_SHOP":
        if status != "ACTIVE":
            fail("ERR_TECHNICIAN_NOT_ACTIVE")
        target_id = envelope.as_str(payload, "target_shop_location_id")
        target = lookup.shop(target_id)
        auth.ensure_owned(user_id, role, auth.shop_owner_id(target))
        if target.get("shop_status") != "ACTIVE":
            fail("ERR_INVALID_STATE", "The target shop is not ACTIVE.")
        for account in store.accounts.values():
            if account.get("technician_id") == technician["id"]:
                if account.get("account_status") not in ("ACTIVE", "SUSPENDED",
                                                         "DELINQUENT", "CHARGED_OFF"):
                    fail("ERR_INVALID_STATE", "The technician holds a CLOSED credit account.")
        source = store.shops.get(technician.get("current_shop_location_id"))
        store.technician_prior_shop[technician["id"]] = technician.get("current_shop_location_id")
        technician["current_shop_location_id"] = target["id"]
        store.set_field(technician, "technician_status", "SHOP_CHANGE_PENDING")
        recompute.recompute_technician(technician)
        if source:
            recompute.recompute_shop(source)
        recompute.recompute_shop(target)
    elif action == "CONFIRM_SHOP":
        if status != "SHOP_CHANGE_PENDING":
            fail("ERR_INVALID_STATE")
        store.set_field(technician, "technician_status", "ACTIVE")
        store.technician_prior_shop.pop(technician["id"], None)
        recompute.recompute_technician(technician)
    elif action == "CANCEL_SHOP":
        if status != "SHOP_CHANGE_PENDING":
            fail("ERR_INVALID_STATE")
        prior_id = store.technician_prior_shop.get(technician["id"])
        if not technician.get("current_shop_location_id") or not prior_id:
            fail("ERR_INVALID_STATE", "The technician has no prior shop on file.")
        abandoned = store.shops.get(technician.get("current_shop_location_id"))
        technician["current_shop_location_id"] = prior_id
        store.set_field(technician, "technician_status", "ACTIVE")
        store.technician_prior_shop.pop(technician["id"], None)
        recompute.recompute_technician(technician)
        if abandoned:
            recompute.recompute_shop(abandoned)
        prior = store.shops.get(prior_id)
        if prior:
            recompute.recompute_shop(prior)
    else:
        if status not in ("ACTIVE", "SHOP_CHANGE_PENDING"):
            fail("ERR_INVALID_STATE")
        for order in store.sales_orders.values():
            if (order.get("technician_id") == technician["id"]
                    and order.get("order_status") == "CONFIRMED"):
                fail("ERR_TRADE_EXIT_OPEN_ORDER")
        source = store.shops.get(technician.get("current_shop_location_id"))
        store.set_field(technician, "last_known_shop_name",
                        source.get("shop_name") if source else technician.get("last_known_shop_name"))
        technician["current_shop_location_id"] = None
        technician["home_route_id"] = None
        store.set_field(technician, "technician_status", "TRADE_EXITED")
        store.technician_prior_shop.pop(technician["id"], None)
        for account in store.accounts.values():
            if (account.get("technician_id") == technician["id"]
                    and account.get("account_status") == "ACTIVE"):
                store.set_field(account, "account_status", "SUSPENDED")
                account["account_status_changed_at"] = clock.fmt_week(clock.now())
                store.stamp(account)
                recompute.recompute_account(account)
                recompute.recompute_account_dependants(account)
        recompute.recompute_technician(technician)
        if source:
            recompute.recompute_shop(source)

    store.stamp(technician)
    return envelope.ok(technician)
