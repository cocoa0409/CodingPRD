"""Restricted intercept endpoints."""

from flask import Blueprint, request

from db import STORE, touch
from errors import (
    ApiError,
    ERR_AGE_VERIFICATION_FAILED,
    ERR_INTERCEPT_NOT_PENDING,
    ERR_INVALID_REQUEST,
)
from logic import (
    deny_intercept,
    get_intercept,
    get_session,
    recompute_session,
    reopen_session_if_clear,
    serialize,
    sort_items,
)
from middleware import get_context, get_body, require_role, require_fields, get_pagination, paginate
from response import success

bp = Blueprint("intercepts", __name__)


@bp.get("/scan-sessions/<session_id>/intercepts")
def list_session_intercepts(session_id):
    get_context()
    session = get_session(session_id)
    limit, offset = get_pagination(request.args)
    intercepts = [i for i in STORE.intercepts.values() if i["session_id"] == session["id"]]
    v = request.args.get("status")
    if v is not None:
        intercepts = [i for i in intercepts if i["status"] == v]
    intercepts = sort_items(intercepts)
    page, page_meta = paginate(intercepts, limit, offset)
    return success([serialize(i) for i in page], response_type="array", pagination=page_meta)


@bp.get("/intercepts/<intercept_id>")
def get_intercept_route(intercept_id):
    get_context()
    return success(serialize(get_intercept(intercept_id)))


@bp.get("/intercepts")
def list_intercepts():
    get_context()
    limit, offset = get_pagination(request.args)
    intercepts = list(STORE.intercepts.values())
    for f in ("session_id", "scan_line_id", "club_id", "status"):
        v = request.args.get(f)
        if v is not None:
            intercepts = [i for i in intercepts if i[f] == v]
    intercepts = sort_items(intercepts)
    page, page_meta = paginate(intercepts, limit, offset)
    return success([serialize(i) for i in page], response_type="array", pagination=page_meta)


@bp.post("/intercepts/<intercept_id>/resolve")
def resolve_intercept(intercept_id):
    user_id, role = get_context()
    require_role(role, ["Associate"])
    intercept = get_intercept(intercept_id)
    body = get_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("APPROVE", "DENY"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be APPROVE or DENY.", 400)
    if intercept["status"] != "PENDING":
        raise ApiError(ERR_INTERCEPT_NOT_PENDING,
                       "Resolve attempted on a non-PENDING intercept.", 409)

    session = STORE.sessions[intercept["session_id"]]
    member = STORE.members[session["member_id"]]
    line = STORE.scan_lines[intercept["scan_line_id"]]

    if decision == "APPROVE":
        if intercept["restricted_class"] in ("ALCOHOL", "TOBACCO"):
            verified = body.get("birth_year_verified")
            age = STORE.now().year - member["birth_year"]
            if verified is not True or age < 21:
                raise ApiError(ERR_AGE_VERIFICATION_FAILED,
                               "Age verification failed for ALCOHOL/TOBACCO approval.", 403)
        elif intercept["restricted_class"] == "PHARMACY":
            note = body.get("pharmacist_note")
            if not isinstance(note, str) or not note:
                raise ApiError(ERR_INVALID_REQUEST,
                               "pharmacist_note is required for PHARMACY approval.", 400)
        intercept["status"] = "APPROVED"
        intercept["decision"] = "APPROVE"
        intercept["associate_id"] = user_id
        touch(intercept)
        line["status"] = "CLEARED"
        touch(line)
        recompute_session(session)
        reopen_session_if_clear(session)
        touch(session)
    else:  # DENY
        intercept["decision"] = "DENY"
        intercept["associate_id"] = user_id
        deny_intercept(intercept, "DENIED")

    return success(serialize(intercept))
