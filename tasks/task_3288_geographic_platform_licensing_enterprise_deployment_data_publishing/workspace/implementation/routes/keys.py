"""API keys (§3.11)."""
from flask import Blueprint, request

import store
from auth import require_role
from calc import SERVICE_KINDS
from envelope import paginate, success
from errors import err
from helpers import get_body, require_fields

bp = Blueprint("keys", __name__)


@bp.post("/geo-orgs/api-keys")
def create_key():
    caller_id, role = require_role("NamedUser", "LicenseAdmin")
    body = get_body()
    require_fields(body, [
        ("named_user_id", "str", True),
        ("organization_id", "str", True),
        ("label", "str", True),
        ("allowed_service_kinds", "list", True),
        ("per_key_credit_cap", "int", True),
    ])
    kinds = body["allowed_service_kinds"]
    if any(not isinstance(k, str) or k not in SERVICE_KINDS for k in kinds):
        raise err("ERR_INVALID_REQUEST", "allowed_service_kinds must be valid service kinds")
    user = store.named_users.get(body["named_user_id"])
    if user is None:
        raise err("ERR_USER_NOT_FOUND")
    if body["organization_id"] != user["organization_id"]:
        raise err("ERR_INVALID_REQUEST",
                  "organization_id must equal the owning named user's organization_id")
    if store.orgs.get(body["organization_id"]) is None:
        raise err("ERR_ORG_NOT_FOUND")
    if role == "NamedUser" and caller_id != body["named_user_id"]:
        raise err("ERR_USER_IDENTITY_MISMATCH")
    rec = store.new_record()
    rec.update({
        "named_user_id": user["id"],
        "organization_id": body["organization_id"],
        "label": body["label"],
        "allowed_service_kinds": kinds,
        "per_key_credit_cap": body["per_key_credit_cap"],
        "credits_consumed": 0,
        "status": "ACTIVE",
    })
    store.api_keys[rec["id"]] = rec
    return success(dict(rec), status=201)


@bp.get("/geo-orgs/named-users/<user_id>/api-keys")
def list_keys(user_id):
    require_role("PlatformAdmin", "LicenseAdmin", "BillingAdmin", "NamedUser")
    if user_id not in store.named_users:
        raise err("ERR_USER_NOT_FOUND")
    items = sorted(
        (k for k in store.api_keys.values() if k["named_user_id"] == user_id),
        key=lambda r: r["created_at"],
    )
    status = request.args.get("status")
    if status is not None:
        items = [k for k in items if k["status"] == status]
    page, pg = paginate(items, request.args)
    return success([dict(k) for k in page], pagination=pg)


@bp.post("/geo-orgs/api-keys/<key_id>/revoke")
def revoke_key(key_id):
    caller_id, role = require_role("LicenseAdmin", "NamedUser")
    key = store.api_keys.get(key_id)
    if key is None:
        raise err("ERR_KEY_NOT_FOUND")
    if key["status"] != "ACTIVE":
        raise err("ERR_API_KEY_REVOKED")
    if role == "NamedUser" and caller_id != key["named_user_id"]:
        raise err("ERR_NOT_ITEM_OWNER")
    key["status"] = "REVOKED"
    store.touch(key)
    return success(dict(key))
