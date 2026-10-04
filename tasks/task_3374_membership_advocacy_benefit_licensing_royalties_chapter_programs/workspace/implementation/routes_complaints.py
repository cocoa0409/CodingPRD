"""Member complaints and oversight adjudication (incl. escalation cascade)."""

from flask import Blueprint, request

from auth import forbidden, require_roles
from db import locked, mint, store, touch
from serializers import complaint_view
from services import member_in_good_standing, run_escalation_cascade
from util import err, get_body, paginate, success_object

bp = Blueprint("complaints", __name__)

COMPLAINT_CATEGORIES = {"PRODUCT_QUALITY", "BILLING", "SERVICE", "CLAIMS"}
COMPLAINT_SEVERITIES = {"LOW", "HIGH"}
ADJUDICATE_ACTIONS = {"OPEN_REVIEW", "RESOLVE", "ESCALATE"}
COMPLAINT_READ_ROLES = ("OversightAnalyst", "MemberServicesAgent", "PlatformAdmin")


@bp.post("/api/complaints")
@locked
def file_complaint():
    user_id, _ = require_roles("Member")
    body = get_body()
    # Rung 3: a member files only as themselves.
    member_id = body.get("member_id")
    if member_id is not None and member_id != user_id:
        forbidden("A Member may only file complaints as themselves")
    # Rung 5: schema.
    for field in ("member_id", "license_agreement_id", "category", "severity", "description"):
        if body.get(field) is None:
            err("ERR_INVALID_REQUEST", 400, "Field '%s' is required" % field)
    if not isinstance(body["member_id"], str) or not isinstance(body["license_agreement_id"], str):
        err("ERR_INVALID_REQUEST", 400, "member_id and license_agreement_id must be strings")
    if body["category"] not in COMPLAINT_CATEGORIES:
        err("ERR_INVALID_REQUEST", 400, "category must be one of PRODUCT_QUALITY, BILLING, SERVICE, CLAIMS")
    if body["severity"] not in COMPLAINT_SEVERITIES:
        err("ERR_INVALID_REQUEST", 400, "severity must be LOW or HIGH")
    if not isinstance(body["description"], str):
        err("ERR_INVALID_REQUEST", 400, "description must be a string")
    # Rung 6: body FK existence, member before agreement.
    member = store.members.get(body["member_id"])
    if member is None:
        err("ERR_NOT_FOUND", 404, "Member not found")
    agreement = store.agreements.get(body["license_agreement_id"])
    if agreement is None:
        err("ERR_NOT_FOUND", 404, "License agreement not found")
    # Rung 9: filing gates on standing before it gates on the agreement.
    if not member_in_good_standing(member):
        err("ERR_MEMBER_NOT_ACTIVE", 409, "Member is not in good standing")
    # Rung 11: the agreement must be ACTIVE or PROBATION.
    if agreement["status"] not in ("ACTIVE", "PROBATION"):
        err("ERR_AGREEMENT_STATE", 409, "Complaints may only be filed against ACTIVE or PROBATION agreements")

    complaint = mint(store.complaints)
    complaint.update(
        {
            "member_id": body["member_id"],
            "license_agreement_id": body["license_agreement_id"],
            "category": body["category"],
            "severity": body["severity"],
            "description": body["description"],
            "status": "FILED",
            "filed_at": store.clock_raw,
            "escalated_at": None,
            "resolution_code": None,
        }
    )
    return success_object(complaint_view(complaint), status=201)


@bp.get("/api/complaints/<complaint_id>")
@locked
def get_complaint(complaint_id):
    require_roles(*COMPLAINT_READ_ROLES)
    complaint = store.complaints.get(complaint_id)
    if complaint is None:
        err("ERR_NOT_FOUND", 404, "Complaint not found")
    return success_object(complaint_view(complaint))


@bp.get("/api/complaints")
@locked
def list_complaints():
    require_roles(*COMPLAINT_READ_ROLES)
    member_filter = request.args.get("member_id")
    agreement_filter = request.args.get("license_agreement_id")
    status_filter = request.args.get("status")
    complaints = sorted(store.complaints.values(), key=lambda r: r["_seq"])
    if member_filter is not None:
        complaints = [c for c in complaints if c["member_id"] == member_filter]
    if agreement_filter is not None:
        complaints = [c for c in complaints if c["license_agreement_id"] == agreement_filter]
    if status_filter is not None:
        complaints = [c for c in complaints if c["status"] == status_filter]
    return paginate([complaint_view(c) for c in complaints])


@bp.post("/api/complaints/<complaint_id>/adjudicate")
@locked
def adjudicate_complaint(complaint_id):
    require_roles("OversightAnalyst")
    body = get_body()
    action = body.get("action")
    if action not in ADJUDICATE_ACTIONS:
        err("ERR_INVALID_REQUEST", 400, "action must be one of OPEN_REVIEW, RESOLVE, ESCALATE")
    resolution_code = body.get("resolution_code")
    if resolution_code is not None and not isinstance(resolution_code, str):
        err("ERR_INVALID_REQUEST", 400, "resolution_code must be a string")
    complaint = store.complaints.get(complaint_id)
    if complaint is None:
        err("ERR_NOT_FOUND", 404, "Complaint not found")
    status = complaint["status"]

    if action == "OPEN_REVIEW":
        if status != "FILED":
            err("ERR_COMPLAINT_STATE", 409, "OPEN_REVIEW is only valid from FILED")
        complaint["status"] = "UNDER_REVIEW"
    elif action == "RESOLVE":
        if status not in ("UNDER_REVIEW", "ESCALATED"):
            err("ERR_COMPLAINT_STATE", 409, "RESOLVE is only valid from UNDER_REVIEW or ESCALATED")
        complaint["status"] = "RESOLVED"
        if resolution_code is not None:
            complaint["resolution_code"] = resolution_code
    else:  # ESCALATE
        if status != "UNDER_REVIEW":
            err("ERR_COMPLAINT_STATE", 409, "ESCALATE is only valid from UNDER_REVIEW")
        agreement = store.agreements.get(complaint["license_agreement_id"])
        if agreement is None or agreement["status"] not in ("ACTIVE", "PROBATION"):
            err("ERR_AGREEMENT_STATE", 409, "Cannot escalate a complaint whose agreement is not ACTIVE or PROBATION")
        # Stamp first so this complaint counts toward the trailing windows.
        complaint["status"] = "ESCALATED"
        complaint["escalated_at"] = store.clock_raw
        touch(complaint)
        run_escalation_cascade(complaint)
        return success_object(complaint_view(complaint))

    touch(complaint)
    return success_object(complaint_view(complaint))
