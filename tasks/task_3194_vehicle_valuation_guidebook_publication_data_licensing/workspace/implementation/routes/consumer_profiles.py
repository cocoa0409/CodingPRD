"""Consumer profile endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import DB
from errors import (
    not_found, invalid_input, duplicate_key,
)
from middleware import require_roles
from response import success
from services.entity import stamp_new


bp = Blueprint("consumer_profiles", __name__)


def _profile_view(p):
    return {
        "id": p["id"],
        "email": p["email"],
        "full_name": p["full_name"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/consumer-profiles", methods=["POST"])
def create_consumer_profile():
    require_roles("Consumer")
    body = request.get_json(silent=True) or {}
    email = body.get("email")
    full_name = body.get("full_name")
    if not isinstance(email, str) or not email:
        raise invalid_input("email is required")
    if not isinstance(full_name, str) or not full_name:
        raise invalid_input("full_name is required")
    if email in DB._consumer_emails:
        raise duplicate_key("email already registered")
    p = stamp_new({
        "email": email,
        "full_name": full_name,
    })
    DB.consumer_profiles[p["id"]] = p
    DB._consumer_emails[email] = p["id"]
    return success(_profile_view(p), 201)


@bp.route("/consumer-profiles", methods=["GET"])
def list_consumer_profiles():
    require_roles("ValuationAdmin", "DealerPartner")
    items = list(DB.consumer_profiles.values())
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_profile_view(p) for p in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/consumer-profiles/<profile_id>", methods=["GET"])
def get_consumer_profile(profile_id):
    role, user_id = require_roles("Consumer", "ValuationAdmin")
    p = DB.consumer_profiles.get(profile_id)
    if p is None:
        raise not_found("consumer profile not found")
    if role == "Consumer" and user_id != profile_id:
        # own profile only
        from errors import unauthorized
        raise unauthorized("consumers may fetch only their own profile")
    return success(_profile_view(p), 200)
