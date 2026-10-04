"""Message routes: send, get/list, delivery_outcome, retry, cancel,
feedback sub-collection."""
from flask import Blueprint, request

import store
from constants import (
    CARRIERS,
    CARRIER_ERROR_CODES,
    RETRYABLE_ERROR_CODES,
    DELIVERY_OUTCOMES,
)
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_CAMPAIGN_NOT_APPROVED,
    ERR_NUMBER_NOT_ATTACHED,
    ERR_NO_CONSENT,
    ERR_MESSAGE_NOT_RETRYABLE,
    validation,
)
from response import success_object, success_list
from serializers import ser_message, ser_feedback


def _is_carrier_error_code(code):
    """PRD section 3.6 requires a carrier error code on FAILED outcomes but
    never enumerates the full set; accept the carrier-code shape (E plus
    digits) so any well-formed carrier code is recorded."""
    return isinstance(code, str) and len(code) > 1 and code[0] == "E" and code[1:].isdigit()
from services.calc import compute_allocated_mps, compute_segments
from services.shared import (
    active_consent_for,
    check_account_gate,
    check_recipient_not_busy,
    check_throughput,
    current_run_index,
    queue_message,
)
from util import (
    find_or_404,
    get_json_body,
    new_id,
    now_dt,
    pagination_params,
    require_auth,
    require_enum,
    require_nonempty,
    sort_by_created,
    touch,
)

bp = Blueprint("messages", __name__)

MESSAGE_READ_ROLES = [
    "PlatformAdmin", "ComplianceOfficer", "CampaignManager",
    "CarrierReviewer", "SystemDriver",
]
MESSAGE_LIST_ROLES = [
    "PlatformAdmin", "ComplianceOfficer", "CampaignManager", "CarrierReviewer",
]


@bp.post("/messaging/accounts/<account_id>/messages")
def send_message(account_id):
    require_auth(["CampaignManager"])
    account = find_or_404(store.ACCOUNTS, account_id)
    check_account_gate(account)
    body = get_json_body()
    require_nonempty(body, ["campaign_id", "sender_number_id", "to_number"])
    campaign = store.CAMPAIGNS.get(body["campaign_id"])
    if campaign is None or campaign["account_id"] != account_id:
        raise ApiError(ERR_NOT_FOUND, "Campaign not found under account", 404)
    # Compliance gate (PRD 2.8 step 5): campaign APPROVED first, then the
    # sender number must be ACTIVE and attached to the campaign.
    if campaign["status"] != "APPROVED":
        raise ApiError(ERR_CAMPAIGN_NOT_APPROVED, "Campaign is not APPROVED", 409)
    number = store.NUMBERS.get(body["sender_number_id"])
    if number is None or number["account_id"] != account_id:
        raise ApiError(ERR_NOT_FOUND, "Sender number not found under account", 404)
    if number.get("campaign_id") != campaign["id"]:
        raise ApiError(
            ERR_NUMBER_NOT_ATTACHED,
            "Sender number is not attached to the campaign",
            409,
        )
    if number["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Sender number is not ACTIVE", 409)
    # Consent gate.
    consent = active_consent_for(campaign["brand_id"], body["to_number"])
    if consent is None:
        raise ApiError(
            ERR_NO_CONSENT,
            "No ACTIVE consent record for the campaign's brand and recipient",
            409,
        )
    # Field shape: body 1-1600 chars, carrier declared.
    msg_body = body.get("body")
    if not isinstance(msg_body, str) or not (1 <= len(msg_body) <= 1600):
        raise validation("body must be between 1 and 1600 characters")
    carrier_code = require_enum(body, "carrier_code", CARRIERS)
    # Recompute live allocated_mps (TEN_DLC tracks trust_score).
    campaign["allocated_mps"] = compute_allocated_mps(campaign)
    # Throughput gate.
    check_throughput(campaign, now_dt())
    # Recipient in-flight uniqueness.
    check_recipient_not_busy(campaign["id"], body["to_number"])

    message = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "updated_at": store.now_iso(),
        "version": 1,
        "account_id": account_id,
        "campaign_id": campaign["id"],
        "sender_number_id": number["id"],
        "to_number": body["to_number"],
        "consent_record_id": consent["id"],
        "body": msg_body,
        "carrier_code": carrier_code,
        "segments": compute_segments(msg_body),
        "queued_at": None,
        "queued_run_index": 0,
        "failed_error_code": "",
        "status": "ACCEPTED",
    }
    store.MESSAGES[message["id"]] = message
    queue_message(message, current_run_index(account_id))
    return success_object(ser_message(message), 201)


