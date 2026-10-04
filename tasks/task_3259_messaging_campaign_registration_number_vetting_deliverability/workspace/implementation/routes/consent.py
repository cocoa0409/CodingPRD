"""ConsentRecord routes: create, get/list, revoke, messages sub-collection."""
from datetime import timedelta

from flask import Blueprint, request

import store
from constants import CONSENT_METHODS, CONSENT_RETENTION_DAYS
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_BRAND_REVOKED,
    validation,
)
from response import success_object, success_list
from serializers import ser_consent, ser_message
from services.shared import check_account_gate
from util import (
    find_or_404,
    format_iso,
    get_json_body,
    new_id,
    pagination_params,
    parse_iso,
    require_auth,
    require_enum,
    require_nonempty,
    sort_by_created,
)

bp = Blueprint("consent", __name__)

CONSENT_ROLES = [
    "PlatformAdmin", "ComplianceOfficer", "BrandManager", "CampaignManager",
    "CarrierReviewer",
]


@bp.post("/messaging/accounts/<account_id>/consent_records")
def create_consent(account_id):
    require_auth(["BrandManager", "CampaignManager"])
    account = find_or_404(store.ACCOUNTS, account_id)
    check_account_gate(account)
    body = get_json_body()
    require_nonempty(body, [
        "brand_id", "phone_number", "evidence_url", "evidence_text",
        "captured_at",
    ])
    consent_method = require_enum(body, "consent_method", CONSENT_METHODS)
    brand = store.BRANDS.get(body["brand_id"])
    if brand is None or brand["account_id"] != account_id:
        raise ApiError(ERR_NOT_FOUND, "Brand not found under account", 404)
    if brand["status"] == "REVOKED":
        raise ApiError(ERR_BRAND_REVOKED, "Brand is revoked", 409)
    try:
        captured_at = parse_iso(body["captured_at"])
    except (ValueError, TypeError):
        raise validation("captured_at must be an ISO 8601 timestamp")
    if consent_method == "POST_BRAND":
        verified_at = brand.get("verified_at")
        if verified_at is None or captured_at < parse_iso(verified_at):
            raise validation(
                "captured_at must be at or after brand verification for POST_BRAND consent"
            )
    retention = format_iso(captured_at + timedelta(days=CONSENT_RETENTION_DAYS))
    record = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "account_id": account_id,
        "brand_id": brand["id"],
        "phone_number": body["phone_number"],
        "evidence_url": body["evidence_url"],
        "evidence_text": body["evidence_text"],
        "captured_at": format_iso(captured_at),
        "retention_expires_at": retention,
        "consent_method": consent_method,
        "revoked_at": None,
        "revoked_by_keyword": "",
        "status": "ACTIVE",
    }
    store.CONSENTS[record["id"]] = record
    return success_object(ser_consent(record), 201)


@bp.get("/messaging/accounts/<account_id>/consent_records/<consent_id>")
def get_consent(account_id, consent_id):
    require_auth(CONSENT_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    record = find_or_404(store.CONSENTS, consent_id, account_id)
    return success_object(ser_consent(record))


@bp.get("/messaging/consent_records/<consent_id>")
def get_consent_alias(consent_id):
    require_auth(CONSENT_ROLES)
    record = find_or_404(store.CONSENTS, consent_id)
    return success_object(ser_consent(record))


def _filter_consents(items):
    status_filter = request.args.get("status")
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    brand_filter = request.args.get("brand_id")
    if brand_filter:
        items = [c for c in items if c["brand_id"] == brand_filter]
    phone_filter = request.args.get("phone_number")
    if phone_filter:
        items = [c for c in items if c["phone_number"] == phone_filter]
    return items


@bp.get("/messaging/accounts/<account_id>/consent_records")
def list_account_consents(account_id):
    require_auth(CONSENT_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    limit, offset = pagination_params()
    items = [c for c in store.CONSENTS.values() if c["account_id"] == account_id]
    items = _filter_consents(items)
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_consent(c) for c in page], limit, offset, total)


@bp.get("/messaging/consent_records")
def list_consents():
    require_auth(["PlatformAdmin", "ComplianceOfficer"])
    limit, offset = pagination_params()
    items = list(store.CONSENTS.values())
    account_filter = request.args.get("account_id")
    if account_filter:
        items = [c for c in items if c["account_id"] == account_filter]
    items = _filter_consents(items)
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_consent(c) for c in page], limit, offset, total)


@bp.get("/messaging/accounts/<account_id>/consent_records/<consent_id>/messages")
def list_consent_messages(account_id, consent_id):
    require_auth(CONSENT_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    find_or_404(store.CONSENTS, consent_id, account_id)
    limit, offset = pagination_params()
    items = [
        m for m in store.MESSAGES.values()
        if m["account_id"] == account_id and m.get("consent_record_id") == consent_id
    ]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_message(m) for m in page], limit, offset, total)


@bp.post("/messaging/accounts/<account_id>/consent_records/<consent_id>/revoke")
def revoke_consent(account_id, consent_id):
    require_auth(["BrandManager", "ComplianceOfficer"])
    account = find_or_404(store.ACCOUNTS, account_id)
    record = find_or_404(store.CONSENTS, consent_id, account_id)
    check_account_gate(account)
    if record["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Consent record is not ACTIVE", 409)
    record["status"] = "REVOKED"
    record["revoked_at"] = store.now_iso()
    return success_object(ser_consent(record))
