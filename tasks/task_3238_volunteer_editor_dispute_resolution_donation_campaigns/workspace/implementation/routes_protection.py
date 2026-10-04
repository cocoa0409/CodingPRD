"""Protection request routes."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, _parse_iso
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE)
from helpers import (base_entity, get_body, require_fields, list_response,
                     lookup, touch, parse_datetime_field, iso)
from middleware import require_roles
from response import success_object
from services import has_open_arbitration

bp = Blueprint("protection", __name__)


@bp.post("/wiki/pages/<pageId>/protection-requests")
def create_protection_request(pageId):
    user_id, _role = require_roles("VolunteerEditor", "Administrator")
    page = lookup(db.pages, pageId, "Page")
    body = get_body()
    require_fields(body, ["requested_level", "reason"])
    if body["requested_level"] not in ("SEMI", "FULL"):
        raise ApiError(ERR_INVALID_REQUEST,
                       "requested_level must be SEMI or FULL", 400)
    pr = base_entity(has_version=False)
    pr.update({
        "page_id": page["id"],
        "requested_by_id": user_id,
        "requested_level": body["requested_level"],
        "reason": body["reason"],
        "status": "PENDING",
        "expires_at": None,
        "reviewed_by_id": None,
    })
    if body.get("expires_at"):
        pr["expires_at"] = iso(parse_datetime_field(body["expires_at"],
                                                    "expires_at"))
    db.protection_requests[pr["id"]] = pr
    return success_object(pr, status=201)


@bp.get("/wiki/protection-requests")
def list_protection_requests():
    require_roles("VolunteerEditor", "Administrator", "PlatformAdmin")
    from services import expire_protections
    expire_protections()
    return list_response(db.protection_requests, filters={
        "page_id": request.args.get("page_id"),
        "requested_by_id": request.args.get("requested_by_id"),
        "reviewed_by_id": request.args.get("reviewed_by_id"),
        "status": request.args.get("status"),
    })


@bp.get("/wiki/protection-requests/<requestId>")
def get_protection_request(requestId):
    require_roles("VolunteerEditor", "Administrator", "PlatformAdmin")
    from services import expire_protections
    expire_protections()
    return success_object(lookup(db.protection_requests, requestId,
                                 "Protection request"))


@bp.post("/wiki/protection-requests/<requestId>/approve")
def approve_protection_request(requestId):
    user_id, _role = require_roles("Administrator")
    pr = lookup(db.protection_requests, requestId, "Protection request")
    if pr["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a PENDING protection request can be approved", 409)
    page = lookup(db.pages, pr["page_id"], "Page")
    cutoff = db.now() - timedelta(days=7)
    flagged_recent = sum(
        1 for r in db.revisions.values()
        if r["page_id"] == page["id"] and r["status"] == "FLAGGED"
        and _parse_iso(r["updated_at"]) >= cutoff)
    if flagged_recent < 3 and not has_open_arbitration(page["id"]):
        raise ApiError(ERR_INVALID_STATE,
                       "Page needs at least 3 FLAGGED revisions in the last 7 "
                       "days or an open Arbitration dispute", 409)
    pr["status"] = "APPROVED"
    pr["reviewed_by_id"] = user_id
    pr["prior_protection_level"] = page["protection_level"]
    touch(pr, bump_version=False)
    page["protection_level"] = pr["requested_level"]
    touch(page)
    return success_object(pr)


@bp.post("/wiki/protection-requests/<requestId>/deny")
def deny_protection_request(requestId):
    user_id, _role = require_roles("Administrator")
    pr = lookup(db.protection_requests, requestId, "Protection request")
    if pr["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a PENDING protection request can be denied", 409)
    pr["status"] = "DENIED"
    pr["reviewed_by_id"] = user_id
    touch(pr, bump_version=False)
    return success_object(pr)
