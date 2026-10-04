"""Webhook delivery + recipient webhook listing."""

from flask import Blueprint, request

import db
from middleware import require_role, parse_limit_offset
from response import success_object, success_list
from errors import err, ERR_NOT_FOUND, ERR_UNAUTHORIZED
from services.serializers import webhook_out

bp = Blueprint("webhooks", __name__)


@bp.route("/webhook_events/<webhookEventId>/deliver", methods=["POST"])
def deliver_webhook(webhookEventId):
    user_id, role = require_role("Recipient")
    w = db.webhook_events.get(webhookEventId)
    if w is None:
        raise err(ERR_NOT_FOUND, "WebhookEvent not found")
    # ownership: the acting Recipient must be the delivery target
    if w["recipient_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "X-User-ID must equal the webhook recipient_id")
    w["delivered_at"] = db.now_iso()
    w["delivery_attempts"] += 1
    return success_object(webhook_out(w))


@bp.route("/recipients/<recipientId>/webhook_events", methods=["GET"])
def list_recipient_webhooks(recipientId):
    require_role("PlatformAdmin", "ComplianceReviewer", "Recipient")
    r = db.recipients.get(recipientId)
    if r is None:
        raise err(ERR_NOT_FOUND, "Recipient not found")
    limit, offset = parse_limit_offset(request.args)
    et = request.args.get("event_type")
    items = [w for w in db.webhook_events.values() if w["recipient_id"] == r["id"]]
    if et:
        items = [w for w in items if w["event_type"] == et]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([webhook_out(w) for w in page], limit, offset, total)
