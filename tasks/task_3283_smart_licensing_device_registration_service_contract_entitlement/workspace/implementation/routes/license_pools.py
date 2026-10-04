"""Routes: license pools (create, get, purchase-adjustment, tier-upgrade, lists)."""
from flask import Blueprint, request

import store
from errors import ApiError
from helpers import (Actor, authorize_resource, body, opt_dt, opt_str, req_dt,
                     req_enum, req_int, req_str, require_row)
from respond import paginate, success
from serializers import serialize
from services import bump, make_row, now, recompute_pool

bp = Blueprint("license_pools", __name__)

TIER_ORDER = {"ESSENTIALS": 1, "ADVANTAGE": 2, "PREMIER": 3}


def _owning_account_active(pool_or_va):
    acct = store.DB["smart_accounts"].get(pool_or_va["smart_account_id"] if "smart_account_id" in pool_or_va
                                          else store.DB["virtual_accounts"][pool_or_va["virtual_account_id"]]["smart_account_id"])
    if acct is None or acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")


@bp.post("/api/license-pools")
def create_pool():
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    b = body()
    virtual_account_id = req_str(b, "virtual_account_id")
    va = require_row("virtual_accounts", virtual_account_id)
    sku = req_str(b, "sku")
    license_model = req_enum(b, "license_model", {"PERPETUAL", "SUBSCRIPTION"})
    feature_tier = opt_str(b, "feature_tier") or "ESSENTIALS"
    if feature_tier not in TIER_ORDER:
        raise ApiError("ERR_INVALID_REQUEST", "feature_tier must be one of ESSENTIALS, ADVANTAGE, PREMIER")
    purchased_quantity = req_int(b, "purchased_quantity")
    if purchased_quantity < 0:
        raise ApiError("ERR_INVALID_QUANTITY", "purchased_quantity must be >= 0")
    subscription_expires_at = opt_dt(b, "subscription_expires_at")
    authorize_resource(actor, "virtual_account", va, scope_needed="LICENSING", write=True)
    _owning_account_active(va)
    for p in store.DB["license_pools"].values():
        if p["virtual_account_id"] == virtual_account_id and p["sku"] == sku:
            raise ApiError("ERR_DUPLICATE", "sku must be unique within the virtual account")
    row = make_row()
    row.update({
        "virtual_account_id": virtual_account_id,
        "sku": sku,
        "license_model": license_model,
        "feature_tier": feature_tier,
        "purchased_quantity": purchased_quantity,
        "consumed_quantity": 0,
        "compliance_state": "COMPLIANT",
        "grace_deadline": None,
        "overage_detected_at": None,
        "subscription_expires_at": subscription_expires_at,
    })
    store.DB["license_pools"][row["id"]] = row
    recompute_pool(row)
    return success(serialize(row, "license_pool"), 201)


@bp.get("/api/license-pools/<pid>")
def get_pool(pid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("license_pools", pid)
    recompute_pool(row)  # lazy grace expiry on read
    authorize_resource(actor, "license_pool", row, write=False)
    return success(serialize(row, "license_pool"), 200)


@bp.post("/api/license-pools/<pid>/purchase-adjustment")
def purchase_adjustment(pid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("license_pools", pid)
    b = body()
    delta = req_int(b, "delta")
    expected = b.get("expected_pool_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_pool_version is required and must be an integer")
    authorize_resource(actor, "license_pool", row, scope_needed="LICENSING", write=True)
    _owning_account_active(row)
    if expected != row["version"]:
        raise ApiError("ERR_STALE_VERSION")
    new_qty = row["purchased_quantity"] + delta
    if new_qty < 0:
        raise ApiError("ERR_INVALID_QUANTITY", "purchased_quantity cannot go below 0")
    row["purchased_quantity"] = new_qty
    bump(row)
    recompute_pool(row)
    return success(serialize(row, "license_pool"), 200)


@bp.post("/api/license-pools/<pid>/tier-upgrade")
def tier_upgrade(pid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("license_pools", pid)
    b = body()
    new_tier = req_enum(b, "new_tier", set(TIER_ORDER))
    authorize_resource(actor, "license_pool", row, scope_needed="LICENSING", write=True)
    _owning_account_active(row)
    if TIER_ORDER[new_tier] <= TIER_ORDER[row["feature_tier"]]:
        raise ApiError("ERR_TIER_DOWNGRADE_FORBIDDEN")
    if row["license_model"] == "SUBSCRIPTION" and row["subscription_expires_at"] is not None:
        total_seconds = (row["subscription_expires_at"] - row["created_at"]).total_seconds()
        days_total = int(total_seconds // 86400)
        left_seconds = (row["subscription_expires_at"] - now()).total_seconds()
        days_left = max(0, int(left_seconds // 86400))
        credit = 0
        if days_total > 0:
            # exact rational, round DOWN last
            credit = (row["purchased_quantity"] * days_left) // days_total
        row["purchased_quantity"] += credit
    row["feature_tier"] = new_tier
    bump(row)
    recompute_pool(row)
    return success(serialize(row, "license_pool"), 200)


@bp.get("/api/license-pools/<pid>/compliance-events")
def list_compliance_events(pid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("license_pools", pid)
    authorize_resource(actor, "license_pool", row, write=False)
    rows = sorted([e for e in store.DB["compliance_events"].values()
                   if e["license_pool_id"] == pid], key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "compliance_event") for r in page], 200, meta)


@bp.get("/api/license-pools/<pid>/assignments")
def list_pool_assignments(pid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("license_pools", pid)
    authorize_resource(actor, "license_pool", row, write=False)
    rows = [a for a in store.DB["assignments"].values() if a["license_pool_id"] == pid]
    status_f = request.args.get("status")
    if status_f:
        rows = [a for a in rows if a["status"] == status_f]
    rows = sorted(rows, key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "assignment") for r in page], 200, meta)
