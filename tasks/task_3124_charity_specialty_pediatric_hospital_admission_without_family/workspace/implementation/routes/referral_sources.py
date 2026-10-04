"""ReferralSource endpoints (PRD §3.2)."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_REFERRAL_SOURCE_NOT_FOUND
from helpers import get_body, new_id, now_iso, req_enum, req_str
from middleware import require_auth
from response import success_list, success_object, paginate
from views import referral_source_view

bp = Blueprint("referral_sources", __name__)

SOURCE_TYPES = {"COMMUNITY_PHYSICIAN", "OUTREACH_CLINIC", "INTERNATIONAL_PARTNER"}

ALL_ROLES = ["NetworkAdmin", "IntakeCoordinator", "ReviewCommitteeMember",
             "BillingSpecialist", "CareCoordinator", "OutreachPlanner",
             "PhilanthropyOfficer", "ReferringPhysician"]


def get_source_or_404(source_id):
    r = db.referral_sources.get(source_id)
    if r is None:
        raise ApiError(ERR_REFERRAL_SOURCE_NOT_FOUND, 404, "Referral source id does not exist")
    return r


@bp.post("/referral-sources")
def create_source():
    require_auth(["NetworkAdmin", "IntakeCoordinator"])
    body = get_body()
    source_type = req_enum(body, "source_type", SOURCE_TYPES)
    display_name = req_str(body, "display_name")
    contact_email = req_str(body, "contact_email")
    country_code = req_str(body, "country_code")
    now = now_iso()
    r = {
        "id": new_id(),
        "source_type": source_type,
        "display_name": display_name,
        "contact_email": contact_email,
        "country_code": country_code,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.referral_sources[r["id"]] = r
    return success_object(referral_source_view(r), 201)


@bp.get("/referral-sources")
def list_sources():
    require_auth(ALL_ROLES)
    items = list(db.referral_sources.values())
    source_type = request.args.get("source_type")
    if source_type:
        items = [r for r in items if r["source_type"] == source_type]
    country_code = request.args.get("country_code")
    if country_code:
        items = [r for r in items if r["country_code"] == country_code]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([referral_source_view(r) for r in page], total, limit, offset)


@bp.get("/referral-sources/<sourceId>")
def get_source(sourceId):
    require_auth(ALL_ROLES)
    r = get_source_or_404(sourceId)
    return success_object(referral_source_view(r))
