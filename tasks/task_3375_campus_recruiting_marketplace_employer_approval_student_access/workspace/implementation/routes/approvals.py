"""Per-university employer approvals: request, list, read, decide."""

from flask import Blueprint, request

import db
from db import now, wall_now
from errors import fail
from services import approval_view, employer_block_cascade
from util import Body, get_context, paginate, require_role, success_object

bp = Blueprint("approvals", __name__)

DECISIONS = ("APPROVE", "BLOCK", "REVOKE")
DECISION_TARGET = {"APPROVE": "APPROVED", "BLOCK": "BLOCKED", "REVOKE": "REVOKED"}


@bp.route("/employer-approvals", methods=["POST"])
def create_approval():
    user_id, role = get_context()
    require_role(role, "EmployerRecruiter")
    body = Body()
    employer_id = body.str_f("employer_id", required=True)
    university_id = body.str_f("university_id", required=True)
    # Priority 3 ownership: the recruiter operates their own employer.
    if employer_id is not None and employer_id != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Recruiter may request approvals only for their own employer")
    # Priority 4 existence, body FK order: employer_id, then university_id.
    employer = db.get("employers", employer_id) if employer_id else None
    if employer_id is not None and employer is None:
        fail("ERR_EMPLOYER_NOT_FOUND", "Employer id does not exist")
    university = db.get("universities", university_id) if university_id else None
    if university_id is not None and university is None:
        fail("ERR_UNIVERSITY_NOT_FOUND", "University id does not exist")
    # Priority 5 state: employer must be APPROVED.
    if employer is not None and employer["status"] != "APPROVED":
        fail("ERR_EMPLOYER_NOT_APPROVED", "Employer must be APPROVED to request approval")
    # Priority 9 constraint: duplicate guard / supersession.
    supersedes = None
    if employer_id is not None and university_id is not None:
        prior = [
            a for a in db.all_of("employer_approvals")
            if a["employer_id"] == employer_id and a["university_id"] == university_id
        ]
        if any(a["status"] in ("PENDING", "APPROVED") for a in prior):
            fail("ERR_DUPLICATE_APPROVAL_REQUEST",
                 "A PENDING or APPROVED approval already exists for this pair")
        terminal = [a for a in prior if a["status"] in ("BLOCKED", "REVOKED")]
        if terminal:
            supersedes = max(terminal, key=lambda a: (a["created_at"], a["_seq"]))
    body.finalize()
    if supersedes is not None:
        supersedes["status"] = "SUPERSEDED"
        db.touch(supersedes)
    record = {
        "id": db.new_id(),
        "employer_id": employer_id,
        "university_id": university_id,
        "status": "PENDING",
        "decision_reason": None,
        "decided_at": None,
        "trust_tier_at_decision": None,
        "supersedes_approval_id": supersedes["id"] if supersedes else None,
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
    }
    db.insert("employer_approvals", record)
    return success_object(approval_view(record), 201)


@bp.route("/employer-approvals", methods=["GET"])
def list_approvals():
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin", "EmployerRecruiter", "PlatformAdmin")
    records = db.all_of("employer_approvals")
    if role == "CareerCenterAdmin":
        records = [a for a in records if a["university_id"] == user_id]
    elif role == "EmployerRecruiter":
        records = [a for a in records if a["employer_id"] == user_id]
    f_employer = request.args.get("employer_id")
    f_university = request.args.get("university_id")
    f_status = request.args.get("status")
    f_supersedes = request.args.get("supersedes_approval_id")
    if f_employer is not None:
        records = [a for a in records if a["employer_id"] == f_employer]
    if f_university is not None:
        records = [a for a in records if a["university_id"] == f_university]
    if f_status is not None:
        records = [a for a in records if a["status"] == f_status]
    if f_supersedes is not None:
        records = [a for a in records if a["supersedes_approval_id"] == f_supersedes]
    return paginate(records, approval_view)


@bp.route("/employer-approvals/<approval_id>", methods=["GET"])
def get_approval(approval_id):
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin", "EmployerRecruiter", "PlatformAdmin")
    approval = db.get("employer_approvals", approval_id)
    if approval is None:
        fail("ERR_EMPLOYER_APPROVAL_NOT_FOUND", "EmployerApproval id does not exist")
    if role == "CareerCenterAdmin" and user_id != approval["university_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may read only its own approvals")
    if role == "EmployerRecruiter" and user_id != approval["employer_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Recruiter may read only their own approvals")
    return success_object(approval_view(approval))


@bp.route("/employer-approvals/<approval_id>/decide", methods=["POST"])
def decide_approval(approval_id):
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin")
    approval = db.get("employer_approvals", approval_id)
    if approval is None:
        fail("ERR_EMPLOYER_APPROVAL_NOT_FOUND", "EmployerApproval id does not exist")
    if user_id != approval["university_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may decide only its own approvals")
    body = Body()
    decision = body.str_f("decision", required=True, enum=DECISIONS)
    decision_reason = body.str_f("decision_reason")
    expected_version = body.int_f("expected_employer_version", required=True)
    # Priority 5 state: university must be ACTIVE for any decision.
    university = db.get("universities", approval["university_id"])
    if university is not None and university["status"] != "ACTIVE":
        fail("ERR_UNIVERSITY_NOT_ACTIVE", "University is not ACTIVE")
    if decision is not None:
        current = approval["status"]
        legal = (
            (decision in ("APPROVE", "BLOCK") and current == "PENDING")
            or (decision == "REVOKE" and current == "APPROVED")
        )
        if not legal:
            fail("ERR_INVALID_APPROVAL_TRANSITION",
                 "Decision %s is not allowed from status %s" % (decision, current))
    # Priority 6 OCC on the employer's version.
    employer = db.get("employers", approval["employer_id"])
    if expected_version is not None and employer is not None and employer["version"] != expected_version:
        fail("ERR_STALE_EMPLOYER_VERSION",
             "expected_employer_version does not match the current Employer version")
    body.finalize()
    stamp = now()
    approval["status"] = DECISION_TARGET[decision]
    approval["decision_reason"] = decision_reason
    approval["decided_at"] = stamp
    approval["trust_tier_at_decision"] = employer["trust_tier"]
    db.touch(approval)
    employer["last_trust_decision_at"] = stamp
    db.touch(employer)
    if decision in ("BLOCK", "REVOKE"):
        employer_block_cascade(approval["employer_id"], approval["university_id"])
    return success_object(approval_view(approval))
