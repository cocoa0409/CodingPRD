"""Routes: identity requests (media/subpoena/law-enforcement pipeline)."""
from datetime import timedelta
from flask import Blueprint, request

from db import store, fmt_ts
from errors import not_found, err
from middleware import require_roles
from response import ok, ok_list, paginate
from services import (
    stamp_common, touch, get_body, req_str, req_enum, pub,
    NOTICE_PERIOD_D,
)

bp = Blueprint("identity", __name__)

IR_ROLES = ("PlatformOps", "LegalOps")
CHANNELS = ("MEDIA", "LEGAL_SUBPOENA", "LAW_ENFORCEMENT")


def get_request(request_id):
    r = store.identity_requests.get(request_id)
    if r is None:
        raise not_found("identity request not found")
    return r


@bp.post("/platform/identity-requests")
@require_roles("LegalOps")
def create_request(_actor_id, _actor_role):
    body = get_body()
    subject_user_id = req_str(body, "subject_user_id")
    requester_label = req_str(body, "requester_label")
    channel = req_enum(body, "channel", CHANNELS)
    ref = body.get("legal_process_ref")
    if subject_user_id not in store.users:
        raise not_found("subject user not found")
    if channel == "MEDIA":
        raise err("ERR_MEDIA_REQUEST_REFUSED",
                  "media requests are refused at intake")
    if not isinstance(ref, str) or not ref:
        raise err("ERR_MEDIA_REQUEST_REFUSED",
                  "legal_process_ref is required for legal channels")
    ireq = stamp_common({
        "subject_user_id": subject_user_id,
        "requester_label": requester_label,
        "channel": channel,
        "legal_process_ref": ref,
        "notice_sent_at": None,
        "notice_deadline": None,
        "status": "RECEIVED",
    })
    store.identity_requests[ireq["id"]] = ireq
    return ok(pub(ireq), status=201)


@bp.get("/platform/identity-requests")
@require_roles(*IR_ROLES)
def list_requests(_actor_id, _actor_role):
    items = list(store.identity_requests.values())
    v = request.args.get("subject_user_id")
    if v is not None:
        items = [r for r in items if r["subject_user_id"] == v]
    items, limit, offset, total = paginate([pub(r) for r in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/users/<userId>/identity-requests")
@require_roles(*IR_ROLES)
def list_user_requests(userId, _actor_id, _actor_role):
    if userId not in store.users:
        raise not_found("user not found")
    items = [pub(r) for r in store.identity_requests.values()
             if r["subject_user_id"] == userId]
    items, limit, offset, total = paginate(items, request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/identity-requests/<requestId>")
@require_roles(*IR_ROLES)
def get_one_request(requestId, _actor_id, _actor_role):
    return ok(pub(get_request(requestId)))


@bp.post("/platform/identity-requests/<requestId>/start-review")
@require_roles("LegalOps")
def start_review(requestId, _actor_id, _actor_role):
    ireq = get_request(requestId)
    if ireq["status"] != "RECEIVED":
        raise err("ERR_INVALID_STATE", "request is not RECEIVED")
    ireq["status"] = "UNDER_REVIEW"
    touch(ireq)
    return ok(pub(ireq))


@bp.post("/platform/identity-requests/<requestId>/send-notice")
@require_roles("LegalOps")
def send_notice(requestId, _actor_id, _actor_role):
    ireq = get_request(requestId)
    if ireq["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "request is not UNDER_REVIEW")
    if ireq["channel"] != "LEGAL_SUBPOENA":
        raise err("ERR_INVALID_STATE",
                  "notice is only applicable to LEGAL_SUBPOENA requests")
    deadline = store.now + timedelta(days=NOTICE_PERIOD_D)
    ireq["notice_sent_at"] = fmt_ts(store.now)
    ireq["notice_deadline"] = fmt_ts(deadline)
    ireq["_notice_deadline_dt"] = deadline
    ireq["status"] = "NOTICE_SENT"
    touch(ireq)
    return ok(pub(ireq))


@bp.post("/platform/identity-requests/<requestId>/release")
@require_roles("LegalOps")
def release(requestId, _actor_id, _actor_role):
    ireq = get_request(requestId)
    if ireq["channel"] == "LAW_ENFORCEMENT":
        if ireq["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE",
                      "law-enforcement release requires UNDER_REVIEW")
    elif ireq["channel"] == "LEGAL_SUBPOENA":
        if ireq["status"] != "NOTICE_SENT":
            raise err("ERR_INVALID_STATE",
                      "subpoena release requires NOTICE_SENT")
        if store.now < ireq["_notice_deadline_dt"]:
            raise err("ERR_NOTICE_PERIOD_ACTIVE",
                      "notice period has not elapsed")
    else:
        raise err("ERR_INVALID_STATE", "request cannot be released")
    ireq["status"] = "RELEASED"
    touch(ireq)
    return ok(pub(ireq))


@bp.post("/platform/identity-requests/<requestId>/decline")
@require_roles("LegalOps")
def decline(requestId, _actor_id, _actor_role):
    ireq = get_request(requestId)
    if ireq["status"] not in ("RECEIVED", "UNDER_REVIEW", "NOTICE_SENT"):
        raise err("ERR_INVALID_STATE", "request cannot be declined")
    ireq["status"] = "DECLINED"
    touch(ireq)
    return ok(pub(ireq))


@bp.post("/platform/identity-requests/<requestId>/withdraw")
@require_roles("LegalOps")
def withdraw(requestId, _actor_id, _actor_role):
    ireq = get_request(requestId)
    if ireq["status"] not in ("RECEIVED", "UNDER_REVIEW"):
        raise err("ERR_INVALID_STATE", "request cannot be withdrawn")
    ireq["status"] = "WITHDRAWN"
    touch(ireq)
    return ok(pub(ireq))
