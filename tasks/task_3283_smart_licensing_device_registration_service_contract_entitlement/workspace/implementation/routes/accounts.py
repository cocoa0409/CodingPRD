"""Routes: clock, smart accounts, partner orgs, delegations, virtual accounts."""
from flask import Blueprint

import store
from errors import ApiError
from helpers import (Actor, authorize_resource, body, opt_str, parse_iso,
                     req_str, require_row)
from respond import paginate, success
from serializers import serialize
from services import (NON_TERMINAL_RMA, bump, close_account_cascade, make_row,
                      now, sweep_clock)
from store import set_clock

bp = Blueprint("accounts", __name__)


def _parse_iso_any(v):
    return parse_iso(v, "to_iso8601")


@bp.post("/api/_clock/set_current_utc")
def clock_set():
    actor = Actor()
    actor.require_roles("PlatformAdmin")
    b = body()
    dt = _parse_iso_any(b.get("to_iso8601"))
    set_clock(dt)
    sweep_clock()
    return success({}, 200)


# ------------------------------------------------------------- smart accounts

@bp.post("/api/smart-accounts")
def create_smart_account():
    actor = Actor()
    actor.require_roles("PlatformAdmin")
    b = body()
    account_ref = req_str(b, "account_ref")
    display_name = req_str(b, "display_name")
    managing_partner_id = opt_str(b, "managing_partner_id")
    if managing_partner_id is not None:
        require_row("partner_orgs", managing_partner_id)
    for a in store.DB["smart_accounts"].values():
        if a["account_ref"] == account_ref:
            raise ApiError("ERR_DUPLICATE", "account_ref must be unique")
    row = make_row()
    row.update({
        "account_ref": account_ref,
        "display_name": display_name,
        "status": "ACTIVE",
        "managing_partner_id": managing_partner_id,
        "compliance_posture": "COMPLIANT",
    })
    store.DB["smart_accounts"][row["id"]] = row
    return success(serialize(row, "smart_account"), 201)


@bp.get("/api/smart-accounts")
def list_smart_accounts():
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    rows = sorted(store.DB["smart_accounts"].values(), key=lambda r: r["created_at"])
    if actor.role == "AccountAdmin":
        rows = [r for r in rows if r["id"] == actor.user_id]
    page, meta = paginate(rows)
    return success([serialize(r, "smart_account") for r in page], 200, meta)


@bp.get("/api/smart-accounts/<sid>")
def get_smart_account(sid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("smart_accounts", sid)
    authorize_resource(actor, "smart_account", row, write=False)
    return success(serialize(row, "smart_account"), 200)


def _account_action(sid, action):
    actor = Actor()
    actor.require_roles("PlatformAdmin")
    row = require_row("smart_accounts", sid)
    if action == "suspend":
        if row["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        row["status"] = "SUSPENDED"
    elif action == "reactivate":
        if row["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE")
        row["status"] = "ACTIVE"
    elif action == "close":
        if row["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        # Preconditions: no REGISTERED device, no non-terminal RMA, no open transfer.
        for va in store.DB["virtual_accounts"].values():
            if va["smart_account_id"] != sid:
                continue
            for dev in store.DB["devices"].values():
                if dev["virtual_account_id"] == va["id"] and dev["registration_state"] == "REGISTERED":
                    raise ApiError("ERR_INVALID_STATE", "account has REGISTERED devices")
        account_device_ids = {
            d["id"] for d in store.DB["devices"].values()
            if (lambda va: va and va["smart_account_id"] == sid)(
                store.DB["virtual_accounts"].get(d["virtual_account_id"]))
        }
        for c in store.DB["rma_cases"].values():
            if c["device_id"] in account_device_ids and c["status"] in NON_TERMINAL_RMA:
                raise ApiError("ERR_INVALID_STATE", "account has open RMA cases")
        account_pool_ids = {
            p["id"] for p in store.DB["license_pools"].values()
            if (lambda va: va and va["smart_account_id"] == sid)(
                store.DB["virtual_accounts"].get(p["virtual_account_id"]))
        }
        account_va_ids = {va["id"] for va in store.DB["virtual_accounts"].values()
                          if va["smart_account_id"] == sid}
        for t in store.DB["transfer_requests"].values():
            if t["status"] in ("PENDING_APPROVAL", "APPROVED") and (
                    t["source_pool_id"] in account_pool_ids
                    or t["target_virtual_account_id"] in account_va_ids):
                raise ApiError("ERR_INVALID_STATE", "account has open transfer requests")
        close_account_cascade(row)
        row["status"] = "CLOSED"
    bump(row)
    return success(serialize(row, "smart_account"), 200)


@bp.post("/api/smart-accounts/<sid>/suspend")
def suspend_account(sid):
    return _account_action(sid, "suspend")


@bp.post("/api/smart-accounts/<sid>/reactivate")
def reactivate_account(sid):
    return _account_action(sid, "reactivate")


@bp.post("/api/smart-accounts/<sid>/close")
def close_account(sid):
    return _account_action(sid, "close")


@bp.get("/api/smart-accounts/<sid>/virtual-accounts")
def list_account_virtual_accounts(sid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("smart_accounts", sid)
    authorize_resource(actor, "smart_account", row, write=False)
    rows = sorted([v for v in store.DB["virtual_accounts"].values()
                   if v["smart_account_id"] == sid], key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "virtual_account") for r in page], 200, meta)


@bp.get("/api/smart-accounts/<sid>/service-contracts")
def list_account_contracts(sid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("smart_accounts", sid)
    authorize_resource(actor, "smart_account", row, write=False)
    rows = sorted([c for c in store.DB["service_contracts"].values()
                   if c["smart_account_id"] == sid], key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "service_contract") for r in page], 200, meta)