@bp.get("/messaging/accounts/<account_id>/messages/<message_id>")
def get_message(account_id, message_id):
    require_auth(MESSAGE_READ_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    message = find_or_404(store.MESSAGES, message_id, account_id)
    return success_object(ser_message(message))


@bp.get("/messaging/messages/<message_id>")
def get_message_alias(message_id):
    require_auth(MESSAGE_READ_ROLES)
    message = find_or_404(store.MESSAGES, message_id)
    return success_object(ser_message(message))


def _filter_messages(items):
    status_filter = request.args.get("status")
    if status_filter:
        items = [m for m in items if m["status"] == status_filter]
    campaign_filter = request.args.get("campaign_id")
    if campaign_filter:
        items = [m for m in items if m["campaign_id"] == campaign_filter]
    number_filter = request.args.get("sender_number_id")
    if number_filter:
        items = [m for m in items if m["sender_number_id"] == number_filter]
    consent_filter = request.args.get("consent_record_id")
    if consent_filter:
        items = [m for m in items if m.get("consent_record_id") == consent_filter]
    return items


@bp.get("/messaging/accounts/<account_id>/messages")
def list_account_messages(account_id):
    require_auth(MESSAGE_LIST_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    limit, offset = pagination_params()
    items = [m for m in store.MESSAGES.values() if m["account_id"] == account_id]
    items = _filter_messages(items)
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_message(m) for m in page], limit, offset, total)


@bp.get("/messaging/messages")
def list_messages():
    require_auth(["PlatformAdmin", "ComplianceOfficer"])
    limit, offset = pagination_params()
    items = list(store.MESSAGES.values())
    account_filter = request.args.get("account_id")
    if account_filter:
        items = [m for m in items if m["account_id"] == account_filter]
    items = _filter_messages(items)
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_message(m) for m in page], limit, offset, total)


@bp.get("/messaging/accounts/<account_id>/messages/<message_id>/feedback_events")
def list_message_feedback(account_id, message_id):
    require_auth(MESSAGE_LIST_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    find_or_404(store.MESSAGES, message_id, account_id)
    limit, offset = pagination_params()
    items = [
        f for f in store.FEEDBACK.values()
        if f["account_id"] == account_id and f.get("message_id") == message_id
    ]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_feedback(f) for f in page], limit, offset, total)


@bp.post("/messaging/accounts/<account_id>/messages/<message_id>/delivery_outcome")
def delivery_outcome(account_id, message_id):
    require_auth(["SystemDriver"])
    account = find_or_404(store.ACCOUNTS, account_id)
    message = find_or_404(store.MESSAGES, message_id, account_id)
    check_account_gate(account)
    if message["status"] != "SENT":
        raise ApiError(ERR_INVALID_STATE, "Message is not SENT", 409)
    body = get_json_body()
    outcome = require_enum(body, "outcome", DELIVERY_OUTCOMES)
    if outcome == "FAILED":
        error_code = body.get("error_code")
        if not _is_carrier_error_code(error_code):
            raise validation("error_code is not a declared carrier error code")
        message["failed_error_code"] = error_code
    message["status"] = outcome
    touch(message)
    return success_object(ser_message(message))


@bp.post("/messaging/accounts/<account_id>/messages/<message_id>/retry")
def retry_message(account_id, message_id):
    require_auth(["CampaignManager"])
    account = find_or_404(store.ACCOUNTS, account_id)
    message = find_or_404(store.MESSAGES, message_id, account_id)
    check_account_gate(account)
    if message["status"] != "FAILED":
        raise ApiError(ERR_INVALID_STATE, "Message is not FAILED", 409)
    if message["failed_error_code"] not in RETRYABLE_ERROR_CODES:
        raise ApiError(
            ERR_MESSAGE_NOT_RETRYABLE,
            "failed_error_code is not retryable",
            409,
        )
    campaign = store.CAMPAIGNS.get(message["campaign_id"])
    if campaign is None:
        raise ApiError(ERR_NOT_FOUND, "Campaign not found", 404)
    if campaign["status"] != "APPROVED":
        raise ApiError(ERR_CAMPAIGN_NOT_APPROVED, "Campaign is not APPROVED", 409)
    consent = active_consent_for(campaign["brand_id"], message["to_number"])
    if consent is None:
        raise ApiError(ERR_NO_CONSENT, "Consent has been revoked", 409)
    campaign["allocated_mps"] = compute_allocated_mps(campaign)
    check_throughput(campaign, now_dt())
    check_recipient_not_busy(campaign["id"], message["to_number"])
    message["status"] = "ACCEPTED"
    message["failed_error_code"] = ""
    message["consent_record_id"] = consent["id"]
    touch(message)
    queue_message(message, current_run_index(account_id))
    return success_object(ser_message(message))


@bp.post("/messaging/accounts/<account_id>/messages/<message_id>/cancel")
def cancel_message(account_id, message_id):
    require_auth(["CampaignManager"])
    account = find_or_404(store.ACCOUNTS, account_id)
    message = find_or_404(store.MESSAGES, message_id, account_id)
    check_account_gate(account)
    if message["status"] not in ("QUEUED", "FAILED"):
        raise ApiError(ERR_INVALID_STATE, "Message is not QUEUED or FAILED", 409)
    message["status"] = "STALE_CANCELLED"
    touch(message)
    return success_object(ser_message(message))
