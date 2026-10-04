"""MarketShift endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import DB, CLOCK
from errors import (
    not_found, invalid_input, invalid_state, region_archived, shift_in_past,
)
from middleware import require_roles
from response import success
from services.calculations import parse_iso8601
from services.entity import stamp_new, touch


bp = Blueprint("market_shifts", __name__)

SEGMENTS = ("SEDAN", "SUV", "TRUCK", "VAN", "COUPE")


def _shift_view(s):
    return {
        "id": s["id"],
        "region_id": s["region_id"],
        "segment": s["segment"],
        "effective_at": s["effective_at"],
        "pct_adjustment": s["pct_adjustment"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/market-shifts", methods=["POST"])
def create_market_shift():
    require_roles("ValuationAdmin")
    body = request.get_json(silent=True) or {}
    region_id = body.get("region_id")
    segment = body.get("segment")
    effective_at = body.get("effective_at")
    pct_adjustment = body.get("pct_adjustment")

    # Priority 3: FK existence
    if region_id is not None:
        region = DB.regions.get(region_id) if isinstance(region_id, str) else None
        if region is None:
            raise not_found("region not found")
        # Priority 13: region must be ACTIVE
        if region["status"] != "ACTIVE":
            raise region_archived("region is archived")

    # Priority 14: input shape
    if segment is not None and segment not in SEGMENTS:
        raise invalid_input("segment invalid")
    if not isinstance(effective_at, str):
        raise invalid_input("effective_at is required")
    try:
        eff_dt = parse_iso8601(effective_at)
    except Exception:
        raise invalid_input("effective_at must be ISO 8601")
    if not isinstance(pct_adjustment, (int, float)) or isinstance(pct_adjustment, bool):
        raise invalid_input("pct_adjustment must be numeric")
    if pct_adjustment < -0.50 or pct_adjustment > 0.50:
        raise invalid_input("pct_adjustment out of range [-0.50, 0.50]")

    s = stamp_new({
        "region_id": region_id,
        "segment": segment,
        "effective_at": effective_at,
        "effective_at_dt": eff_dt,
        "pct_adjustment": pct_adjustment,
        "status": "DRAFT",
    })
    DB.market_shifts[s["id"]] = s
    return success(_shift_view(s), 201)


@bp.route("/market-shifts", methods=["GET"])
def list_market_shifts():
    require_roles("ValuationAdmin", "DataOps")
    items = list(DB.market_shifts.values())
    rid = request.args.get("region_id")
    seg = request.args.get("segment")
    status_filter = request.args.get("status")
    if rid:
        items = [s for s in items if s["region_id"] == rid]
    if seg:
        items = [s for s in items if s["segment"] == seg]
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
    return success([_shift_view(s) for s in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


def _same_bucket(a, b):
    """Scope-bucket equality per PRD §3.5."""
    if a["region_id"] is None and a["segment"] is None:
        return b["region_id"] is None and b["segment"] is None
    if a["region_id"] is not None and a["segment"] is None:
        return b["region_id"] == a["region_id"] and b["segment"] is None
    if a["region_id"] is None and a["segment"] is not None:
        return b["region_id"] is None and b["segment"] == a["segment"]
    return b["region_id"] == a["region_id"] and b["segment"] == a["segment"]


@bp.route("/market-shifts/<shift_id>/activate", methods=["POST"])
def activate_market_shift(shift_id):
    require_roles("ValuationAdmin")
    s = DB.market_shifts.get(shift_id)
    if s is None:
        raise not_found("market shift not found")
    if s["status"] != "DRAFT":
        raise invalid_state("shift not in DRAFT")

    # effective_at must not be in the past relative to server clock
    if s["effective_at_dt"] < CLOCK.now():
        raise shift_in_past("shift effective_at in past")

    # Bucket non-overlap among ACTIVE shifts
    for other in DB.market_shifts.values():
        if other["id"] == s["id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if _same_bucket(s, other):
            raise invalid_state("another ACTIVE shift occupies the same scope bucket")

    s["status"] = "ACTIVE"
    touch(s)
    return success(_shift_view(s), 200)


@bp.route("/market-shifts/<shift_id>/rescind", methods=["POST"])
def rescind_market_shift(shift_id):
    require_roles("ValuationAdmin")
    s = DB.market_shifts.get(shift_id)
    if s is None:
        raise not_found("market shift not found")
    if s["status"] != "ACTIVE":
        raise invalid_state("shift not in ACTIVE")
    s["status"] = "RESCINDED"
    touch(s)
    return success(_shift_view(s), 200)
