"""Assignment endpoints."""

from flask import Blueprint, request
from db import (
    assignments, images, photographers, new_id, now_iso, parse_iso,
)
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_ASSIGNMENT_NOT_FOUND,
    ERR_INVALID_STATE, ERR_FORBIDDEN, ERR_MIN_IMAGES_NOT_MET,
    ERR_IMAGE_LIMIT_EXCEEDED,
)
from response import success_object, success_list
from middleware import get_auth, require_role, check_photographer_ownership
from serializers import serialize_assignment, serialize_image
from services.calculations import compute_kill_fee

bp = Blueprint("assignments", __name__)


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager", "Photographer"})

    # Pagination
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    # Filters
    story_request_id = request.args.get("story_request_id")
    photographer_id = request.args.get("photographer_id")
    status_filter = request.args.get("status")

    items = list(assignments.values())

    # Photographer sees only own assignments
    if role == "Photographer":
        items = [a for a in items if a["photographer_id"] == user_id]

    if story_request_id:
        items = [a for a in items if a["story_request_id"] == story_request_id]
    if photographer_id:
        items = [a for a in items if a["photographer_id"] == photographer_id]
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]

    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_assignment(a) for a in page], limit, offset, total)


@bp.route("/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager", "Photographer"})

    a = assignments.get(aid)
    if a is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND, f"Assignment {aid} not found", 404)

    check_photographer_ownership(user_id, role, a["photographer_id"])
    return success_object(serialize_assignment(a))


