"""Routes: partner orgs and partner delegations."""
from flask import Blueprint, request

import store
from errors import ApiError
from helpers import (Actor, body, req_enum, req_str, require_row)
from respond import paginate, success
from serializers import serialize
from services import bump, make_row, now

bp = Blueprint("partners", __name__)


@bp.post("/api/partner-orgs")
def create_partner_org():
    actor = Actor()
    actor.require_roles("PlatformAdmin")
    b = body()
    partner_ref = req_str(b, "partner_ref")
    display_name = req_str(b, "display_name")
    for p in store.DB["partner_orgs"].values():
        if p["partner_ref"] == partner_ref:
            raise ApiError("ERR_DUPLICATE", "partner_ref must be unique")
    row = make_row()
    row.update({"partner_ref": partner_ref, "display_name": display_name, "status": "ACTIVE"})
    store.DB["partner_orgs"][row["id"]] = row
    return success(serialize(row, "partner_org"), 201)


@bp.get("/api/partner-orgs/<pid>")
def get_partner_org(pid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "PartnerManager")
    row = require_row("partner_orgs", pid)
    if actor.role == "PartnerManager" and actor.user_id != pid:
        raise ApiError("ERR_FORBIDDEN")
    return success(serialize(row, "partner_org"), 200)


@bp.get("/api/partner-orgs/<pid>/delegations")
def list_partner_delegations(pid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "PartnerManager")
    require_row("partner_orgs", pid)
    if actor.role == "PartnerManager" and actor.user_id != pid:
        raise ApiError("ERR_FORBIDDEN")
    rows = sorted([d for d in store.DB["partner_delegations"].values()
                   if d["partner_org_id"] == pid], key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "partner_delegation") for r in page], 200, meta)


@bp.post("/api/partner-delegations")
def create_delegation():
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin")
    b = body()
    partner_org_id = req_str(b, "partner_org_id")
    smart_account_id = req_str(b, "smart_account_id")
    require_row("partner_orgs", partner_org_id)
    acct = require_row("smart_accounts", smart_account_id)
    if actor.role == "AccountAdmin" and actor.user_id != smart_account_id:
        raise ApiError("ERR_FORBIDDEN")
    scope = req_enum(b, "scope", {"LICENSING", "SERVICE_CONTRACTS", "FULL"})
    row = make_row()
    row.update({
        "partner_org_id": partner_org_id,
        "smart_account_id": smart_account_id,
        "scope": scope,
        "status": "ACTIVE",
        "granted_at": now(),
        "revoked_at": None,
    })
    store.DB["partner_delegations"][row["id"]] = row
    return success(serialize(row, "partner_delegation"), 201)


@bp.get("/api/partner-delegations")
def list_delegations():
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    rows = list(store.DB["partner_delegations"].values())
    if actor.role == "AccountAdmin":
        rows = [d for d in rows if d["smart_account_id"] == actor.user_id]
    elif actor.role == "PartnerManager":
        rows = [d for d in rows if d["partner_org_id"] == actor.user_id and d["status"] == "ACTIVE"]
    f_sa = request.args.get("smart_account_id")
    f_po = request.args.get("partner_org_id")
    if f_sa:
        rows = [d for d in rows if d["smart_account_id"] == f_sa]
    if f_po:
        rows = [d for d in rows if d["partner_org_id"] == f_po]
    rows = sorted(rows, key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "partner_delegation") for r in page], 200, meta)


@bp.get("/api/partner-delegations/<did>")
def get_delegation(did):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "PartnerManager", "AccountAdmin")
    row = require_row("partner_delegations", did)
    if actor.role == "PartnerManager" and actor.user_id != row["partner_org_id"]:
        raise ApiError("ERR_FORBIDDEN")
    if actor.role == "AccountAdmin" and actor.user_id != row["smart_account_id"]:
        raise ApiError("ERR_FORBIDDEN")
    return success(serialize(row, "partner_delegation"), 200)


@bp.post("/api/partner-delegations/<did>/revoke")
def revoke_delegation(did):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin")
    row = require_row("partner_delegations", did)
    if actor.role == "AccountAdmin" and actor.user_id != row["smart_account_id"]:
        raise ApiError("ERR_FORBIDDEN")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    row["status"] = "REVOKED"
    row["revoked_at"] = now()
    bump(row)
    return success(serialize(row, "partner_delegation"), 200)
