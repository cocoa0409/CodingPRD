"""Region endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import DB
from errors import (
    not_found, invalid_input, region_archived, invalid_state, ApiError,
)
from middleware import require_roles
from response import success
from services.entity import stamp_new, touch


bp = Blueprint("regions", __name__)

ALL_ROLES = ("ValuationAdmin", "DataOps", "DealerPartner", "Consumer", "Licensee")


def _region_view(r):
    return {
        "id": r["id"],
        "region_code": r["region_code"],
        "name": r["name"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def _paginate(items):
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise invalid_input("limit out of range [1,100]")
    if offset < 0:
        raise invalid_input("offset must be >= 0")
    items_sorted = sorted(items, key=lambda r: r["created_at"])
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return success([_region_view(r) for r in page], 200,
                   response_type="array",
                   limit=limit, offset=offset,
                   total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/regions", methods=["POST"])
def create_region():
    require_roles("ValuationAdmin")
    body = request.get_json(silent=True) or {}
    code = body.get("region_code")
    name = body.get("name")
    if not isinstance(code, str) or not code or not isinstance(name, str) or not name:
        raise invalid_input("region_code and name are required strings")
    if code in DB._region_codes:
        # Region codes unique; replay with different payload would be duplicate-key.
        # No idempotent replay on regions per PRD (only sources/configs/series/batches).
        raise invalid_input("region_code already exists")
    r = stamp_new({
        "region_code": code,
        "name": name,
        "status": "ACTIVE",
    })
    DB.regions[r["id"]] = r
    DB._region_codes[code] = r["id"]
    return success(_region_view(r), 201)


@bp.route("/regions", methods=["GET"])
def list_regions():
    require_roles(*ALL_ROLES)
    items = list(DB.regions.values())
    status_filter = request.args.get("status")
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    return _paginate(items)


@bp.route("/regions/<region_id>", methods=["GET"])
def get_region(region_id):
    require_roles(*ALL_ROLES)
    r = DB.regions.get(region_id)
    if r is None:
        raise not_found("region not found")
    return success(_region_view(r), 200)


@bp.route("/regions/<region_id>", methods=["PATCH"])
def patch_region(region_id):
    require_roles("ValuationAdmin")
    r = DB.regions.get(region_id)
    if r is None:
        raise not_found("region not found")
    body = request.get_json(silent=True) or {}
    new_status = body.get("status")
    if new_status is None:
        raise invalid_input("status required")
    if new_status not in ("ACTIVE", "ARCHIVED"):
        raise invalid_input("status must be ACTIVE or ARCHIVED")
    if r["status"] == "ARCHIVED":
        if new_status == "ARCHIVED":
            # idempotent no-op
            return success(_region_view(r), 200)
        raise invalid_state("cannot transition from ARCHIVED")
    # r is ACTIVE
    if new_status == "ARCHIVED":
        # guard: no Source in PROBATION or ACTIVE references the region
        for src in DB.sources.values():
            if src["region_id"] == r["id"] and src["status"] in ("PROBATION", "ACTIVE"):
                raise invalid_state("active sources reference this region")
        r["status"] = "ARCHIVED"
        touch(r)
    return success(_region_view(r), 200)


# Sub-resource: market shifts scoped to one region
@bp.route("/regions/<region_id>/market-shifts", methods=["GET"])
def list_region_market_shifts(region_id):
    require_roles("ValuationAdmin", "DataOps")
    r = DB.regions.get(region_id)
    if r is None:
        raise not_found("region not found")
    items = [s for s in DB.market_shifts.values() if s["region_id"] == region_id]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    from routes.market_shifts import _shift_view
    return success([_shift_view(s) for s in page], 200,
                   response_type="array",
                   limit=limit, offset=offset,
                   total_count=total,
                   has_more=(offset + limit) < total)
