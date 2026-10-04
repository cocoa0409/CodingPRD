"""Routes: virtual accounts."""
from flask import Blueprint

import store
from errors import ApiError
from helpers import (Actor, authorize_resource, body, req_str, require_row)
from respond import paginate, success
from serializers import serialize
from services import bump, make_row

bp = Blueprint("virtual_accounts", __name__)


@bp.post("/api/virtual-accounts")
def create_virtual_account():
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    b = body()
    smart_account_id = req_str(b, "smart_account_id")
    acct = require_row("smart_accounts", smart_account_id)
    name = req_str(b, "name")
    authorize_resource(actor, "smart_account", acct, scope_needed=None, write=True)
    for v in store.DB["virtual_accounts"].values():
        if v["smart_account_id"] == smart_account_id and v["name"] == name:
            raise ApiError("ERR_DUPLICATE", "name must be unique within the smart account")
    row = make_row()
    row.update({
        "smart_account_id": smart_account_id,
        "name": name,
        "status": "ACTIVE",
    })
    store.DB["virtual_accounts"][row["id"]] = row
    return success(serialize(row, "virtual_account"), 201)


@bp.get("/api/virtual-accounts/<vid>")
def get_virtual_account(vid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("virtual_accounts", vid)
    authorize_resource(actor, "virtual_account", row, write=False)
    return success(serialize(row, "virtual_account"), 200)


@bp.post("/api/virtual-accounts/<vid>/archive")
def archive_virtual_account(vid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("virtual_accounts", vid)
    authorize_resource(actor, "virtual_account", row, scope_needed="LICENSING", write=True)
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    for dev in store.DB["devices"].values():
        if dev["virtual_account_id"] == vid and dev["registration_state"] in ("REGISTERED", "PENDING"):
            raise ApiError("ERR_INVALID_STATE", "virtual account still has PENDING or REGISTERED devices")
    for pool in store.DB["license_pools"].values():
        if pool["virtual_account_id"] == vid and pool["compliance_state"] in ("IN_GRACE", "OUT_OF_COMPLIANCE"):
            raise ApiError("ERR_INVALID_STATE", "virtual account has a pool in overage")
    row["status"] = "ARCHIVED"
    bump(row)
    return success(serialize(row, "virtual_account"), 200)


@bp.get("/api/virtual-accounts/<vid>/license-pools")
def list_va_pools(vid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("virtual_accounts", vid)
    authorize_resource(actor, "virtual_account", row, write=False)
    rows = sorted([p for p in store.DB["license_pools"].values()
                   if p["virtual_account_id"] == vid], key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "license_pool") for r in page], 200, meta)


@bp.get("/api/virtual-accounts/<vid>/devices")
def list_va_devices(vid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("virtual_accounts", vid)
    authorize_resource(actor, "virtual_account", row, write=False)
    rows = sorted([d for d in store.DB["devices"].values()
                   if d["virtual_account_id"] == vid], key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "device") for r in page], 200, meta)
