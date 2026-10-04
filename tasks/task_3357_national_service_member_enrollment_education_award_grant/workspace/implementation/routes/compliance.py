from datetime import timedelta

from flask import Blueprint, request

import auth
import clock
import constants as C
import db
import domain
import util
from errors import ApiError
from serializers import serialize

bp = Blueprint("compliance", __name__)

FINDING_READ_ROLES = ["CNCSProgramOfficer", "ComplianceOfficer", "GranteeStaff"]


def _check_finding_grantee_ownership(uid, role, finding):
    award = db.store.awards.get(finding["award_id"])
    if award is not None:
        auth.check_grantee_ownership(uid, role, award["organization_id"])


@bp.route("/awards/<awardId>/compliance-visits", methods=["POST"])
def schedule_visit(awardId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["ComplianceOfficer"])
    award = db.store.awards.get(awardId)
    if award is None:
        raise ApiError("ERR_AWARD_NOT_FOUND", 404, "Award not found")
    body = util.body_json()
    visit_type = body.get("visit_type")
    scheduled_raw = body.get("scheduled_date")
    scheduled_date = util.parse_date(scheduled_raw)
    if visit_type not in C.VISIT_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "visit_type is invalid")
    if scheduled_date is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "scheduled_date must be an ISO date (YYYY-MM-DD)",
        )
    # 30-day breathing room against every other SCHEDULED or CONDUCTED visit.
    for other in db.store.visits.values():
        if other["award_id"] != awardId:
            continue
        if other["status"] not in ("SCHEDULED", "CONDUCTED"):
            continue
        other_date = util.parse_date(other["scheduled_date"])
        if abs((scheduled_date - other_date).days) < C.VISIT_BUFFER_DAYS:
            raise ApiError(
                "ERR_VISIT_TOO_SOON",
                409,
                "Visit is less than 30 days away from another visit of this award",
            )
    visit = db.new_entity(
        {
            "id": util.new_id(),
            "award_id": awardId,
            "visit_type": visit_type,
            "scheduled_date": scheduled_raw,
            "created_by_officer_id": uid,
            "conducted_at": None,
            "status": "SCHEDULED",
        }
    )
    db.store.visits[visit["id"]] = visit
    return util.ok(serialize(visit), 201)


@bp.route("/compliance-visits/<visitId>/conduct", methods=["POST"])
def conduct_visit(visitId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["ComplianceOfficer"])
    visit = db.store.visits.get(visitId)
    if visit is None:
        raise ApiError("ERR_VISIT_NOT_FOUND", 404, "Compliance visit not found")
    if visit["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Visit is not SCHEDULED")
    visit["status"] = "CONDUCTED"
    visit["conducted_at"] = clock.now_iso()
    domain.touch(visit)
    return util.ok(serialize(visit), 200)


@bp.route("/compliance-visits/<visitId>/findings", methods=["POST"])
def create_finding(visitId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["ComplianceOfficer"])
    visit = db.store.visits.get(visitId)
    if visit is None:
        raise ApiError("ERR_VISIT_NOT_FOUND", 404, "Compliance visit not found")
    body = util.body_json()
    severity = body.get("severity")
    description = body.get("description")
    if severity not in C.SEVERITIES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "severity is invalid")
    if not util.is_str(description) or not description.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "description is required")
    if visit["status"] != "CONDUCTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Visit is not CONDUCTED")
    finding = db.new_entity(
        {
            "id": util.new_id(),
            "visit_id": visitId,
            "award_id": visit["award_id"],
            "severity": severity,
            "description": description,
            "requirement": None,
            "due_days": None,
            "due_at": None,
            "evidence_note": None,
            "submitted_by_org_id": None,
            "decided_by_officer_id": None,
            "status": "OPEN",
        }
    )
    db.store.findings[finding["id"]] = finding
    return util.ok(serialize(finding), 201)


