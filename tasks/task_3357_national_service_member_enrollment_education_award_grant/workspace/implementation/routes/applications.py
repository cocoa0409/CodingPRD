from flask import Blueprint, request

import auth
import clock
import constants as C
import db
import domain
import util
from errors import ApiError
from serializers import serialize

bp = Blueprint("applications", __name__)

READ_ROLES = ["CNCSProgramOfficer", "ComplianceOfficer", "GranteeStaff"]


def _validate_slot_requests(value):
    if not isinstance(value, list) or not value:
        return None
    for entry in value:
        if not isinstance(entry, dict):
            return None
        if entry.get("term_category") not in C.TERM_CATEGORIES:
            return None
        if not util.is_int(entry.get("count")) or entry["count"] < 1:
            return None
    return value


def _validate_match_lines(value):
    if not isinstance(value, list):
        return None
    for entry in value:
        if not isinstance(entry, dict):
            return None
        if entry.get("category") not in C.MATCH_CATEGORIES:
            return None
        if not util.is_int(entry.get("amount_cents")) or entry["amount_cents"] < 0:
            return None
    return value


@bp.route("/competitions/<competitionId>/applications", methods=["POST"])
def create_application(competitionId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    body = util.body_json()
    organization_id = body.get("organization_id")
    # Tier 3 ownership: org self-service, organization_id must equal X-User-ID.
    if util.is_str(organization_id) and organization_id != uid:
        raise ApiError(
            "ERR_UNAUTHORIZED", 403, "organization_id must equal the caller identity"
        )
    auth.check_not_debarred(uid, role)
    competition = db.store.competitions.get(competitionId)
    if competition is None:
        raise ApiError("ERR_COMPETITION_NOT_FOUND", 404, "Competition not found")
    slot_requests = _validate_slot_requests(body.get("slot_requests"))
    match_lines = _validate_match_lines(body.get("match_lines"))
    federal = body.get("federal_share_requested_cents")
    if not util.is_str(organization_id) or not organization_id.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "organization_id is required")
    if not util.is_int(federal) or federal <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "federal_share_requested_cents must be an integer greater than zero",
        )
    if slot_requests is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "slot_requests must be a non-empty array of {term_category, count}",
        )
    if match_lines is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "match_lines must be an array of {category, amount_cents}",
        )
    allowable = domain.match_lines_total(match_lines)
    total_minutes = sum(
        entry["count"] * C.TERM_MINUTES[entry["term_category"]]
        for entry in slot_requests
    )
    application = db.new_entity(
        {
            "id": util.new_id(),
            "competition_id": competitionId,
            "organization_id": organization_id,
            "federal_share_requested_cents": federal,
            "slot_requests": slot_requests,
            "match_lines": match_lines,
            "allowable_match_commitment_cents": allowable,
            "total_term_minutes": total_minutes,
            "msy_requested": util.msy_3dp(total_minutes),
            "cost_per_msy_federal_cents": domain.cost_per_msy(federal, total_minutes),
            "cost_per_msy_total_cents": domain.cost_per_msy(
                federal + allowable, total_minutes
            ),
            "clarification_question": None,
            "clarification_response": None,
            "status": "DRAFT",
        }
    )
    db.store.applications[application["id"]] = application
    return util.ok(serialize(application), 201)


@bp.route("/applications", methods=["GET"])
def list_applications():
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    items = list(db.store.applications.values())
    if role == "GranteeStaff":
        items = [a for a in items if a["organization_id"] == uid]
    competition_id = request.args.get("competition_id")
    organization_id = request.args.get("organization_id")
    status = request.args.get("status")
    if competition_id is not None:
        items = [a for a in items if a["competition_id"] == competition_id]
    if organization_id is not None:
        items = [a for a in items if a["organization_id"] == organization_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return util.list_response(items, serialize)


@bp.route("/applications/<applicationId>", methods=["GET"])
def get_application(applicationId):
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    application = db.store.applications.get(applicationId)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "Application not found")
    auth.check_grantee_ownership(uid, role, application["organization_id"])
    return util.ok(serialize(application), 200)


@bp.route("/applications/<applicationId>/submit", methods=["POST"])
def submit_application(applicationId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    application = db.store.applications.get(applicationId)
    if application is not None:
        auth.check_grantee_ownership(uid, role, application["organization_id"])
    auth.check_not_debarred(uid, role)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "Application not found")
    if application["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not DRAFT")
    competition = db.store.competitions.get(application["competition_id"])
    now = clock.now()
    open_dt = clock.parse_datetime(competition["application_open_at"])
    close_dt = clock.parse_datetime(competition["application_close_at"])
    # Gate order (PRD 3.2): window, then cost-per-MSY cap, then match floor.
    if not (open_dt <= now <= close_dt):
        raise ApiError(
            "ERR_COMPETITION_WINDOW_CLOSED",
            422,
            "Submission is outside the application window",
        )
    federal_basis = util.federal_basis_cents(
        application["federal_share_requested_cents"],
        application["total_term_minutes"],
    )
    if federal_basis > C.COST_PER_MSY_CAP_CENTS:
        raise ApiError(
            "ERR_COST_PER_MSY_EXCEEDS_CAP",
            422,
            "Federal-basis cost per MSY exceeds the cap",
        )
    if (
        application["allowable_match_commitment_cents"] * C.MATCH_MIN_DENOMINATOR
        < application["federal_share_requested_cents"] * C.MATCH_MIN_NUMERATOR
    ):
        raise ApiError(
            "ERR_MATCH_BELOW_MINIMUM", 422, "Allowable match is below the 24% floor"
        )
    application["status"] = "UNDER_REVIEW"
    domain.touch(application)
    return util.ok(serialize(application), 200)


