"""Story request endpoints."""

from flask import Blueprint, request
from db import (
    story_requests, photographers, assignments, images, licenses,
    new_id, now_iso, parse_iso, logical_now,
)
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_STORY_REQUEST_NOT_FOUND,
    ERR_PHOTOGRAPHER_NOT_FOUND, ERR_IMAGE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_STORY_ALREADY_DECIDED, ERR_IMAGE_NOT_CLEARED,
    ERR_PHOTOGRAPHER_SUSPENDED, ERR_PHOTOGRAPHER_DOUBLE_BOOKED,
)
from response import success_object, success_list
from middleware import get_auth, require_role
from serializers import serialize_story_request, serialize_assignment
from services.calculations import compute_kill_fee
from datetime import timedelta

bp = Blueprint("story_requests", __name__)


@bp.route("/story-requests", methods=["POST"])
def create_story_request():
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor"})

    body = request.get_json(force=True, silent=True) or {}

    headline = body.get("headline")
    slug = body.get("slug")
    needed_by = body.get("needed_by")
    budget_cents = body.get("budget_cents")

    if not headline or not isinstance(headline, str):
        raise ApiError(ERR_INVALID_REQUEST, "headline is required", 400)
    if not slug or not isinstance(slug, str):
        raise ApiError(ERR_INVALID_REQUEST, "slug is required", 400)
    if not needed_by or not isinstance(needed_by, str):
        raise ApiError(ERR_INVALID_REQUEST, "needed_by is required", 400)
    if parse_iso(needed_by) is None:
        raise ApiError(ERR_INVALID_REQUEST, "needed_by must be a valid ISO 8601 datetime", 400)
    if budget_cents is None or not isinstance(budget_cents, int) or isinstance(budget_cents, bool):
        raise ApiError(ERR_INVALID_REQUEST, "budget_cents is required and must be an integer", 400)

    srid = new_id()
    now = now_iso()
    sr = {
        "id": srid,
        "headline": headline,
        "slug": slug,
        "needed_by": needed_by,
        "budget_cents": budget_cents,
        "committed_cents": 0,
        "decision": None,
        "commissioned_assignment_id": None,
        "sourced_image_id": None,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    story_requests[srid] = sr
    return success_object(serialize_story_request(sr), 201)


@bp.route("/story-requests/<srid>", methods=["GET"])
def get_story_request(srid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager", "Archivist"})

    sr = story_requests.get(srid)
    if sr is None:
        raise ApiError(ERR_STORY_REQUEST_NOT_FOUND, f"Story request {srid} not found", 404)
    return success_object(serialize_story_request(sr))


@bp.route("/story-requests/<srid>/decide", methods=["POST"])
def decide_story_request(srid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor"})

    body = request.get_json(force=True, silent=True) or {}

    # Priority 3: request shape
    decision = body.get("decision")
    if decision not in ("COMMISSION", "WIRE_STOCK"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be COMMISSION or WIRE_STOCK", 400)

    # Priority 4: existence
    sr = story_requests.get(srid)
    if sr is None:
        raise ApiError(ERR_STORY_REQUEST_NOT_FOUND, f"Story request {srid} not found", 404)

    # Priority 7: story must be OPEN
    if sr["status"] != "OPEN":
        raise ApiError(ERR_STORY_ALREADY_DECIDED, "Story request is not OPEN", 409)

    if decision == "COMMISSION":
        _decide_commission(sr, body)
    else:
        _decide_wire_stock(sr, body)

    sr["status"] = "DECIDED"
    sr["decision"] = decision
    sr["updated_at"] = now_iso()
    sr["version"] += 1
    return success_object(serialize_story_request(sr))


def _decide_commission(sr, body):
    """Handle COMMISSION decision branch."""
    photographer_id = body.get("photographer_id")
    brief = body.get("brief")
    shoot_start = body.get("shoot_start")
    shoot_end = body.get("shoot_end")
    min_image_count = body.get("min_image_count", 1)
    max_image_count = body.get("max_image_count", 10)

    # Validate required fields for COMMISSION
    if not photographer_id or not isinstance(photographer_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "photographer_id is required for COMMISSION", 400)
    if not brief or not isinstance(brief, str):
        raise ApiError(ERR_INVALID_REQUEST, "brief is required for COMMISSION", 400)
    if not shoot_start or not isinstance(shoot_start, str):
        raise ApiError(ERR_INVALID_REQUEST, "shoot_start is required for COMMISSION", 400)
    if not shoot_end or not isinstance(shoot_end, str):
        raise ApiError(ERR_INVALID_REQUEST, "shoot_end is required for COMMISSION", 400)

    ss = parse_iso(shoot_start)
    se = parse_iso(shoot_end)
    if ss is None or se is None:
        raise ApiError(ERR_INVALID_REQUEST, "shoot_start and shoot_end must be valid ISO 8601 datetimes", 400)
    if se < ss:
        raise ApiError(ERR_INVALID_REQUEST, "shoot_end must be >= shoot_start", 400)

    if not isinstance(min_image_count, int) or isinstance(min_image_count, bool):
        raise ApiError(ERR_INVALID_REQUEST, "min_image_count must be an integer", 400)
    if not isinstance(max_image_count, int) or isinstance(max_image_count, bool):
        raise ApiError(ERR_INVALID_REQUEST, "max_image_count must be an integer", 400)

    # Existence: photographer
    photog = photographers.get(photographer_id)
    if photog is None:
        raise ApiError(ERR_PHOTOGRAPHER_NOT_FOUND, f"Photographer {photographer_id} not found", 404)

    # Priority 11 (§2.8): double-booking check, evaluated before the suspended gate
    # Buffered window: [shoot_start - 1d, shoot_end + 1d] CLOSED
    new_buf_start = ss - timedelta(days=1)
    new_buf_end = se + timedelta(days=1)

    for existing_a in assignments.values():
        if existing_a["photographer_id"] != photographer_id:
            continue
        if existing_a["status"] not in ("COMMISSIONED", "IN_PROGRESS", "SUBMITTED", "REVISION_REQUESTED"):
            continue
        ess = parse_iso(existing_a["shoot_start"])
        ese = parse_iso(existing_a["shoot_end"])
        if ess is None or ese is None:
            continue
        ex_buf_start = ess - timedelta(days=1)
        ex_buf_end = ese + timedelta(days=1)
        # Closed interval intersection
        if new_buf_start <= ex_buf_end and ex_buf_start <= new_buf_end:
            raise ApiError(ERR_PHOTOGRAPHER_DOUBLE_BOOKED,
                           "Photographer is double-booked for the requested window", 409)

    # Priority 12 (§2.8): commissioned photographer must be ACTIVE
    if photog["status"] != "ACTIVE":
        raise ApiError(ERR_PHOTOGRAPHER_SUSPENDED, "Photographer is SUSPENDED", 409)

    # Compute day_count: date(shoot_end) - date(shoot_start) + 1
    day_count = (se.date() - ss.date()).days + 1

    # Create Assignment
    aid = new_id()
    now = now_iso()
    assignment = {
        "id": aid,
        "story_request_id": sr["id"],
        "photographer_id": photographer_id,
        "brief": brief,
        "shoot_start": shoot_start,
        "shoot_end": shoot_end,
        "min_image_count": min_image_count,
        "max_image_count": max_image_count,
        "day_count": day_count,
        "revision_count": 0,
        "accepted_at": None,
        "kill_fee_cents": 0,
        "status": "COMMISSIONED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    assignments[aid] = assignment
    sr["commissioned_assignment_id"] = aid


def _decide_wire_stock(sr, body):
    """Handle WIRE_STOCK decision branch."""
    image_id = body.get("image_id")
    if not image_id or not isinstance(image_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "image_id is required for WIRE_STOCK", 400)

    img = images.get(image_id)
    if img is None:
        raise ApiError(ERR_IMAGE_NOT_FOUND, f"Image {image_id} not found", 404)

    # Priority 6: image must be in {CLEARED, PUBLISHED, ARCHIVED}
    if img["status"] not in ("CLEARED", "PUBLISHED", "ARCHIVED"):
        raise ApiError(ERR_IMAGE_NOT_CLEARED, "Image is not yet cleared", 409)

    sr["sourced_image_id"] = image_id


@bp.route("/story-requests/<srid>/cancel", methods=["POST"])
def cancel_story_request(srid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor"})

    sr = story_requests.get(srid)
    if sr is None:
        raise ApiError(ERR_STORY_REQUEST_NOT_FOUND, f"Story request {srid} not found", 404)

    if sr["status"] not in ("OPEN", "DECIDED"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot cancel story request in status {sr['status']}", 409)

    now = now_iso()

    if sr["status"] == "DECIDED":
        # Cascade: cancel commissioned assignment
        if sr["commissioned_assignment_id"]:
            a = assignments.get(sr["commissioned_assignment_id"])
            if a and a["status"] in ("COMMISSIONED", "IN_PROGRESS", "SUBMITTED", "REVISION_REQUESTED"):
                old_status = a["status"]
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

        # Cascade: revoke DRAFT/ACTIVE licenses linked to this story
        from services.calculations import process_license_lazy_expiry
        for lic in licenses.values():
            # Process lazy expiry first so we don't double-release budget
            process_license_lazy_expiry(lic)
            if lic.get("story_request_id") == sr["id"] and lic["status"] in ("DRAFT", "ACTIVE"):
                old_lic_status = lic["status"]
                lic["status"] = "REVOKED"
                lic["updated_at"] = now
                lic["version"] += 1
                if old_lic_status == "ACTIVE":
                    sr["committed_cents"] -= lic["fee_cents"]

    sr["status"] = "CANCELLED"
    sr["updated_at"] = now
    sr["version"] += 1
    return success_object(serialize_story_request(sr))
