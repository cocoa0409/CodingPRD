# routes/notices.py — hearing-notice service records.
import uuid

from flask import Blueprint

import db
from auth import get_auth, require_role
from computed import serialize_notice
from constants import (ROLE_COURT_ADMINISTRATOR, SERVICE_METHODS,
                       NOTICE_SERVED, NOTICE_DEFECTIVE)
from envelope import success
from errors import ApiError
from inputs import get_body, req_str, req_enum, fk, invalid
from timeutil import parse_iso

bp = Blueprint("notices", __name__)


@bp.post("/notices")
def create_notice():
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    body = get_body()
    # tier 3
    hearing_id = fk(body, "hearing_id")
    hearing = db.hearings.get(hearing_id) if hearing_id is not None else None
    if hearing_id is not None and hearing is None:
        raise ApiError("ERR_HEARING_NOT_FOUND", "Hearing id does not exist")
    # tier 9: at most one notice per hearing
    if hearing is not None and any(n for n in db.notices.values()
                                   if n["hearing_id"] == hearing["id"]):
        raise ApiError("ERR_NOTICE_ALREADY_RECORDED",
                       "A HearingNotice already exists for the hearing")
    # tier 10: shape (served_at must parse and must not be later than the
    # current clock; PRD §3.4 states the rule without a dedicated error id,
    # so the generic input-shape error carries it)
    hearing_id = req_str(body, "hearing_id")
    if hearing_id not in db.hearings:
        raise ApiError("ERR_HEARING_NOT_FOUND", "Hearing id does not exist")
    service_method = req_enum(body, "service_method", SERVICE_METHODS)
    served_raw = body.get("served_at")
    served_at = parse_iso(served_raw)
    if served_at is None:
        invalid("field 'served_at' is required and must be an ISO 8601 "
                "timestamp")
    if served_at > db.get_clock():
        invalid("field 'served_at' must not be later than the current clock")
    n = {
        "id": str(uuid.uuid4()),
        "hearing_id": hearing_id,
        "service_method": service_method,
        "served_at": served_at,
        "status": NOTICE_SERVED,
    }
    db.stamp_new(n)
    db.stamp_common(n)
    db.notices[n["id"]] = n
    return success(serialize_notice(n), response_type="object", status=201)


@bp.post("/notices/<noticeId>/mark-defective")
def mark_defective(noticeId):
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    n = db.notices.get(noticeId)
    if n is None:
        raise ApiError("ERR_NOTICE_NOT_FOUND",
                       "HearingNotice id does not exist")
    # tier 5: only a SERVED notice can be marked defective
    if n["status"] == NOTICE_DEFECTIVE:
        raise ApiError("ERR_NOTICE_ALREADY_DEFECTIVE",
                       "Notice is already DEFECTIVE")
    n["status"] = NOTICE_DEFECTIVE
    db.touch(n)
    return success(serialize_notice(n), response_type="object", status=200)
