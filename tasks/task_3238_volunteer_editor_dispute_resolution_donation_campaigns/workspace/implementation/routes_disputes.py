"""Dispute routes: open, escalate, resolve, close."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, _parse_iso
from errors import (ApiError, ERR_DISPUTE_ALREADY_OPEN,
                    ERR_ESCALATION_TOO_SOON, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_UNAUTHORIZED)
from helpers import (base_entity, get_body, require_fields, list_response,
                     lookup, touch, check_occ)
from middleware import require_roles
from response import success_object
from services import recompute_dispute_level

bp = Blueprint("disputes", __name__)

DISPUTE_TYPES = {"CONTENT", "CONDUCT", "SOURCING", "NOTABILITY"}
LEVEL_ADVANCE = {"TALK": "NOTICE", "NOTICE": "ARBITRATION"}


@bp.post("/wiki/pages/<pageId>/disputes")
def create_dispute(pageId):
    user_id, _role = require_roles("VolunteerEditor")
    page = lookup(db.pages, pageId, "Page")
    body = get_body()
    require_fields(body, ["respondent_id", "subject_revision_id", "dispute_type"])
    if body["dispute_type"] not in DISPUTE_TYPES:
        raise ApiError(ERR_INVALID_REQUEST,
                       "dispute_type must be one of CONTENT, CONDUCT, "
                       "SOURCING, NOTABILITY", 400)
    respondent = lookup(db.editors, body["respondent_id"], "Respondent editor")
    revision = lookup(db.revisions, body["subject_revision_id"],
                      "Subject revision")
    if revision["page_id"] != page["id"]:
        from errors import ERR_NOT_FOUND
        raise ApiError(ERR_NOT_FOUND,
                       "Subject revision does not belong to this page", 404)
    # A page may not have two open disputes at the same level (TALK here).
    for d in db.disputes.values():
        if (d["page_id"] == page["id"] and d["level"] == "TALK"
                and d["status"] in ("OPEN", "ESCALATED")):
            raise ApiError(ERR_DISPUTE_ALREADY_OPEN,
                           "Page already has an open dispute at this level", 409)
    dispute = base_entity()
    dispute.update({
        "page_id": page["id"],
        "initiator_id": user_id,
        "respondent_id": respondent["id"],
        "subject_revision_id": revision["id"],
        "dispute_type": body["dispute_type"],
        "level": "TALK",
        "status": "OPEN",
        "opened_at": db.now_iso(),
        "escalated_at": None,
        "resolution_notes": None,
    })
    db.disputes[dispute["id"]] = dispute
    recompute_dispute_level(page)
    touch(page)
    return success_object(dispute, status=201)


@bp.get("/wiki/disputes")
def list_disputes():
    require_roles("VolunteerEditor", "Administrator", "LegalCounsel",
                  "PlatformAdmin")
    return list_response(db.disputes, filters={
        "page_id": request.args.get("page_id"),
        "initiator_id": request.args.get("initiator_id"),
        "respondent_id": request.args.get("respondent_id"),
        "subject_revision_id": request.args.get("subject_revision_id"),
        "status": request.args.get("status"),
        "level": request.args.get("level"),
    })


@bp.get("/wiki/disputes/<disputeId>")
def get_dispute(disputeId):
    require_roles("VolunteerEditor", "Administrator", "LegalCounsel")
    return success_object(lookup(db.disputes, disputeId, "Dispute"))


@bp.post("/wiki/disputes/<disputeId>/escalate")
def escalate_dispute(disputeId):
    user_id, role = require_roles("VolunteerEditor", "Administrator")
    dispute = lookup(db.disputes, disputeId, "Dispute")
    if dispute["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an OPEN dispute can be escalated", 409)
    if role == "VolunteerEditor" and user_id not in (
            dispute["initiator_id"], dispute["respondent_id"]):
        raise ApiError(ERR_UNAUTHORIZED,
                       "Only the initiator, respondent, or an Administrator "
                       "may escalate", 403)
    if dispute["level"] not in LEVEL_ADVANCE:
        raise ApiError(ERR_INVALID_STATE,
                       "Dispute already at ARBITRATION level", 409)
    body = get_body()
    check_occ(body, "expected_dispute_version", dispute)
    anchor = dispute["escalated_at"] or dispute["opened_at"]
    if db.now() - _parse_iso(anchor) < timedelta(hours=72):
        raise ApiError(ERR_ESCALATION_TOO_SOON,
                       "Less than 72 hours since last dispute escalation", 409)
    dispute["level"] = LEVEL_ADVANCE[dispute["level"]]
    dispute["escalated_at"] = db.now_iso()
    touch(dispute)
    page = db.pages.get(dispute["page_id"])
    if page is not None:
        if dispute["level"] == "ARBITRATION":
            page["dispute_level"] = "ARB"
            page["protection_level"] = "FULL"
        else:
            recompute_dispute_level(page)
        touch(page)
    return success_object(dispute)


@bp.post("/wiki/disputes/<disputeId>/resolve")
def resolve_dispute(disputeId):
    require_roles("Administrator")
    dispute = lookup(db.disputes, disputeId, "Dispute")
    if dispute["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an OPEN dispute can be resolved", 409)
    body = get_body()
    require_fields(body, ["resolution_notes"])
    dispute["status"] = "RESOLVED"
    dispute["resolution_notes"] = body["resolution_notes"]
    touch(dispute)
    page = db.pages.get(dispute["page_id"])
    if page is not None:
        recompute_dispute_level(page)
        touch(page)
    return success_object(dispute)


@bp.post("/wiki/disputes/<disputeId>/close")
def close_dispute(disputeId):
    require_roles("Administrator")
    dispute = lookup(db.disputes, disputeId, "Dispute")
    if dispute["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an OPEN dispute can be closed", 409)
    initiator = db.editors.get(dispute["initiator_id"])
    if initiator is None or initiator["account_status"] != "BLOCKED":
        raise ApiError(ERR_INVALID_STATE,
                       "Dispute can only be closed when the initiator account "
                       "is BLOCKED or withdrawn", 409)
    dispute["status"] = "CLOSED"
    touch(dispute)
    page = db.pages.get(dispute["page_id"])
    if page is not None:
        recompute_dispute_level(page)
        touch(page)
    return success_object(dispute)
