"""Source endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import DB
from errors import (
    not_found, invalid_input, invalid_state, duplicate_key,
    region_archived,
)
from middleware import require_roles
from response import success
from services.entity import stamp_new, touch


bp = Blueprint("sources", __name__)


def _source_view(s):
    return {
        "id": s["id"],
        "source_type": s["source_type"],
        "region_id": s["region_id"],
        "status": s["status"],
        "consecutive_rejections": s["consecutive_rejections"],
        "external_key": s["external_key"],
        "name": s["name"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/sources", methods=["POST"])
def create_source():
    require_roles("DataOps")
    body = request.get_json(silent=True) or {}
    source_type = body.get("source_type")
    region_id = body.get("region_id")
    name = body.get("name")
    external_key = body.get("external_key")

    # Priority 3: FK resolution
    region = DB.regions.get(region_id) if isinstance(region_id, str) else None
    if region is None:
        raise not_found("region not found")

    # Priority 4: idempotency on external_key (replay returns existing)
    if isinstance(external_key, str) and external_key in DB._source_external_keys:
        existing_id = DB._source_external_keys[external_key]
        existing = DB.sources[existing_id]
        # Same payload -> return existing; different payload -> 409
        if (existing["source_type"] == source_type
                and existing["region_id"] == region_id
                and existing["name"] == name):
            return success(_source_view(existing), 201)
        raise duplicate_key("external_key already used with different payload")

    # Priority 13: region must be ACTIVE
    if region["status"] != "ACTIVE":
        raise region_archived("region is archived")

    # Priority 14: input shape
    if source_type not in ("DEALER", "AUCTION", "LENDER"):
        raise invalid_input("source_type must be DEALER, AUCTION, or LENDER")
    if not isinstance(name, str) or not name:
        raise invalid_input("name is required")
    if not isinstance(external_key, str) or not external_key:
        raise invalid_input("external_key is required")

    s = stamp_new({
        "source_type": source_type,
        "region_id": region_id,
        "status": "PROBATION",
        "consecutive_rejections": 0,
        "external_key": external_key,
        "name": name,
    })
    DB.sources[s["id"]] = s
    DB._source_external_keys[external_key] = s["id"]
    return success(_source_view(s), 201)


@bp.route("/sources", methods=["GET"])
def list_sources():
    require_roles("DataOps", "ValuationAdmin")
    items = list(DB.sources.values())
    region_id = request.args.get("region_id")
    status_filter = request.args.get("status")
    if region_id:
        items = [s for s in items if s["region_id"] == region_id]
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]
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
    return success([_source_view(s) for s in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/sources/<source_id>", methods=["GET"])
def get_source(source_id):
    require_roles("DataOps", "ValuationAdmin", "DealerPartner", "Licensee")
    s = DB.sources.get(source_id)
    if s is None:
        raise not_found("source not found")
    return success(_source_view(s), 200)


@bp.route("/sources/<source_id>/activate", methods=["POST"])
def activate_source(source_id):
    require_roles("DataOps")
    s = DB.sources.get(source_id)
    if s is None:
        raise not_found("source not found")
    if s["status"] != "PROBATION":
        raise invalid_state("source not in PROBATION")
    s["status"] = "ACTIVE"
    touch(s)
    return success(_source_view(s), 200)


@bp.route("/sources/<source_id>/reinstate", methods=["POST"])
def reinstate_source(source_id):
    require_roles("DataOps")
    s = DB.sources.get(source_id)
    if s is None:
        raise not_found("source not found")
    if s["status"] != "SUSPENDED":
        raise invalid_state("source not in SUSPENDED")
    s["status"] = "PROBATION"
    s["consecutive_rejections"] = 0
    touch(s)
    return success(_source_view(s), 200)