@bp.route("/assignments/<aid>/images", methods=["POST"])
def submit_image(aid):
    user_id, role = get_auth()
    require_role(role, {"Photographer"})

    body = request.get_json(force=True, silent=True) or {}

    # Priority 3: request shape
    caption = body.get("caption")
    credit_line = body.get("credit_line")
    if not caption or not isinstance(caption, str):
        raise ApiError(ERR_INVALID_REQUEST, "caption is required", 400)
    if not credit_line or not isinstance(credit_line, str):
        raise ApiError(ERR_INVALID_REQUEST, "credit_line is required", 400)

    keywords = body.get("keywords", [])
    if not isinstance(keywords, list):
        raise ApiError(ERR_INVALID_REQUEST, "keywords must be an array", 400)
    has_people = body.get("has_identifiable_people", False)
    has_property = body.get("has_private_property", False)
    embargo_until = body.get("embargo_until")

    # Priority 4: existence
    a = assignments.get(aid)
    if a is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND, f"Assignment {aid} not found", 404)

    # Priority 2: ownership
    check_photographer_ownership(user_id, role, a["photographer_id"])

    # Priority 5: state — must be COMMISSIONED, IN_PROGRESS, or REVISION_REQUESTED
    if a["status"] not in ("COMMISSIONED", "IN_PROGRESS", "REVISION_REQUESTED"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot submit images to assignment in status {a['status']}", 409)

    # Priority 13: image count ceiling
    existing_images = [i for i in images.values() if i.get("assignment_id") == aid]
    if len(existing_images) + 1 > a["max_image_count"]:
        raise ApiError(ERR_IMAGE_LIMIT_EXCEEDED, "Assignment image limit exceeded", 422)

    now = now_iso()

    # State transition: COMMISSIONED -> IN_PROGRESS or REVISION_REQUESTED -> IN_PROGRESS
    if a["status"] in ("COMMISSIONED", "REVISION_REQUESTED"):
        a["status"] = "IN_PROGRESS"
        a["updated_at"] = now
        a["version"] += 1

    # Create image
    iid = new_id()
    img = {
        "id": iid,
        "photographer_id": a["photographer_id"],
        "assignment_id": aid,
        "source_type": "ASSIGNMENT",
        "agency_name": None,
        "base_license_fee_cents": 0,
        "caption": caption,
        "credit_line": credit_line,
        "keywords": keywords,
        "has_identifiable_people": has_people,
        "has_private_property": has_property,
        "embargo_until": embargo_until,
        "status": "INGESTED",
        "restriction_status": "NONE",
        "times_used": 0,
        "first_published_at": None,
        "rights_reversion_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    images[iid] = img
    return success_object(serialize_image(img), 201)


@bp.route("/assignments/<aid>/images", methods=["GET"])
def list_assignment_images(aid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager", "Photographer"})

    a = assignments.get(aid)
    if a is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND, f"Assignment {aid} not found", 404)

    check_photographer_ownership(user_id, role, a["photographer_id"])

    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    items = [i for i in images.values() if i.get("assignment_id") == aid]
    items.sort(key=lambda i: i["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_image(i) for i in page], limit, offset, total)


@bp.route("/assignments/<aid>/submit", methods=["POST"])
def submit_assignment(aid):
    user_id, role = get_auth()
    require_role(role, {"Photographer"})

    a = assignments.get(aid)
    if a is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND, f"Assignment {aid} not found", 404)

    # Ownership
    check_photographer_ownership(user_id, role, a["photographer_id"])

    # State: must be IN_PROGRESS
    if a["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, f"Cannot submit assignment in status {a['status']}", 409)

    # Min images check: count INGESTED images
    ingested = [i for i in images.values()
                if i.get("assignment_id") == aid and i["status"] == "INGESTED"]
    if len(ingested) < a["min_image_count"]:
        raise ApiError(ERR_MIN_IMAGES_NOT_MET,
                       f"Assignment requires at least {a['min_image_count']} images, has {len(ingested)}", 422)

    a["status"] = "SUBMITTED"
    a["updated_at"] = now_iso()
    a["version"] += 1
    return success_object(serialize_assignment(a))


@bp.route("/assignments/<aid>/accept", methods=["POST"])
def accept_assignment(aid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor"})

    a = assignments.get(aid)
    if a is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND, f"Assignment {aid} not found", 404)

    if a["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot accept assignment in status {a['status']}", 409)

    now = now_iso()

    a["status"] = "ACCEPTED"
    a["accepted_at"] = now
    a["updated_at"] = now
    a["version"] += 1

    # Cascade: INGESTED images -> CLEARED, per-image fee accrual
    photog = photographers.get(a["photographer_id"])
    cleared_count = 0
    for img in images.values():
        if img.get("assignment_id") == aid and img["status"] == "INGESTED":
            img["status"] = "CLEARED"
            img["updated_at"] = now
            img["version"] += 1
            cleared_count += 1

    if photog and cleared_count > 0:
        photog["accrued_earnings_cents"] += photog["per_image_fee_cents"] * cleared_count
        photog["updated_at"] = now
        photog["version"] += 1

    return success_object(serialize_assignment(a))


@bp.route("/assignments/<aid>/request-revision", methods=["POST"])
def request_revision(aid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor"})

    a = assignments.get(aid)
    if a is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND, f"Assignment {aid} not found", 404)

    if a["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot request revision on assignment in status {a['status']}", 409)

    a["status"] = "REVISION_REQUESTED"
    a["revision_count"] += 1
    a["updated_at"] = now_iso()
    a["version"] += 1
    return success_object(serialize_assignment(a))


@bp.route("/assignments/<aid>/cancel", methods=["POST"])
def cancel_assignment(aid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor"})

    a = assignments.get(aid)
    if a is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND, f"Assignment {aid} not found", 404)

    if a["status"] not in ("COMMISSIONED", "IN_PROGRESS", "SUBMITTED", "REVISION_REQUESTED"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot cancel assignment in status {a['status']}", 409)

    old_status = a["status"]
    now = now_iso()

    a["status"] = "CANCELLED"
    a["updated_at"] = now
    a["version"] += 1

    # Kill fee from SUBMITTED or REVISION_REQUESTED
    if old_status in ("SUBMITTED", "REVISION_REQUESTED"):
        photog = photographers.get(a["photographer_id"])
        if photog:
            kf = compute_kill_fee(photog, a)
            a["kill_fee_cents"] = kf
            photog["accrued_earnings_cents"] += kf
            photog["updated_at"] = now
            photog["version"] += 1

    return success_object(serialize_assignment(a))
