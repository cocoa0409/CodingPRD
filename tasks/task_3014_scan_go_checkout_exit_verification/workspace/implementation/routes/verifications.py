"""Exit verification endpoints."""

from flask import Blueprint, request

from db import STORE, new_entity, touch
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_LP_CASE_NOT_OPEN,
    ERR_VERIFICATION_METHOD_NOT_ENABLED,
    ERR_VERIFICATION_NOT_MISMATCHED,
    ERR_VERIFICATION_NOT_PENDING,
)
from logic import (
    get_session,
    get_verification,
    is_int,
    open_lp_case,
    serialize,
    sort_items,
)
from middleware import get_context, get_body, require_role, require_fields, get_pagination, paginate
from response import success

bp = Blueprint("verifications", __name__)


@bp.get("/scan-sessions/<session_id>/exit-verifications")
def list_session_verifications(session_id):
    get_context()
    session = get_session(session_id)
    limit, offset = get_pagination(request.args)
    verifications = [v for v in STORE.exit_verifications.values()
                     if v["session_id"] == session["id"]]
    f = request.args.get("status")
    if f is not None:
        verifications = [v for v in verifications if v["status"] == f]
    verifications = sort_items(verifications)
    page, page_meta = paginate(verifications, limit, offset)
    return success([serialize(v) for v in page], response_type="array", pagination=page_meta)


@bp.get("/exit-verifications/<verification_id>")
def get_verification_route(verification_id):
    get_context()
    return success(serialize(get_verification(verification_id)))


@bp.get("/exit-verifications")
def list_verifications():
    get_context()
    limit, offset = get_pagination(request.args)
    verifications = list(STORE.exit_verifications.values())
    for f in ("session_id", "club_id", "status"):
        v = request.args.get(f)
        if v is not None:
            verifications = [x for x in verifications if x[f] == v]
    verifications = sort_items(verifications)
    page, page_meta = paginate(verifications, limit, offset)
    return success([serialize(v) for v in page], response_type="array", pagination=page_meta)


def _mismatch(verification, session, source, unscanned_count, flagger):
    verification["status"] = "MISMATCH"
    verification["flagging_associate_id"] = flagger
    touch(verification)
    session["status"] = "FLAGGED"
    touch(session)
    open_lp_case(session, source, unscanned_count, flagger)


def _verified(verification, session):
    verification["status"] = "VERIFIED"
    touch(verification)
    session["status"] = "EXITED"
    touch(session)


@bp.post("/exit-verifications/<verification_id>/verify-receipt")
def verify_receipt(verification_id):
    user_id, role = get_context()
    require_role(role, ["Associate"])
    verification = get_verification(verification_id)
    body = get_body()
    require_fields(body, ["receipt_code"])
    if verification["status"] != "PENDING":
        raise ApiError(ERR_VERIFICATION_NOT_PENDING,
                       "verify-receipt requires a PENDING verification.", 409)
    if verification["method"] != "RECEIPT_CODE":
        raise ApiError(ERR_VERIFICATION_METHOD_NOT_ENABLED,
                       "verify-receipt requires a RECEIPT_CODE verification.", 409)
    session = STORE.sessions[verification["session_id"]]
    if body["receipt_code"] == session["receipt_code"]:
        _verified(verification, session)
    else:
        _mismatch(verification, session, "CV_MISMATCH", 0, user_id)
    return success(serialize(verification))


@bp.post("/exit-verifications/<verification_id>/cv-report")
def cv_report(verification_id):
    user_id, role = get_context()
    require_role(role, ["Associate"])
    verification = get_verification(verification_id)
    body = get_body()
    require_fields(body, ["observed_item_count"])
    observed = body["observed_item_count"]
    if not is_int(observed) or observed < 0:
        raise ApiError(ERR_INVALID_REQUEST,
                       "observed_item_count must be an integer >= 0.", 400)
    if verification["status"] != "PENDING":
        raise ApiError(ERR_VERIFICATION_NOT_PENDING,
                       "cv-report requires a PENDING verification.", 409)
    if verification["method"] != "CV_ARCH":
        raise ApiError(ERR_VERIFICATION_METHOD_NOT_ENABLED,
                       "cv-report requires a CV_ARCH verification.", 409)
    verification["cv_observed_item_count"] = observed
    session = STORE.sessions[verification["session_id"]]
    club = STORE.clubs[verification["club_id"]]
    unscanned = observed - verification["expected_item_count"]
    if unscanned >= club["lp_unscanned_threshold"]:
        _mismatch(verification, session, "CV_MISMATCH", unscanned, user_id)
    else:
        _verified(verification, session)
    return success(serialize(verification))


@bp.post("/exit-verifications/<verification_id>/resolve-mismatch")
def resolve_mismatch(verification_id):
    _, role = get_context()
    require_role(role, ["Associate"])
    verification = get_verification(verification_id)
    body = get_body()
    require_fields(body, ["action"])
    action = body["action"]
    if action not in ("CLEAR", "CONFIRM", "RESCAN"):
        raise ApiError(ERR_INVALID_REQUEST,
                       "action must be CLEAR, CONFIRM, or RESCAN.", 400)
    if verification["status"] != "MISMATCH":
        raise ApiError(ERR_VERIFICATION_NOT_MISMATCHED,
                       "resolve-mismatch requires a MISMATCH verification.", 409)
    session = STORE.sessions[verification["session_id"]]

    if action == "RESCAN":
        new_v = new_entity()
        new_v.update({
            "session_id": session["id"],
            "club_id": session["club_id"],
            "method": verification["method"],
            "status": "PENDING",
            "expected_item_count": session["scanned_item_count"],
            "cv_observed_item_count": None,
            "flagging_associate_id": None,
        })
        STORE.exit_verifications[new_v["id"]] = new_v
        session["status"] = "EXIT_PENDING"
        touch(session)
        return success(serialize(new_v))

    if action == "CLEAR":
        for case in STORE.lp_cases.values():
            if case["session_id"] == session["id"] and case["status"] != "RESOLVED":
                raise ApiError(ERR_LP_CASE_NOT_OPEN,
                               "An unresolved loss-prevention case blocks the clear.", 409)
        verification["status"] = "VERIFIED"
        touch(verification)
        session["status"] = "EXITED"
        touch(session)
        return success(serialize(verification))

    # CONFIRM
    verification["status"] = "CONFIRMED"
    touch(verification)
    # Session stays FLAGGED awaiting LP resolution and/or void-payment.
    touch(session)
    return success(serialize(verification))
