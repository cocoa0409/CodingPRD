"""Infringement claim endpoints."""

from flask import Blueprint, request
from db import (
    claims, images, photographers, licenses, story_requests,
    new_id, now_iso, parse_iso, logical_now,
)
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_CLAIM_NOT_FOUND, ERR_IMAGE_NOT_FOUND,
    ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES,
)
from response import success_object, success_list
from middleware import get_auth, require_role
from serializers import serialize_claim, _license_effective_status
from services.calculations import compute_settlement_split

bp = Blueprint("claims", __name__)

OPEN_CLAIM_STATUSES = {"INTAKE", "UNDER_REVIEW", "SETTLEMENT_OFFERED", "COUNTERED", "ESCALATED"}


@bp.route("/infringement-claims", methods=["POST"])
def intake_claim():
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    body = request.get_json(force=True, silent=True) or {}

    image_id = body.get("image_id")
    claimant_name = body.get("claimant_name")
    claim_type = body.get("claim_type")
    description = body.get("description")
    claimed_amount_cents = body.get("claimed_amount_cents")

    if not image_id or not isinstance(image_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "image_id is required", 400)
    if not claimant_name or not isinstance(claimant_name, str):
        raise ApiError(ERR_INVALID_REQUEST, "claimant_name is required", 400)
    if claim_type not in ("UNLICENSED_USE", "COPYRIGHT_DISPUTE", "MODEL_RELEASE_VIOLATION"):
        raise ApiError(ERR_INVALID_REQUEST, "claim_type must be UNLICENSED_USE, COPYRIGHT_DISPUTE, or MODEL_RELEASE_VIOLATION", 400)
    if not description or not isinstance(description, str):
        raise ApiError(ERR_INVALID_REQUEST, "description is required", 400)
    if claimed_amount_cents is None or not isinstance(claimed_amount_cents, int) or isinstance(claimed_amount_cents, bool):
        raise ApiError(ERR_INVALID_REQUEST, "claimed_amount_cents is required and must be an integer", 400)

    img = images.get(image_id)
    if img is None:
        raise ApiError(ERR_IMAGE_NOT_FOUND, f"Image {image_id} not found", 404)

    now = now_iso()

    # Latch image RESTRICTED
    img["restriction_status"] = "RESTRICTED"
    img["updated_at"] = now
    img["version"] += 1

    cid = new_id()
    claim = {
        "id": cid,
        "image_id": image_id,
        "claimant_name": claimant_name,
        "claim_type": claim_type,
        "description": description,
        "claimed_amount_cents": claimed_amount_cents,
        "proposed_settlement_cents": None,
        "settlement_amount_cents": None,
        "photographer_clawback_cents": None,
        "intaken_by_user_id": user_id,
        "resolved_by_user_id": None,
        "resolved_at": None,
        "resolution_outcome": None,
        "status": "INTAKE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    claims[cid] = claim
    return success_object(serialize_claim(claim), 201)


@bp.route("/infringement-claims", methods=["GET"])
def list_claims():
    user_id, role = get_auth()
    require_role(role, {"RightsManager", "PhotoEditor", "FinanceAdmin"})

    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    image_id = request.args.get("image_id")
    status_filter = request.args.get("status")

    items = list(claims.values())
    if image_id:
        items = [c for c in items if c["image_id"] == image_id]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]

    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_claim(c) for c in page], limit, offset, total)


@bp.route("/infringement-claims/<cid>", methods=["GET"])
def get_claim(cid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager", "PhotoEditor", "FinanceAdmin"})

    c = claims.get(cid)
    if c is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, f"Claim {cid} not found", 404)
    return success_object(serialize_claim(c))


@bp.route("/infringement-claims/<cid>/review", methods=["POST"])
def review_claim(cid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    c = claims.get(cid)
    if c is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, f"Claim {cid} not found", 404)

    if c["status"] != "INTAKE":
        raise ApiError(ERR_INVALID_STATE, f"Cannot review claim in status {c['status']}", 409)

    c["status"] = "UNDER_REVIEW"
    c["updated_at"] = now_iso()
    c["version"] += 1
    return success_object(serialize_claim(c))


@bp.route("/infringement-claims/<cid>/offer", methods=["POST"])
def offer_claim(cid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    body = request.get_json(force=True, silent=True) or {}
    settlement_offer_cents = body.get("settlement_offer_cents")
    if settlement_offer_cents is None or not isinstance(settlement_offer_cents, int) or isinstance(settlement_offer_cents, bool):
        raise ApiError(ERR_INVALID_REQUEST, "settlement_offer_cents is required and must be an integer", 400)

    c = claims.get(cid)
    if c is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, f"Claim {cid} not found", 404)

    if c["status"] not in ("UNDER_REVIEW", "COUNTERED"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot offer settlement in status {c['status']}", 409)

    c["status"] = "SETTLEMENT_OFFERED"
    c["proposed_settlement_cents"] = settlement_offer_cents
    c["updated_at"] = now_iso()
    c["version"] += 1
    return success_object(serialize_claim(c))


@bp.route("/infringement-claims/<cid>/counter", methods=["POST"])
def counter_claim(cid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    body = request.get_json(force=True, silent=True) or {}
    counter_amount_cents = body.get("counter_amount_cents")
    if counter_amount_cents is None or not isinstance(counter_amount_cents, int) or isinstance(counter_amount_cents, bool):
        raise ApiError(ERR_INVALID_REQUEST, "counter_amount_cents is required and must be an integer", 400)

    c = claims.get(cid)
    if c is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, f"Claim {cid} not found", 404)

    if c["status"] != "SETTLEMENT_OFFERED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot counter in status {c['status']}", 409)

    c["status"] = "COUNTERED"
    c["proposed_settlement_cents"] = counter_amount_cents
    c["updated_at"] = now_iso()
    c["version"] += 1
    return success_object(serialize_claim(c))