@bp.route("/applications/<applicationId>/request-clarification", methods=["POST"])
def request_clarification(applicationId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    application = db.store.applications.get(applicationId)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "Application not found")
    body = util.body_json()
    question = body.get("question")
    if not util.is_str(question):
        raise ApiError("ERR_INVALID_REQUEST", 400, "question is required")
    if application["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not UNDER_REVIEW")
    application["status"] = "CLARIFICATION_REQUESTED"
    application["clarification_question"] = question
    domain.touch(application)
    return util.ok(serialize(application), 200)


@bp.route("/applications/<applicationId>/respond-clarification", methods=["POST"])
def respond_clarification(applicationId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    application = db.store.applications.get(applicationId)
    if application is not None:
        auth.check_grantee_ownership(uid, role, application["organization_id"])
    auth.check_not_debarred(uid, role)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "Application not found")
    body = util.body_json()
    response = body.get("response")
    if not util.is_str(response):
        raise ApiError("ERR_INVALID_REQUEST", 400, "response is required")
    if application["status"] != "CLARIFICATION_REQUESTED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Application is not CLARIFICATION_REQUESTED"
        )
    application["status"] = "UNDER_REVIEW"
    application["clarification_response"] = response
    domain.touch(application)
    return util.ok(serialize(application), 200)


@bp.route("/applications/<applicationId>/award", methods=["POST"])
def award_application(applicationId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    application = db.store.applications.get(applicationId)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "Application not found")
    body = util.body_json()
    awarded = body.get("federal_share_awarded_cents")
    if not util.is_int(awarded) or awarded <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "federal_share_awarded_cents must be a positive integer",
        )
    if application["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not UNDER_REVIEW")
    competition = db.store.competitions.get(application["competition_id"])
    if competition["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Competition is not CLOSED")
    # PRD order: award-exceeds-request first, then the recomputed cost cap.
    if awarded > application["federal_share_requested_cents"]:
        raise ApiError(
            "ERR_AWARD_EXCEEDS_REQUEST",
            422,
            "Awarded federal share exceeds the requested amount",
        )
    federal_basis = util.federal_basis_cents(awarded, application["total_term_minutes"])
    if federal_basis > C.COST_PER_MSY_CAP_CENTS:
        raise ApiError(
            "ERR_COST_PER_MSY_EXCEEDS_CAP",
            422,
            "Federal-basis cost per MSY on the awarded amount exceeds the cap",
        )
    application["status"] = "AWARDED"
    domain.touch(application)
    total_minutes = application["total_term_minutes"]
    slot_count = sum(e["count"] for e in application["slot_requests"])
    award = db.new_entity(
        {
            "id": util.new_id(),
            "application_id": application["id"],
            "organization_id": application["organization_id"],
            "competition_id": application["competition_id"],
            "federal_share_awarded_cents": awarded,
            "total_term_minutes": total_minutes,
            "awarded_slot_count": slot_count,
            "cost_per_msy_awarded_cents": domain.cost_per_msy(awarded, total_minutes),
            "allowable_match_cents": 0,
            "suspension_reason": None,
            "status": "ACTIVE",
        }
    )
    db.store.awards[award["id"]] = award
    slot_index = 0
    for entry in application["slot_requests"]:
        for _ in range(entry["count"]):
            slot_index += 1
            slot = db.new_entity(
                {
                    "id": util.new_id(),
                    "award_id": award["id"],
                    "term_category": entry["term_category"],
                    "slot_index": slot_index,
                    "fill_count": 0,
                    "status": "OPEN",
                }
            )
            db.store.slots[slot["id"]] = slot
    domain.competition_bubble(competition)
    return util.ok(serialize(award), 201)


@bp.route("/applications/<applicationId>/reject", methods=["POST"])
def reject_application(applicationId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    application = db.store.applications.get(applicationId)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "Application not found")
    body = util.body_json()
    if not util.is_str(body.get("reason")):
        raise ApiError("ERR_INVALID_REQUEST", 400, "reason is required")
    if application["status"] not in ("UNDER_REVIEW", "CLARIFICATION_REQUESTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Application is not UNDER_REVIEW or CLARIFICATION_REQUESTED",
        )
    application["status"] = "REJECTED"
    domain.touch(application)
    competition = db.store.competitions.get(application["competition_id"])
    if competition is not None:
        domain.competition_bubble(competition)
    return util.ok(serialize(application), 200)
