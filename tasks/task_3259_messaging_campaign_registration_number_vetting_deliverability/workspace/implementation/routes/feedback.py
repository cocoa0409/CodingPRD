"""FeedbackEvent routes: create (with in-request apply), get/list."""
from flask import Blueprint, request

import store
from constants import FEEDBACK_KINDS
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    validation,
)
from response import success_object, success_list
from serializers import ser_feedback
from services.shared import active_consent_for, check_account_gate
from util import (
    find_or_404,
    get_json_body,
    new_id,
    pagination_params,
    require_auth,
    require_enum,
    require_nonempty,
    sort_by_created,
)

bp = Blueprint("feedback", __name__)

FEEDBACK_ROLES = [
    "PlatformAdmin", "ComplianceOfficer", "CampaignManager", "CarrierReviewer",
]


@bp.post("/messaging/accounts/<account_id>/feedback_events")
def create_feedback(account_id):
    require_auth(["SystemDriver"])
    account = find_or_404(store.ACCOUNTS, account_id)
    check_account_gate(account)
    body = get_json_body()
    require_nonempty(body, ["campaign_id"])
    kind = require_enum(body, "kind", FEEDBACK_KINDS)
    campaign = store.CAMPAIGNS.get(body["campaign_id"])
    if campaign is None or campaign["account_id"] != account_id:
        raise ApiError(ERR_NOT_FOUND, "Campaign not found under account", 404)

    message_id = ""
    keyword = ""
    to_number = ""
    if kind in ("BLOCK", "SPAM_COMPLAINT"):
        mid = body.get("message_id")
        if not isinstance(mid, str) or not mid.strip():
            raise validation("message_id is required for BLOCK/SPAM_COMPLAINT")
        message = store.MESSAGES.get(mid)
        if message is None or message["campaign_id"] != campaign["id"]:
            raise ApiError(
                ERR_NOT_FOUND, "Message not found under campaign", 404
            )
        message_id = mid
    else:  # STOP
        keyword = body.get("keyword")
        to_number = body.get("to_number")
        if not isinstance(keyword, str) or not keyword.strip():
            raise validation("keyword is required for STOP")
        if not isinstance(to_number, str) or not to_number.strip():
            raise validation("to_number is required for STOP")

    event = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "account_id": account_id,
        "campaign_id": campaign["id"],
        "message_id": message_id,
        "kind": kind,
        "keyword": keyword,
        "to_number": to_number,
        "status": "RECORDED",
    }
    store.FEEDBACK[event["id"]] = event

    # Apply in the same request.
    if kind == "STOP":
        consent = active_consent_for(campaign["brand_id"], to_number)
        if consent is not None:
            consent["status"] = "REVOKED"
            consent["revoked_at"] = store.now_iso()
            consent["revoked_by_keyword"] = keyword
    event["status"] = "APPLIED"
    return success_object(ser_feedback(event), 201)


@bp.get("/messaging/accounts/<account_id>/feedback_events")
def list_account_feedback(account_id):
    require_auth(FEEDBACK_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    limit, offset = pagination_params()
    items = [f for f in store.FEEDBACK.values() if f["account_id"] == account_id]
    items = _filter_feedback(items)
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_feedback(f) for f in page], limit, offset, total)


def _filter_feedback(items):
    campaign_filter = request.args.get("campaign_id")
    if campaign_filter:
        items = [f for f in items if f["campaign_id"] == campaign_filter]
    kind_filter = request.args.get("kind")
    if kind_filter:
        items = [f for f in items if f["kind"] == kind_filter]
    message_filter = request.args.get("message_id")
    if message_filter:
        items = [f for f in items if f.get("message_id") == message_filter]
    return items


@bp.get("/messaging/feedback_events/<feedback_id>")
def get_feedback_alias(feedback_id):
    require_auth(FEEDBACK_ROLES)
    event = find_or_404(store.FEEDBACK, feedback_id)
    return success_object(ser_feedback(event))


@bp.get("/messaging/feedback_events")
def list_feedback():
    require_auth(["PlatformAdmin", "ComplianceOfficer"])
    limit, offset = pagination_params()
    items = list(store.FEEDBACK.values())
    account_filter = request.args.get("account_id")
    if account_filter:
        items = [f for f in items if f["account_id"] == account_filter]
    items = _filter_feedback(items)
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_feedback(f) for f in page], limit, offset, total)