@bp.route("/findings", methods=["GET"])
def list_findings():
    uid, role = auth.authenticate()
    auth.authorize(role, FINDING_READ_ROLES)
    items = list(db.store.findings.values())
    if role == "GranteeStaff":
        items = [
            f
            for f in items
            if db.store.awards.get(f["award_id"], {}).get("organization_id") == uid
        ]
    visit_id = request.args.get("visit_id")
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    if visit_id is not None:
        items = [f for f in items if f["visit_id"] == visit_id]
    if award_id is not None:
        items = [f for f in items if f["award_id"] == award_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return util.list_response(items, serialize)


@bp.route("/findings/<findingId>", methods=["GET"])
def get_finding(findingId):
    uid, role = auth.authenticate()
    auth.authorize(role, FINDING_READ_ROLES)
    finding = db.store.findings.get(findingId)
    if finding is None:
        raise ApiError("ERR_FINDING_NOT_FOUND", 404, "Finding not found")
    _check_finding_grantee_ownership(uid, role, finding)
    return util.ok(serialize(finding), 200)


@bp.route("/findings/<findingId>/assign-corrective-action", methods=["POST"])
def assign_corrective_action(findingId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["ComplianceOfficer"])
    finding = db.store.findings.get(findingId)
    if finding is None:
        raise ApiError("ERR_FINDING_NOT_FOUND", 404, "Finding not found")
    body = util.body_json()
    requirement = body.get("requirement")
    due_days = body.get("due_days")
    if not util.is_str(requirement) or not requirement.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "requirement is required")
    if (
        not util.is_int(due_days)
        or due_days < C.DUE_DAYS_MIN
        or due_days > C.DUE_DAYS_MAX
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "due_days must be an integer in 14..90"
        )
    if finding["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Finding is not OPEN")
    finding["requirement"] = requirement
    finding["due_days"] = due_days
    finding["due_at"] = clock.iso(clock.now() + timedelta(days=due_days))
    finding["status"] = "ACTION_ASSIGNED"
    domain.touch(finding)
    return util.ok(serialize(finding), 200)


@bp.route("/findings/<findingId>/submit-evidence", methods=["POST"])
def submit_evidence(findingId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    finding = db.store.findings.get(findingId)
    if finding is not None:
        _check_finding_grantee_ownership(uid, role, finding)
    auth.check_not_debarred(uid, role)
    if finding is None:
        raise ApiError("ERR_FINDING_NOT_FOUND", 404, "Finding not found")
    body = util.body_json()
    evidence_note = body.get("evidence_note")
    if not util.is_str(evidence_note):
        raise ApiError("ERR_INVALID_REQUEST", 400, "evidence_note is required")
    if finding["status"] not in ("ACTION_ASSIGNED", "ESCALATED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Finding is not ACTION_ASSIGNED or ESCALATED",
        )
    finding["status"] = "EVIDENCE_SUBMITTED"
    finding["evidence_note"] = evidence_note
    finding["submitted_by_org_id"] = uid
    domain.touch(finding)
    return util.ok(serialize(finding), 200)


@bp.route("/findings/<findingId>/decide", methods=["POST"])
def decide_finding(findingId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["ComplianceOfficer"])
    finding = db.store.findings.get(findingId)
    if finding is None:
        raise ApiError("ERR_FINDING_NOT_FOUND", 404, "Finding not found")
    body = util.body_json()
    decision = body.get("decision")
    if decision not in C.FINDING_DECISIONS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "decision must be APPROVE or REJECT")
    if finding["status"] != "EVIDENCE_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Finding is not EVIDENCE_SUBMITTED")
    visit = db.store.visits.get(finding["visit_id"])
    # Segregation of duties: the deciding officer must differ from the creator.
    if visit is not None and uid == visit["created_by_officer_id"]:
        raise ApiError(
            "ERR_SOD_VIOLATION",
            403,
            "The deciding officer must differ from the visit creator",
        )
    finding["decided_by_officer_id"] = uid
    if decision == "APPROVE":
        finding["status"] = "RESOLVED"
        domain.touch(finding)
        if visit is not None:
            domain.visit_bubble(visit)
    else:
        finding["status"] = "ACTION_ASSIGNED"
        domain.touch(finding)
    return util.ok(serialize(finding), 200)


@bp.route("/compliance/sweep-overdue", methods=["POST"])
def sweep_overdue():
    _uid, role = auth.authenticate()
    auth.authorize(role, ["ComplianceOfficer"])
    now = clock.now()
    overdue = [
        f
        for f in db.store.findings.values()
        if f["status"] in ("ACTION_ASSIGNED", "EVIDENCE_SUBMITTED")
        and f.get("due_at")
        and clock.parse_datetime(f["due_at"]) < now
    ]
    overdue.sort(key=lambda f: (f.get("created_at", ""), f.get("_seq", 0)))
    escalated_finding_ids = []
    suspended_award_ids = []
    suspended_enrollment_ids = []
    for finding in overdue:
        finding["status"] = "ESCALATED"
        domain.touch(finding)
        escalated_finding_ids.append(finding["id"])
        award = db.store.awards.get(finding["award_id"])
        if award is not None and award["status"] == "ACTIVE":
            suspended = domain.suspend_award(award, C.ESCALATION_REASON)
            suspended_award_ids.append(award["id"])
            suspended_enrollment_ids.extend(suspended)
    return util.ok(
        {
            "escalated_finding_ids": escalated_finding_ids,
            "suspended_award_ids": suspended_award_ids,
            "suspended_enrollment_ids": suspended_enrollment_ids,
        },
        200,
    )
