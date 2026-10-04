from flask import Blueprint, request

import auth
import constants as C
import db
import domain
import util
from errors import ApiError
from serializers import serialize

bp = Blueprint("awards", __name__)

READ_ROLES = ["CNCSProgramOfficer", "ComplianceOfficer", "GranteeStaff"]


def _load_award_or_404(awardId):
    award = db.store.awards.get(awardId)
    if award is None:
        raise ApiError("ERR_AWARD_NOT_FOUND", 404, "Award not found")
    return award


def _validate_report_lines(value):
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


@bp.route("/awards", methods=["GET"])
def list_awards():
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    items = list(db.store.awards.values())
    if role == "GranteeStaff":
        items = [a for a in items if a["organization_id"] == uid]
    application_id = request.args.get("application_id")
    organization_id = request.args.get("organization_id")
    status = request.args.get("status")
    if application_id is not None:
        items = [a for a in items if a["application_id"] == application_id]
    if organization_id is not None:
        items = [a for a in items if a["organization_id"] == organization_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return util.list_response(items, serialize)


@bp.route("/awards/<awardId>", methods=["GET"])
def get_award(awardId):
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    award = _load_award_or_404(awardId)
    auth.check_grantee_ownership(uid, role, award["organization_id"])
    return util.ok(serialize(award), 200)


@bp.route("/awards/<awardId>/suspend", methods=["POST"])
def suspend_award(awardId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    award = _load_award_or_404(awardId)
    if award["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Award is not ACTIVE")
    body = util.body_json()
    reason = body.get("reason")
    if not util.is_str(reason) or not reason:
        reason = C.ESCALATION_REASON
    domain.suspend_award(award, reason)
    return util.ok(serialize(award), 200)


@bp.route("/awards/<awardId>/reinstate", methods=["POST"])
def reinstate_award(awardId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    award = _load_award_or_404(awardId)
    if award["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Award is not SUSPENDED")
    for finding in db.store.findings.values():
        if finding["award_id"] == awardId and finding["status"] == "ESCALATED":
            raise ApiError(
                "ERR_FINDINGS_ESCALATED",
                409,
                "Award has ESCALATED findings and cannot be reinstated",
            )
    domain.reinstate_award(award)
    return util.ok(serialize(award), 200)


@bp.route("/awards/<awardId>/close", methods=["POST"])
def close_award(awardId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    award = _load_award_or_404(awardId)
    if award["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Award is not ACTIVE")
    for e in db.store.enrollments.values():
        if e["award_id"] == awardId and e["status"] in (
            "PENDING_CHECKS",
            "ACTIVE",
            "SUSPENDED",
        ):
            raise ApiError(
                "ERR_ENROLLMENTS_OPEN",
                409,
                "Award still has non-terminal enrollments",
            )
    if (
        award["allowable_match_cents"] * C.MATCH_MIN_DENOMINATOR
        < award["federal_share_awarded_cents"] * C.MATCH_MIN_NUMERATOR
    ):
        raise ApiError(
            "ERR_MATCH_BELOW_MINIMUM", 422, "Accumulated match is below the 24% floor"
        )
    award["status"] = "CLOSED"
    domain.touch(award)
    for slot in db.store.slots.values():
        if slot["award_id"] == awardId and slot["status"] == "OPEN":
            slot["status"] = "RETIRED"
            domain.touch(slot)
    return util.ok(serialize(award), 200)


@bp.route("/awards/<awardId>/match-reports", methods=["POST"])
def create_match_report(awardId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    award = db.store.awards.get(awardId)
    if award is not None:
        auth.check_grantee_ownership(uid, role, award["organization_id"])
    auth.check_not_debarred(uid, role)
    if award is None:
        raise ApiError("ERR_AWARD_NOT_FOUND", 404, "Award not found")
    body = util.body_json()
    label = body.get("reporting_period_label")
    lines = _validate_report_lines(body.get("lines"))
    if not util.is_str(label) or not label.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "reporting_period_label is required")
    if lines is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "lines must be an array of {category, amount_cents}",
        )
    if award["status"] != "ACTIVE":
        raise ApiError("ERR_AWARD_SUSPENDED", 409, "Award is not ACTIVE")
    award["allowable_match_cents"] += domain.match_lines_total(lines)
    domain.touch(award)
    return util.ok(serialize(award), 201)


@bp.route("/awards/<awardId>/slots", methods=["GET"])
def list_award_slots(awardId):
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    award = _load_award_or_404(awardId)
    auth.check_grantee_ownership(uid, role, award["organization_id"])
    items = [s for s in db.store.slots.values() if s["award_id"] == awardId]
    status = request.args.get("status")
    term_category = request.args.get("term_category")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if term_category is not None:
        items = [s for s in items if s["term_category"] == term_category]
    return util.list_response(items, serialize)


@bp.route("/awards/<awardId>/compliance-visits", methods=["GET"])
def list_award_visits(awardId):
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    award = _load_award_or_404(awardId)
    auth.check_grantee_ownership(uid, role, award["organization_id"])
    items = [v for v in db.store.visits.values() if v["award_id"] == awardId]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    return util.list_response(items, serialize)


@bp.route("/awards/<awardId>/performance-measures", methods=["GET"])
def list_award_measures(awardId):
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    award = _load_award_or_404(awardId)
    auth.check_grantee_ownership(uid, role, award["organization_id"])
    items = [m for m in db.store.measures.values() if m["award_id"] == awardId]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return util.list_response(items, serialize)


@bp.route("/slots/<slotId>", methods=["GET"])
def get_slot(slotId):
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    slot = db.store.slots.get(slotId)
    if slot is None:
        raise ApiError("ERR_SLOT_NOT_FOUND", 404, "Slot not found")
    award = db.store.awards.get(slot["award_id"])
    if award is not None:
        auth.check_grantee_ownership(uid, role, award["organization_id"])
    return util.ok(serialize(slot), 200)
