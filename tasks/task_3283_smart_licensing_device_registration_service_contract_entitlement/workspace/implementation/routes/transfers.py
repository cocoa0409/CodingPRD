"""Routes: license transfer requests with approval workflow."""
from flask import Blueprint, request

import store
from errors import ApiError
from helpers import (Actor, authorize_resource, body, req_enum, req_int,
                     req_str, require_row)
from respond import paginate, success
from serializers import serialize
from services import bump, make_row, recompute_pool

bp = Blueprint("transfers", __name__)


def _pool_account(pool):
    va = store.DB["virtual_accounts"].get(pool["virtual_account_id"])
    return store.DB["smart_accounts"].get(va["smart_account_id"]) if va else None


def _transferable(pool):
    return pool["purchased_quantity"] - pool["consumed_quantity"]


@bp.post("/api/license-transfer-requests")
def create_transfer():
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    b = body()
    source_pool_id = req_str(b, "source_pool_id")
    pool = require_row("license_pools", source_pool_id)
    target_virtual_account_id = req_str(b, "target_virtual_account_id")
    target_va = require_row("virtual_accounts", target_virtual_account_id)
    quantity = req_int(b, "quantity")
    reason = req_enum(b, "reason", {"HARDWARE_REFRESH", "ACCOUNT_REORG", "PARTNER_EXIT"})
    if quantity < 1:
        raise ApiError("ERR_INVALID_QUANTITY", "quantity must be >= 1")
    authorize_resource(actor, "license_pool", pool, scope_needed="LICENSING", write=True)
    acct = _pool_account(pool)
    if acct is None or acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    if _transferable(pool) < quantity:
        raise ApiError("ERR_INSUFFICIENT_TRANSFERABLE")
    row = make_row()
    row.update({
        "source_pool_id": source_pool_id,
        "target_virtual_account_id": target_virtual_account_id,
        "quantity": quantity,
        "reason": reason,
        "status": "PENDING_APPROVAL",
        "requested_by_partner_org_id": actor.user_id if actor.role == "PartnerManager" else None,
        "decided_by": None,
    })
    store.DB["transfer_requests"][row["id"]] = row
    return success(serialize(row, "transfer_request"), 201)


@bp.get("/api/license-transfer-requests")
def list_transfers():
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    rows = list(store.DB["transfer_requests"].values())
    if actor.role in ("AccountAdmin", "PartnerManager"):
        rows = [r for r in rows if _visible(actor, r)]
    f_sp = request.args.get("source_pool_id")
    f_tva = request.args.get("target_virtual_account_id")
    f_po = request.args.get("requested_by_partner_org_id")
    f_st = request.args.get("status")
    if f_sp:
        rows = [r for r in rows if r["source_pool_id"] == f_sp]
    if f_tva:
        rows = [r for r in rows if r["target_virtual_account_id"] == f_tva]
    if f_po:
        rows = [r for r in rows if r["requested_by_partner_org_id"] == f_po]
    if f_st:
        rows = [r for r in rows if r["status"] == f_st]
    rows = sorted(rows, key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "transfer_request") for r in page], 200, meta)


def _visible(actor, row):
    from helpers import owning_account_id
    account_id = owning_account_id("transfer_request", row)
    if actor.role == "AccountAdmin":
        return account_id == actor.user_id
    if actor.role == "PartnerManager":
        return any(
            d["partner_org_id"] == actor.user_id
            and d["smart_account_id"] == account_id
            and d["status"] == "ACTIVE"
            for d in store.DB["partner_delegations"].values()
        )
    return False


