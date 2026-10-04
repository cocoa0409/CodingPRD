"""ConditionStandard endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request

from db import DB
from errors import not_found, invalid_input, duplicate_key
from middleware import require_roles
from response import success
from services.calculations import TIER_MULTIPLIERS
from services.entity import stamp_new


bp = Blueprint("condition_standards", __name__)

ALL_ROLES = ("ValuationAdmin", "DataOps", "DealerPartner", "Consumer", "Licensee")


def _standard_view(s):
    return {
        "id": s["id"],
        "tier": s["tier"],
        "description": s["description"],
        "multiplier": s["multiplier"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/condition-standards", methods=["POST"])
def create_condition_standard():
    require_roles("ValuationAdmin")
    body = request.get_json(silent=True) or {}
    tier = body.get("tier")
    description = body.get("description")
    multiplier = body.get("multiplier")
    if tier not in TIER_MULTIPLIERS:
        raise invalid_input("tier invalid")
    if not isinstance(description, str) or not description:
        raise invalid_input("description is required")
    if not isinstance(multiplier, (int, float)) or isinstance(multiplier, bool):
        raise invalid_input("multiplier must be numeric")
    # Multiplier must equal the fixed catalog value
    if Decimal(str(multiplier)) != TIER_MULTIPLIERS[tier]:
        raise invalid_input("multiplier deviates from fixed catalog value")
    if tier in DB._condition_tiers:
        raise duplicate_key("tier already defined")
    s = stamp_new({
        "tier": tier,
        "description": description,
        "multiplier": multiplier,
    })
    DB.condition_standards[s["id"]] = s
    DB._condition_tiers[tier] = s["id"]
    return success(_standard_view(s), 201)


@bp.route("/condition-standards", methods=["GET"])
def list_condition_standards():
    require_roles(*ALL_ROLES)
    items = list(DB.condition_standards.values())
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
    return success([_standard_view(s) for s in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)
