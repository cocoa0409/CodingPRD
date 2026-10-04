"""Withdrawal notice endpoints (PRD 3.9): draft, list, publish.
Enforcement happens on the clock sweep at effective_on."""
from datetime import timedelta

from flask import Blueprint

import clock
import db
from constants import NOTICE_PERIOD_DAYS, ROLE_COMPLIANCE, WITHDRAWAL_REASON_CODES
from errors import (
    ApiError, ERR_ALREADY_TERMINAL, ERR_INVALID_STATE, ERR_NOT_FOUND,
)
from middleware import any_authenticated, require_roles
from response import paginated_list, success
from routes.certifications import get_certification_or_404
from validation import body, req_enum, req_str

bp = Blueprint("withdrawals", __name__)


@bp.post("/certifications/<certification_id>/withdrawal-notices")
@require_roles(ROLE_COMPLIANCE)
def create_withdrawal_notice(certification_id, user_id, role):
    get_certification_or_404(certification_id)
    payload = body(required=True)
    notice = db.new_entity(db.withdrawal_notices, {
        "certification_id": certification_id,
        "reason_code": req_enum(payload, "reason_code", WITHDRAWAL_REASON_CODES),
        "public_text": req_str(payload, "public_text"),
        "published_on": None,
        "effective_on": None,
        "status": "DRAFT",
    })
    return success(notice, status=201)


@bp.get("/certifications/<certification_id>/withdrawal-notices")
@any_authenticated
def list_withdrawal_notices(certification_id, user_id, role):
    get_certification_or_404(certification_id)
    items = [n for n in db.sorted_items(db.withdrawal_notices)
             if n["certification_id"] == certification_id]
    page, pagination = paginated_list(items)
    return success(page, pagination=pagination)


@bp.post("/withdrawal-notices/<notice_id>/publish")
@require_roles(ROLE_COMPLIANCE)
def publish_withdrawal_notice(notice_id, user_id, role):
    notice = db.withdrawal_notices.get(notice_id)
    if notice is None:
        raise ApiError(ERR_NOT_FOUND, "withdrawal notice not found")

    if notice["status"] == "EFFECTIVE":
        raise ApiError(ERR_ALREADY_TERMINAL, "notice is EFFECTIVE (terminal)")
    if notice["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "notice is %s, not DRAFT"
                       % notice["status"])

    cert = db.certifications[notice["certification_id"]]
    if cert["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE,
                       "certification is %s; notice cannot be published"
                       % cert["status"])

    notice["published_on"] = clock.now()
    notice["effective_on"] = clock.now() + timedelta(days=NOTICE_PERIOD_DAYS)
    notice["status"] = "PUBLISHED"
    db.mutate(notice)
    return success(notice)