@bp.get("/api/license-transfer-requests/<tid>")
def get_transfer(tid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("transfer_requests", tid)
    authorize_resource(actor, "transfer_request", row, write=False)
    return success(serialize(row, "transfer_request"), 200)


@bp.post("/api/license-transfer-requests/<tid>/approve")
def approve_transfer(tid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("transfer_requests", tid)
    b = body()
    expected = b.get("expected_transfer_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_transfer_version is required and must be an integer")
    pool = store.DB["license_pools"].get(row["source_pool_id"])
    acct = _pool_account(pool) if pool else None
    # PRD 3.8: partner side can never approve a partner-initiated request.
    if actor.role == "PartnerManager":
        if row["requested_by_partner_org_id"] is not None:
            raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN")
        raise ApiError("ERR_FORBIDDEN")
    if actor.role == "AccountAdmin":
        if acct is None or acct["id"] != actor.user_id:
            raise ApiError("ERR_FORBIDDEN")
    if row["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE")
    if expected != row["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if pool is None or _transferable(pool) < row["quantity"]:
        raise ApiError("ERR_INSUFFICIENT_TRANSFERABLE")
    row["status"] = "APPROVED"
    row["decided_by"] = actor.user_id
    bump(row)
    return success(serialize(row, "transfer_request"), 200)


@bp.post("/api/license-transfer-requests/<tid>/reject")
def reject_transfer(tid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin")
    row = require_row("transfer_requests", tid)
    pool = store.DB["license_pools"].get(row["source_pool_id"])
    acct = _pool_account(pool) if pool else None
    if actor.role == "AccountAdmin":
        if acct is None or acct["id"] != actor.user_id:
            raise ApiError("ERR_FORBIDDEN")
    if row["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE")
    row["status"] = "REJECTED"
    row["decided_by"] = actor.user_id
    bump(row)
    return success(serialize(row, "transfer_request"), 200)


@bp.post("/api/license-transfer-requests/<tid>/cancel")
def cancel_transfer(tid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("transfer_requests", tid)
    pool = store.DB["license_pools"].get(row["source_pool_id"])
    acct = _pool_account(pool) if pool else None
    if actor.role == "PartnerManager":
        if row["requested_by_partner_org_id"] is None or row["requested_by_partner_org_id"] != actor.user_id:
            raise ApiError("ERR_FORBIDDEN")
    elif actor.role == "AccountAdmin":
        if acct is None or acct["id"] != actor.user_id:
            raise ApiError("ERR_FORBIDDEN")
    if row["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE")
    row["status"] = "CANCELLED"
    bump(row)
    return success(serialize(row, "transfer_request"), 200)


@bp.post("/api/license-transfer-requests/<tid>/execute")
def execute_transfer(tid):
    actor = Actor()
    actor.require_roles("PlatformAdmin")
    row = require_row("transfer_requests", tid)
    if row["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")
    source = store.DB["license_pools"].get(row["source_pool_id"])
    target_va = store.DB["virtual_accounts"].get(row["target_virtual_account_id"])
    if source is None or target_va is None:
        raise ApiError("ERR_NOT_FOUND")
    if target_va["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "target virtual account is not ACTIVE")
    target_acct = store.DB["smart_accounts"].get(target_va["smart_account_id"])
    if target_acct is None or target_acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", "target smart account is not ACTIVE")
    if _transferable(source) < row["quantity"]:
        raise ApiError("ERR_INSUFFICIENT_TRANSFERABLE")
    # Pinned order: (1) decrement source, (2) top up or create target pool,
    # (3) recompute source, (4) recompute target, (5) recompute postures.
    source["purchased_quantity"] -= row["quantity"]
    bump(source)
    target = None
    for p in store.DB["license_pools"].values():
        if (p["virtual_account_id"] == target_va["id"]
                and p["sku"] == source["sku"]
                and p["license_model"] == source["license_model"]
                and p["feature_tier"] == source["feature_tier"]):
            target = p
            break
    if target is not None:
        target["purchased_quantity"] += row["quantity"]
        bump(target)
    else:
        target = make_row()
        target.update({
            "virtual_account_id": target_va["id"],
            "sku": source["sku"],
            "license_model": source["license_model"],
            "feature_tier": source["feature_tier"],
            "purchased_quantity": row["quantity"],
            "consumed_quantity": 0,
            "compliance_state": "COMPLIANT",
            "grace_deadline": None,
            "overage_detected_at": None,
            "subscription_expires_at": source["subscription_expires_at"],
        })
        store.DB["license_pools"][target["id"]] = target
    recompute_pool(source)
    recompute_pool(target)
    row["status"] = "EXECUTED"
    bump(row)
    return success(serialize(row, "transfer_request"), 200)
