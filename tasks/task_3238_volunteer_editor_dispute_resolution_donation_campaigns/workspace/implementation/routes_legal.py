"""Legal request routes."""
from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_TAKEDOWN_ARBITRATION_BLOCK)
from helpers import (base_entity, get_body, require_fields, list_response,
                     lookup, touch)
from middleware import require_roles
from response import success_object
from services import has_open_arbitration

bp = Blueprint("legal", __name__)

REQUEST_TYPES = {"TAKEDOWN", "USER_INFO", "SUBPOENA", "COURT_ORDER"}
TERMINAL = {"COMPLIED", "REJECTED", "PARTIALLY_COMPLIED"}


@bp.post("/wiki/legal-requests")
def create_legal_request():
    require_roles("LegalCounsel")
    body = get_body()
    require_fields(body, ["request_type", "requesting_party"])
    if body["request_type"] not in REQUEST_TYPES:
        raise ApiError(ERR_INVALID_REQUEST,
                       "request_type must be one of TAKEDOWN, USER_INFO, "
                       "SUBPOENA, COURT_ORDER", 400)
    target_page_id = body.get("target_page_id")
    target_user_id = body.get("target_user_id")
    if target_page_id is not None:
        lookup(db.pages, target_page_id, "Target page")
    if target_user_id is not None:
        lookup(db.editors, target_user_id, "Target user")
    lr = base_entity(has_version=False)
    lr.update({
        "request_type": body["request_type"],
        "target_page_id": target_page_id,
        "target_user_id": target_user_id,
        "requesting_party": body["requesting_party"],
        "received_at": db.now_iso(),
        "status": "RECEIVED",
        "transparency_report_id": None,
    })
    db.legal_requests[lr["id"]] = lr
    return success_object(lr, status=201)


@bp.get("/wiki/legal-requests")
def list_legal_requests():
    require_roles("LegalCounsel", "PlatformAdmin")
    return list_response(db.legal_requests, filters={
        "target_page_id": request.args.get("target_page_id"),
        "target_user_id": request.args.get("target_user_id"),
        "transparency_report_id": request.args.get("transparency_report_id"),
        "status": request.args.get("status"),
        "request_type": request.args.get("request_type"),
    })


@bp.get("/wiki/legal-requests/<requestId>")
def get_legal_request(requestId):
    require_roles("LegalCounsel")
    return success_object(lookup(db.legal_requests, requestId, "Legal request"))


@bp.post("/wiki/legal-requests/<requestId>/start-review")
def start_review(requestId):
    require_roles("LegalCounsel")
    lr = lookup(db.legal_requests, requestId, "Legal request")
    if lr["status"] != "RECEIVED":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a RECEIVED request can enter review", 409)
    lr["status"] = "UNDER_REVIEW"
    touch(lr, bump_version=False)
    return success_object(lr)


def _comply(requestId, status):
    require_roles("LegalCounsel")
    lr = lookup(db.legal_requests, requestId, "Legal request")
    if lr["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an UNDER_REVIEW request can be actioned", 409)
    if lr["request_type"] == "TAKEDOWN":
        if lr.get("target_page_id"):
            page = db.pages.get(lr["target_page_id"])
            if page is None:
                from errors import ERR_NOT_FOUND
                raise ApiError(ERR_NOT_FOUND, "Target page does not exist", 404)
            if has_open_arbitration(page["id"]):
                raise ApiError(
                    ERR_TAKEDOWN_ARBITRATION_BLOCK,
                    "Cannot comply with takedown while page has open "
                    "Arbitration dispute", 409)
    lr["status"] = status
    touch(lr, bump_version=False)
    if lr["request_type"] == "TAKEDOWN" and lr.get("target_page_id"):
        page = db.pages.get(lr["target_page_id"])
        if page is not None:
            page["protection_level"] = "FULL"
            touch(page)
    return success_object(lr)


@bp.post("/wiki/legal-requests/<requestId>/comply")
def comply(requestId):
    return _comply(requestId, "COMPLIED")


@bp.post("/wiki/legal-requests/<requestId>/partially-comply")
def partially_comply(requestId):
    return _comply(requestId, "PARTIALLY_COMPLIED")


@bp.post("/wiki/legal-requests/<requestId>/reject")
def reject(requestId):
    require_roles("LegalCounsel")
    lr = lookup(db.legal_requests, requestId, "Legal request")
    if lr["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an UNDER_REVIEW request can be rejected", 409)
    lr["status"] = "REJECTED"
    touch(lr, bump_version=False)
    return success_object(lr)
