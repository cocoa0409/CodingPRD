"""Fleet customer endpoints and per-customer collection lists."""

from flask import Blueprint

import store
from store import DB
from util import (auth, require_role, body, req_field, as_str, as_enum, find,
                  ok, ok_list)

bp = Blueprint("customers", __name__)


@bp.post("/evfleet/fleet-customers")
def create_customer():
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    b = body()
    company_name = as_str(req_field(b, "company_name"), "company_name")
    contact_email = as_str(req_field(b, "contact_email"), "contact_email")
    account_tier = as_enum(req_field(b, "account_tier"), {"STANDARD", "PRIORITY"},
                           "account_tier")
    e = {
        "company_name": company_name,
        "contact_email": contact_email,
        "account_tier": account_tier,
    }
    store.stamp_new(e)
    DB.customers[e["id"]] = e
    return ok(store.public(e), 201)


@bp.get("/evfleet/fleet-customers/<cid>")
def get_customer(cid):
    _, role = auth()
    require_role(role, {"PlatformAdmin", "FleetManager"})
    e = find(DB.customers, cid, "fleet customer")
    return ok(store.public(e), 200)


@bp.get("/evfleet/fleet-customers/<cid>/depots")
def list_customer_depots(cid):
    _, role = auth()
    require_role(role, {"PlatformAdmin", "FleetManager", "ChargingCoordinator"})
    find(DB.customers, cid, "fleet customer")
    items = [d for d in DB.depots.values() if d["fleet_customer_id"] == cid]
    return ok_list(items)


@bp.get("/evfleet/fleet-customers/<cid>/uptime-contracts")
def list_customer_contracts(cid):
    _, role = auth()
    require_role(role, {"PlatformAdmin", "FleetManager"})
    find(DB.customers, cid, "fleet customer")
    items = [c for c in DB.contracts.values() if c["fleet_customer_id"] == cid]
    return ok_list(items)
