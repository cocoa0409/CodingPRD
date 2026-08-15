"""License endpoints: read, list, activate, revoke."""

from flask import Blueprint, request
from db import (
    licenses, images, story_requests, releases as releases_store,
    usage_runs, new_id, now_iso, parse_iso, logical_now,
)
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_LICENSE_NOT_FOUND,
    ERR_INVALID_STATE, ERR_EXCLUSIVE_LICENSE_CONFLICT,
    ERR_RELEASE_REQUIRED, ERR_BUDGET_EXCEEDED,
)
from response import success_object, success_list
from middleware import get_auth, require_role
from serializers import serialize_license, serialize_usage_run, _license_effective_status, _release_effective_status

bp = Blueprint("licenses", __name__)


@bp.route("/licenses", methods=["GET"])
def list_licenses():
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager", "Archivist", "FinanceAdmin"})

    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    image_id = request.args.get("image_id")
    story_request_id = request.args.get("story_request_id")
    status_filter = request.args.get("status")

    items = list(licenses.values())
    if image_id:
        items = [l for l in items if l["image_id"] == image_id]
    if story_request_id:
        items = [l for l in items if l.get("story_request_id") == story_request_id]
    if status_filter:
        items = [l for l in items if _license_effective_status(l) == status_filter]

    items.sort(key=lambda l: l["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_license(l) for l in page], limit, offset, total)


@bp.route("/licenses/<lid>", methods=["GET"])
def get_license(lid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager", "Archivist", "FinanceAdmin"})

    lic = licenses.get(lid)
    if lic is None:
        raise ApiError(ERR_LICENSE_NOT_FOUND, f"License {lid} not found", 404)
    return success_object(serialize_license(lic))


@bp.route("/licenses/<lid>/usage-runs", methods=["GET"])
def list_license_usage_runs(lid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager", "Archivist", "FinanceAdmin"})

    lic = licenses.get(lid)
    if lic is None:
        raise ApiError(ERR_LICENSE_NOT_FOUND, f"License {lid} not found", 404)

    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    items = [u for u in usage_runs.values() if u["license_id"] == lid]
    items.sort(key=lambda u: u["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_usage_run(u) for u in page], limit, offset, total)


@bp.route("/licenses/<lid>/activate", methods=["POST"])
def activate_license(lid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    lic = licenses.get(lid)
    if lic is None:
        raise ApiError(ERR_LICENSE_NOT_FOUND, f"License {lid} not found", 404)

    if lic["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, f"Cannot activate license in status {_license_effective_status(lic)}", 409)

    img = images.get(lic["image_id"])
    if img is None:
        raise ApiError(ERR_LICENSE_NOT_FOUND, "Associated image not found", 404)

    # Priority 8: release gate
    if img.get("has_identifiable_people"):
        has_model = any(
            r["image_id"] == lic["image_id"] and r["subject_type"] == "MODEL" and _release_effective_status(r) == "ACTIVE"
            for r in releases_store.values()
        )
        if not has_model:
            raise ApiError(ERR_RELEASE_REQUIRED, "Image requires an ACTIVE MODEL release", 422)
    if img.get("has_private_property"):
        has_prop = any(
            r["image_id"] == lic["image_id"] and r["subject_type"] == "PROPERTY" and _release_effective_status(r) == "ACTIVE"
            for r in releases_store.values()
        )
        if not has_prop:
            raise ApiError(ERR_RELEASE_REQUIRED, "Image requires an ACTIVE PROPERTY release", 422)

    # Priority 10: exclusivity gate
    new_vf = parse_iso(lic["valid_from"])
    new_vt = parse_iso(lic["valid_to"])

    for other in licenses.values():
        if other["id"] == lid or other["image_id"] != lic["image_id"]:
            continue
        other_eff = _license_effective_status(other)
        if other_eff != "ACTIVE":
            continue

        other_vf = parse_iso(other["valid_from"])
        other_vt = parse_iso(other["valid_to"])
        if other_vf is None or other_vt is None or new_vf is None or new_vt is None:
            continue

        # Half-open overlap: [new_vf, new_vt) intersects [other_vf, other_vt)
        overlaps = new_vf < other_vt and other_vf < new_vt

        if overlaps:
            # If the other is exclusive, conflict
            if other.get("exclusive", False):
                raise ApiError(ERR_EXCLUSIVE_LICENSE_CONFLICT,
                               "Overlaps an ACTIVE exclusive license", 409)
            # If this license is exclusive, any overlap is conflict
            if lic.get("exclusive", False):
                raise ApiError(ERR_EXCLUSIVE_LICENSE_CONFLICT,
                               "Exclusive license overlaps an ACTIVE license", 409)

    # Priority 24: budget gate
    if lic.get("story_request_id"):
        sr = story_requests.get(lic["story_request_id"])
        if sr:
            if sr["committed_cents"] + lic["fee_cents"] > sr["budget_cents"]:
                raise ApiError(ERR_BUDGET_EXCEEDED,
                               f"Activation would exceed story budget ({sr['committed_cents']} + {lic['fee_cents']} > {sr['budget_cents']})", 422)

    # Activate
    now = now_iso()
    lic["status"] = "ACTIVE"
    lic["updated_at"] = now
    lic["version"] += 1

    # Add to story committed_cents
    if lic.get("story_request_id"):
        sr = story_requests.get(lic["story_request_id"])
        if sr:
            sr["committed_cents"] += lic["fee_cents"]
            sr["updated_at"] = now
            sr["version"] += 1

    return success_object(serialize_license(lic))


@bp.route("/licenses/<lid>/revoke", methods=["POST"])
def revoke_license(lid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    lic = licenses.get(lid)
    if lic is None:
        raise ApiError(ERR_LICENSE_NOT_FOUND, f"License {lid} not found", 404)

    eff_status = _license_effective_status(lic)
    if eff_status not in ("DRAFT", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot revoke license in status {eff_status}", 409)

    now = now_iso()
    old_status = lic["status"]  # stored status, not lazy-derived
    lic["status"] = "REVOKED"
    lic["updated_at"] = now
    lic["version"] += 1

    # Budget release if was ACTIVE
    if old_status == "ACTIVE" and lic.get("story_request_id"):
        sr = story_requests.get(lic["story_request_id"])
        if sr:
            sr["committed_cents"] -= lic["fee_cents"]
            sr["updated_at"] = now
            sr["version"] += 1

    return success_object(serialize_license(lic))
