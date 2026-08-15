"""Release record endpoints."""

from flask import Blueprint, request
from db import releases, images, new_id, now_iso, parse_iso
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_RELEASE_NOT_FOUND, ERR_IMAGE_NOT_FOUND,
    ERR_INVALID_STATE,
)
from response import success_object, success_list
from middleware import get_auth, require_role
from serializers import serialize_release, _release_effective_status

bp = Blueprint("releases", __name__)


@bp.route("/images/<iid>/releases", methods=["POST"])
def create_release(iid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    body = request.get_json(force=True, silent=True) or {}

    subject_type = body.get("subject_type")
    if subject_type not in ("MODEL", "PROPERTY"):
        raise ApiError(ERR_INVALID_REQUEST, "subject_type must be MODEL or PROPERTY", 400)

    subject_name = body.get("subject_name")
    if not subject_name or not isinstance(subject_name, str):
        raise ApiError(ERR_INVALID_REQUEST, "subject_name is required", 400)

    document_ref = body.get("document_ref")
    if not document_ref or not isinstance(document_ref, str):
        raise ApiError(ERR_INVALID_REQUEST, "document_ref is required", 400)

    signed_at = body.get("signed_at")
    if not signed_at or not isinstance(signed_at, str):
        raise ApiError(ERR_INVALID_REQUEST, "signed_at is required", 400)
    if parse_iso(signed_at) is None:
        raise ApiError(ERR_INVALID_REQUEST, "signed_at must be a valid ISO 8601 datetime", 400)

    expires_at = body.get("expires_at")
    if expires_at is not None:
        if not isinstance(expires_at, str) or parse_iso(expires_at) is None:
            raise ApiError(ERR_INVALID_REQUEST, "expires_at must be a valid ISO 8601 datetime or null", 400)

    # Existence
    img = images.get(iid)
    if img is None:
        raise ApiError(ERR_IMAGE_NOT_FOUND, f"Image {iid} not found", 404)

    rid = new_id()
    now = now_iso()
    rel = {
        "id": rid,
        "image_id": iid,
        "subject_type": subject_type,
        "subject_name": subject_name,
        "document_ref": document_ref,
        "signed_at": signed_at,
        "expires_at": expires_at,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    releases[rid] = rel
    return success_object(serialize_release(rel), 201)


@bp.route("/images/<iid>/releases", methods=["GET"])
def list_image_releases(iid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager", "Archivist"})

    img = images.get(iid)
    if img is None:
        raise ApiError(ERR_IMAGE_NOT_FOUND, f"Image {iid} not found", 404)

    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    items = [r for r in releases.values() if r["image_id"] == iid]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_release(r) for r in page], limit, offset, total)


@bp.route("/releases/<rid>/revoke", methods=["POST"])
def revoke_release(rid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    rel = releases.get(rid)
    if rel is None:
        raise ApiError(ERR_RELEASE_NOT_FOUND, f"Release {rid} not found", 404)

    eff_status = _release_effective_status(rel)
    if eff_status != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, f"Cannot revoke release in status {eff_status}", 409)

    rel["status"] = "REVOKED"
    rel["updated_at"] = now_iso()
    rel["version"] += 1
    return success_object(serialize_release(rel))