@bp.route("/infringement-claims/<cid>/escalate", methods=["POST"])
def escalate_claim(cid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    c = claims.get(cid)
    if c is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, f"Claim {cid} not found", 404)

    if c["status"] not in ("UNDER_REVIEW", "SETTLEMENT_OFFERED", "COUNTERED"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot escalate claim in status {c['status']}", 409)

    c["status"] = "ESCALATED"
    c["updated_at"] = now_iso()
    c["version"] += 1
    return success_object(serialize_claim(c))


@bp.route("/infringement-claims/<cid>/resolve", methods=["POST"])
def resolve_claim(cid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    body = request.get_json(force=True, silent=True) or {}
    outcome = body.get("outcome")
    if outcome not in ("UPHELD", "DISMISSED"):
        raise ApiError(ERR_INVALID_REQUEST, "outcome must be UPHELD or DISMISSED", 400)

    c = claims.get(cid)
    if c is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, f"Claim {cid} not found", 404)

    # State check: must be in a resolvable state
    if c["status"] not in ("UNDER_REVIEW", "SETTLEMENT_OFFERED", "COUNTERED", "ESCALATED"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot resolve claim in status {c['status']}", 409)

    # Priority 9: segregation of duties
    if user_id == c["intaken_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "Resolver must differ from intaker", 403)

    now = now_iso()

    if outcome == "UPHELD":
        settlement_amount_cents = body.get("settlement_amount_cents")
        if settlement_amount_cents is None or not isinstance(settlement_amount_cents, int) or isinstance(settlement_amount_cents, bool):
            raise ApiError(ERR_INVALID_REQUEST, "settlement_amount_cents is required for UPHELD", 400)
        if settlement_amount_cents <= 0:
            raise ApiError(ERR_INVALID_REQUEST, "settlement_amount_cents must be > 0", 400)
        if settlement_amount_cents > c["claimed_amount_cents"]:
            raise ApiError(ERR_INVALID_REQUEST,
                           f"settlement_amount_cents ({settlement_amount_cents}) exceeds claimed_amount_cents ({c['claimed_amount_cents']})", 400)

        c["status"] = "RESOLVED"
        c["resolution_outcome"] = "UPHELD"
        c["settlement_amount_cents"] = settlement_amount_cents
        c["resolved_at"] = now
        c["resolved_by_user_id"] = user_id

        # Settlement split
        img = images.get(c["image_id"])
        if img:
            clawback = compute_settlement_split(settlement_amount_cents, img)
            c["photographer_clawback_cents"] = clawback

            # Cascade 1: latch image RESTRICTED
            img["restriction_status"] = "RESTRICTED"
            img["updated_at"] = now
            img["version"] += 1

            # Cascade 2: revoke ACTIVE licenses on the image
            for lic in licenses.values():
                if lic["image_id"] == img["id"]:
                    # Process lazy expiry first
                    eff = _license_effective_status(lic)
                    if eff == "ACTIVE":
                        lic["status"] = "REVOKED"
                        lic["updated_at"] = now
                        lic["version"] += 1
                        # Cascade 3: release story budget
                        if lic.get("story_request_id"):
                            sr = story_requests.get(lic["story_request_id"])
                            if sr:
                                sr["committed_cents"] -= lic["fee_cents"]
                                sr["updated_at"] = now
                                sr["version"] += 1

            # Cascade 4: debit photographer (ASSIGNMENT images only)
            if img["source_type"] == "ASSIGNMENT" and img.get("photographer_id"):
                photog = photographers.get(img["photographer_id"])
                if photog:
                    photog["accrued_earnings_cents"] = max(0, photog["accrued_earnings_cents"] - clawback)
                    photog["updated_at"] = now
                    photog["version"] += 1

    else:  # DISMISSED
        c["status"] = "DISMISSED"
        c["resolution_outcome"] = "DISMISSED"
        c["resolved_at"] = now
        c["resolved_by_user_id"] = user_id

        # Lift restriction if no other open claims on this image
        img = images.get(c["image_id"])
        if img:
            other_open = any(
                oc["image_id"] == img["id"] and oc["id"] != c["id"] and oc["status"] in OPEN_CLAIM_STATUSES
                for oc in claims.values()
            )
            if not other_open:
                img["restriction_status"] = "NONE"
                img["updated_at"] = now
                img["version"] += 1

    c["updated_at"] = now
    c["version"] += 1
    return success_object(serialize_claim(c))
