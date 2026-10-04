"""Data product tiers + recipient tier assignments."""

from flask import Blueprint, request

import db
from middleware import require_role, parse_limit_offset
from response import success_object, success_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_DUPLICATE_ACTIVE,
    ERR_PARENT_NOT_OPERABLE,
)
from services import core
from services.serializers import tier_out, tier_assignment_out

bp = Blueprint("tiers", __name__)

TIER_READ_ROLES = ("PlatformAdmin", "ComplianceReviewer", "Recipient")


def _get_tier(tier_id):
    t = db.tiers.get(tier_id)
    if t is None:
        raise err(ERR_NOT_FOUND, "DataProductTier not found")
    return t


@bp.route("/tiers", methods=["POST"])
def create_tier():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    tier_name = body.get("tier_name")
    scopes_included = body.get("scopes_included")
    rate_class = body.get("rate_class")
    active = body.get("active", True)

    if not isinstance(tier_name, str) or not tier_name.strip():
        raise err(ERR_INVALID_REQUEST, "tier_name must be a non-empty string")
    if not isinstance(scopes_included, list) or not scopes_included:
        raise err(ERR_INVALID_REQUEST, "scopes_included must be a non-empty array")
    for s in scopes_included:
        if s not in core.DATA_SCOPES:
            raise err(ERR_INVALID_REQUEST, f"scopes_included contains invalid scope {s}")
    if rate_class not in core.RATE_CLASSES:
        raise err(ERR_INVALID_REQUEST, "rate_class must be LOW, MEDIUM, or HIGH")
    if not isinstance(active, bool):
        raise err(ERR_INVALID_REQUEST, "active must be a boolean")

    for other in db.tiers.values():
        if other["tier_name"] == tier_name:
            raise err(ERR_DUPLICATE_ACTIVE, "tier_name must be unique")

    t = {
        "tier_name": tier_name,
        "scopes_included": list(scopes_included),
        "rate_class": rate_class,
        "active": active,
    }
    core.stamp_new(t)
    db.tiers[t["id"]] = t
    return success_object(tier_out(t), 201)


@bp.route("/tiers", methods=["GET"])
def list_tiers():
    require_role(*TIER_READ_ROLES)
    limit, offset = parse_limit_offset(request.args)
    active_filter = request.args.get("active")
    items = list(db.tiers.values())
    if active_filter is not None:
        want = active_filter.lower() == "true"
        items = [t for t in items if bool(t.get("active")) == want]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([tier_out(t) for t in page], limit, offset, total)


@bp.route("/tiers/<tierId>", methods=["GET"])
def get_tier(tierId):
    require_role(*TIER_READ_ROLES)
    t = _get_tier(tierId)
    return success_object(tier_out(t))


@bp.route("/tiers/<tierId>/tier_assignments", methods=["GET"])
def list_tier_assignments_for_tier(tierId):
    require_role(*TIER_READ_ROLES)
    t = _get_tier(tierId)
    limit, offset = parse_limit_offset(request.args)
    status_filter = request.args.get("status")
    items = [ta for ta in db.tier_assignments.values() if ta["tier_id"] == t["id"]]
    if status_filter:
        items = [ta for ta in items if ta["status"] == status_filter]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([tier_assignment_out(ta) for ta in page], limit, offset, total)


@bp.route("/recipients/<recipientId>/tier_assignments", methods=["POST"])
def create_tier_assignment(recipientId):
    require_role("PlatformAdmin")
    r = db.recipients.get(recipientId)
    if r is None:
        raise err(ERR_NOT_FOUND, "Recipient not found")
    body = request.get_json(silent=True) or {}
    tier_id = body.get("tier_id")
    if not isinstance(tier_id, str) or not tier_id:
        raise err(ERR_INVALID_REQUEST, "tier_id is required")
    t = db.tiers.get(tier_id)
    if t is None:
        raise err(ERR_NOT_FOUND, "DataProductTier not found")

    # parent operability (priority 8): recipient must be APPROVED
    if r["status"] != "APPROVED":
        raise err(ERR_PARENT_NOT_OPERABLE, "Recipient must be APPROVED for tier enrollment")
    # tier must be active at enrollment (field-level/constraint)
    if not t.get("active"):
        raise err(ERR_INVALID_REQUEST, "tier is not active")

    # end prior ACTIVE assignment
    for ta in db.tier_assignments.values():
        if ta["recipient_id"] == r["id"] and ta["status"] == "ACTIVE":
            ta["status"] = "ENDED"
            core.touch(ta)

    ta = {
        "recipient_id": r["id"],
        "tier_id": t["id"],
        "status": "ACTIVE",
    }
    core.stamp_new(ta)
    db.tier_assignments[ta["id"]] = ta
    return success_object(tier_assignment_out(ta), 201)


@bp.route("/recipients/<recipientId>/tier_assignments", methods=["GET"])
def list_tier_assignments_for_recipient(recipientId):
    require_role(*TIER_READ_ROLES)
    r = db.recipients.get(recipientId)
    if r is None:
        raise err(ERR_NOT_FOUND, "Recipient not found")
    limit, offset = parse_limit_offset(request.args)
    status_filter = request.args.get("status")
    items = [ta for ta in db.tier_assignments.values() if ta["recipient_id"] == r["id"]]
    if status_filter:
        items = [ta for ta in items if ta["status"] == status_filter]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([tier_assignment_out(ta) for ta in page], limit, offset, total)


def active_assignment_for_recipient(recipient_id):
    for ta in db.tier_assignments.values():
        if ta["recipient_id"] == recipient_id and ta["status"] == "ACTIVE":
            return ta
    return None
