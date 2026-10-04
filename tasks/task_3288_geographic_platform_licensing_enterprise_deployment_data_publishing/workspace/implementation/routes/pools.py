"""Credit pools and projection (§3.2)."""
from flask import Blueprint, request

import calc
import store
from auth import require_role
from envelope import paginate, success
from errors import err
from helpers import get_body, require_fields

bp = Blueprint("pools", __name__)


def pool_view(pool):
    p = dict(pool)
    p["posture"] = calc.compute_posture(pool)
    return p


@bp.post("/geo-orgs/credit-pools")
def create_pool():
    require_role("BillingAdmin")
    body = get_body()
    require_fields(body, [
        ("organization_id", "str", True),
        ("capacity_credits", "int", True),
        ("low_credit_threshold_credits", "int", False),
    ])
    org = store.orgs.get(body["organization_id"])
    if org is None:
        raise err("ERR_ORG_NOT_FOUND")
    if store.pool_for_org(org["id"]) is not None:
        raise err("ERR_DUPLICATE_VALUE", "organization already has a CreditPool")
    rec = store.new_record()
    rec.update({
        "organization_id": org["id"],
        "capacity_credits": body["capacity_credits"],
        "reserved_credits": 0,
        "consumed_credits": 0,
        "low_credit_threshold_credits": body.get("low_credit_threshold_credits", 500),
        "posture": "OK",
    })
    store.credit_pools[rec["id"]] = rec
    calc.refresh_pool(rec)
    store.touch(org)
    return success(pool_view(rec), status=201)


@bp.get("/geo-orgs/credit-pools/<pool_id>")
def get_pool(pool_id):
    require_role("PlatformAdmin", "LicenseAdmin", "BillingAdmin")
    pool = store.credit_pools.get(pool_id)
    if pool is None:
        raise err("ERR_ORG_NOT_FOUND", "CreditPool not found")
    return success(pool_view(pool))


@bp.get("/geo-orgs/credit-pools")
def list_pools():
    require_role("PlatformAdmin", "LicenseAdmin", "BillingAdmin")
    items = sorted(store.credit_pools.values(), key=lambda r: r["created_at"])
    org_id = request.args.get("organization_id")
    if org_id is not None:
        items = [p for p in items if p["organization_id"] == org_id]
    page, pg = paginate(items, request.args)
    return success([pool_view(p) for p in page], pagination=pg)


@bp.get("/geo-orgs/<org_id>/credit-pool-projection")
def projection(org_id):
    require_role("BillingAdmin", "PlatformAdmin")
    org = store.orgs.get(org_id)
    if org is None:
        raise err("ERR_ORG_NOT_FOUND")
    raw_periods = request.args.get("periods")
    try:
        periods = int(raw_periods)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "periods must be an integer")
    mode = request.args.get("mode", "forward")
    if mode not in ("forward", "chronological"):
        raise err("ERR_INVALID_REQUEST", "mode must be forward or chronological")
    projected = calc.credit_burn_projection(org_id, periods, mode)
    return success({"projected_credits": projected, "mode": mode})
