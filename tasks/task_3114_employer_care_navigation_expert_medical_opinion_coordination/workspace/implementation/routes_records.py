"""Routes: record requests and expert opinion cases."""
from flask import Blueprint, request

from db import db
from errors import fail
from common import (envelope, paginate, body, auth, require_role,
                    check_member_scope, active_consent, touch)
from helpers import new_entity, get_or_404, req_str, opt_str, req_int

bp = Blueprint("records", __name__)

EMO_MIN_RECORDS = 3


def _recompute_attached_received(opinion_id):
    op = db.expert_opinions.get(opinion_id)
    if op is None:
        return
    count = 0
    for item in db.opinion_items.values():
        if item["opinion_id"] != opinion_id:
            continue
        rr = db.record_requests.get(item["record_request_id"])
        if rr is not None and rr["status"] == "RECEIVED":
            count += 1
    if op["attached_received_count"] != count:
        op["attached_received_count"] = count
        touch(op)


# ---- record requests ---------------------------------------------------------

@bp.post("/care/members/<mid>/record-requests")
def create_record_request(mid):
    user_id, role = auth()
    require_role(role, {"RecordsSpecialist"})
    data = body()
    provider_id = req_str(data, "provider_id")
    m = get_or_404(db.members, mid, "member")
    get_or_404(db.providers, provider_id, "provider")
    if m["eligibility_status"] != "ACTIVE":
        fail("ERR_MEMBER_INELIGIBLE", "member is not ACTIVE")
    if active_consent(mid, "RECORD_RETRIEVAL") is None:
        fail("ERR_CONSENT_REQUIRED", "no ACTIVE RECORD_RETRIEVAL consent")
    rr = new_entity({
        "member_id": mid,
        "provider_id": provider_id,
        "status": "REQUESTED",
        "record_pages": None,
        "retry_count": 0,
    })
    db.record_requests[rr["id"]] = rr
    # RECORDS_BLOCKED -> RECORDS_COLLECTION for this member's cases
    for op in list(db.expert_opinions.values()):
        if op["member_id"] == mid and op["status"] == "RECORDS_BLOCKED":
            op["status"] = "RECORDS_COLLECTION"
            touch(op)
    return envelope(rr, status=201)


@bp.get("/care/record-requests/<rid>")
def get_record_request(rid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "RecordsSpecialist", "ExpertReviewer", "Member"})
    rr = get_or_404(db.record_requests, rid, "record request")
    check_member_scope(rr["member_id"], user_id, role)
    return envelope(rr)


@bp.get("/care/record-requests")
def list_record_requests():
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin", "RecordsSpecialist"})
    items = list(db.record_requests.values())
    pid = request.args.get("provider_id")
    if pid is not None:
        items = [r for r in items if r["provider_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.get("/care/members/<mid>/record-requests")
def list_member_record_requests(mid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "RecordsSpecialist", "Member"})
    get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    items = [r for r in db.record_requests.values() if r["member_id"] == mid]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.post("/care/record-requests/<rid>/receive")
def receive_record_request(rid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"RecordsSpecialist"})
    data = body()
    pages = data.get("record_pages")
    if pages is None or isinstance(pages, bool) or not isinstance(pages, int) or pages < 1:
        fail("ERR_INVALID_REQUEST", "record_pages must be an integer >= 1")
    rr = get_or_404(db.record_requests, rid, "record request")
    if rr["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "record request is not REQUESTED")
    rr["status"] = "RECEIVED"
    rr["record_pages"] = pages
    touch(rr)
    for item in db.opinion_items.values():
        if item["record_request_id"] == rid:
            _recompute_attached_received(item["opinion_id"])
    return envelope(rr)


@bp.post("/care/record-requests/<rid>/fail")
def fail_record_request(rid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"RecordsSpecialist"})
    rr = get_or_404(db.record_requests, rid, "record request")
    if rr["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "record request is not REQUESTED")
    rr["status"] = "FAILED"
    touch(rr)
    return envelope(rr)


@bp.post("/care/record-requests/<rid>/retry")
def retry_record_request(rid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"RecordsSpecialist"})
    rr = get_or_404(db.record_requests, rid, "record request")
    if rr["status"] != "FAILED":
        fail("ERR_INVALID_STATE", "record request is not FAILED")
    if rr["retry_count"] >= 2:
        fail("ERR_RETRY_EXHAUSTED", "retry limit reached")
    if active_consent(rr["member_id"], "RECORD_RETRIEVAL") is None:
        fail("ERR_CONSENT_REQUIRED", "no ACTIVE RECORD_RETRIEVAL consent")
    rr["status"] = "REQUESTED"
    rr["retry_count"] += 1
    touch(rr)
    return envelope(rr)


@bp.post("/care/record-requests/<rid>/cancel")
def cancel_record_request(rid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"RecordsSpecialist"})
    rr = get_or_404(db.record_requests, rid, "record request")
    if rr["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "record request is not REQUESTED")
    rr["status"] = "CANCELLED"
    touch(rr)
    from common import _maybe_block_records
    _maybe_block_records(rr["member_id"])
    return envelope(rr)


# ---- expert opinion cases -----------------------------------------------------

def _opinion(oid):
    return get_or_404(db.expert_opinions, oid, "expert opinion case")


@bp.post("/care/members/<mid>/expert-opinions")
def create_expert_opinion(mid):
    user_id, role = auth()
    require_role(role, {"Member", "RecordsSpecialist"})
    data = body()
    condition_summary = req_str(data, "condition_summary")
    nav_case_id = opt_str(data, "navigation_case_id")
    m = get_or_404(db.members, mid, "member")
    if nav_case_id is not None:
        get_or_404(db.navigation_cases, nav_case_id, "navigation case")
    check_member_scope(mid, user_id, role)
    if m["eligibility_status"] != "ACTIVE":
        fail("ERR_MEMBER_INELIGIBLE", "member is not ACTIVE")
    employer = db.employers.get(m["employer_id"])
    if employer is None or not employer.get("emo_benefit_enabled"):
        fail("ERR_INVALID_REQUEST", "employer does not sponsor the expert medical opinion benefit")
    if active_consent(mid, "EMO_REVIEW") is None:
        fail("ERR_CONSENT_REQUIRED", "no ACTIVE EMO_REVIEW consent")
    op = new_entity({
        "member_id": mid,
        "navigation_case_id": nav_case_id,
        "condition_summary": condition_summary,
        "status": "INTAKE",
        "compiler_user_id": None,
        "reviewer_user_id": None,
        "recommendation_text": None,
        "recommendation_version": 0,
        "attached_received_count": 0,
    })
    db.expert_opinions[op["id"]] = op
    return envelope(op, status=201)


@bp.get("/care/expert-opinions/<oid>")
def get_expert_opinion(oid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Member", "RecordsSpecialist", "ExpertReviewer", "PhysicianAdvisor"})
    op = _opinion(oid)
    check_member_scope(op["member_id"], user_id, role)
    return envelope(op)


@bp.get("/care/members/<mid>/expert-opinions")
def list_member_opinions(mid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Member", "RecordsSpecialist", "ExpertReviewer"})
    get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    items = [o for o in db.expert_opinions.values() if o["member_id"] == mid]
    st = request.args.get("status")
    if st is not None:
        items = [o for o in items if o["status"] == st]
    items.sort(key=lambda o: o["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.post("/care/expert-opinions/<oid>/attach-records")
def attach_records(oid):
    user_id, role = auth()
    require_role(role, {"RecordsSpecialist"})
    data = body()
    rr_id = req_str(data, "record_request_id")
    op = _opinion(oid)
    rr = db.record_requests.get(rr_id)
    if rr is None:
        fail("ERR_RECORD_NOT_READY", "record request not found")
    if rr["member_id"] != op["member_id"]:
        fail("ERR_RECORD_NOT_READY", "record request belongs to a different member")
    if rr["status"] != "RECEIVED":
        fail("ERR_RECORD_NOT_READY", "record request is not RECEIVED")
    for item in db.opinion_items.values():
        if item["record_request_id"] == rr_id:
            other = db.expert_opinions.get(item["opinion_id"])
            if other is not None and other["status"] not in ("DELIVERED", "WITHDRAWN"):
                fail("ERR_RECORD_NOT_READY", "record request already attached to a live opinion case")
    item = new_entity({
        "opinion_id": oid,
        "record_request_id": rr_id,
        "attached_by_user_id": user_id,
    })
    db.opinion_items[item["id"]] = item
    if op["status"] == "INTAKE":
        op["status"] = "RECORDS_COLLECTION"
        touch(op)
    _recompute_attached_received(oid)
    return envelope(item, status=201)


@bp.get("/care/expert-opinions/<oid>/record-items")
def list_opinion_items(oid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "RecordsSpecialist", "ExpertReviewer", "Member"})
    op = _opinion(oid)
    check_member_scope(op["member_id"], user_id, role)
    items = [i for i in db.opinion_items.values() if i["opinion_id"] == oid]
    items.sort(key=lambda i: i["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.get("/care/record-requests/<rid>/opinion-items")
def list_request_opinion_items(rid):
    auth()
    require_role(request.headers.get("X-User-Role"), {"PlatformAdmin", "RecordsSpecialist"})
    get_or_404(db.record_requests, rid, "record request")
    items = [i for i in db.opinion_items.values() if i["record_request_id"] == rid]
    items.sort(key=lambda i: i["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.post("/care/expert-opinions/<oid>/compile")
def compile_opinion(oid):
    user_id, role = auth()
    require_role(role, {"RecordsSpecialist"})
    op = _opinion(oid)
    if op["status"] not in ("RECORDS_COLLECTION", "CHANGES_REQUESTED"):
        fail("ERR_INVALID_STATE", "opinion is not RECORDS_COLLECTION or CHANGES_REQUESTED")
    if active_consent(op["member_id"], "EMO_REVIEW") is None:
        fail("ERR_CONSENT_REQUIRED", "no ACTIVE EMO_REVIEW consent")
    op["status"] = "COMPILING"
    op["compiler_user_id"] = user_id
    touch(op)
    return envelope(op)


@bp.post("/care/expert-opinions/<oid>/submit-for-review")
def submit_for_review(oid):
    user_id, role = auth()
    require_role(role, {"RecordsSpecialist"})
    op = _opinion(oid)
    if op["status"] != "COMPILING":
        fail("ERR_INVALID_STATE", "opinion is not COMPILING")
    if op["compiler_user_id"] != user_id:
        fail("ERR_NOT_ASSIGNED_COMPILER", "only the compiler may submit for review")
    if op["attached_received_count"] < EMO_MIN_RECORDS:
        fail("ERR_RECORDS_INSUFFICIENT", "fewer than 3 received records attached")
    has_auth = any(
        a["member_id"] == op["member_id"] and a["service_code"] == "EXPERT_MEDICAL_OPINION"
        and a["status"] == "APPROVED"
        for a in db.authorizations.values()
    )
    if not has_auth:
        fail("ERR_AUTHORIZATION_REQUIRED", "no APPROVED EXPERT_MEDICAL_OPINION authorization")
    op["status"] = "READY_FOR_REVIEW"
    touch(op)
    return envelope(op)


@bp.post("/care/expert-opinions/<oid>/claim-review")
def claim_review(oid):
    user_id, role = auth()
    require_role(role, {"ExpertReviewer"})
    op = _opinion(oid)
    if op["status"] != "READY_FOR_REVIEW":
        fail("ERR_INVALID_STATE", "opinion is not READY_FOR_REVIEW")
    if user_id == op["compiler_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "reviewer must differ from compiler")
    op["status"] = "IN_REVIEW"
    op["reviewer_user_id"] = user_id
    touch(op)
    return envelope(op)


@bp.post("/care/expert-opinions/<oid>/request-changes")
def request_changes(oid):
    user_id, role = auth()
    require_role(role, {"ExpertReviewer"})
    op = _opinion(oid)
    if op["status"] != "IN_REVIEW":
        fail("ERR_INVALID_STATE", "opinion is not IN_REVIEW")
    if op["reviewer_user_id"] != user_id:
        fail("ERR_NOT_ASSIGNED_REVIEWER", "only the assigned reviewer may request changes")
    op["status"] = "CHANGES_REQUESTED"
    touch(op)
    return envelope(op)


@bp.post("/care/expert-opinions/<oid>/submit-recommendation")
def submit_recommendation(oid):
    user_id, role = auth()
    require_role(role, {"ExpertReviewer"})
    data = body()
    text = req_str(data, "recommendation_text")
    if "expected_opinion_version" not in data or not isinstance(data["expected_opinion_version"], int):
        fail("ERR_INVALID_REQUEST", "expected_opinion_version is required")
    expected = data["expected_opinion_version"]
    op = _opinion(oid)
    # OCC per §2.7: a submission whose expected_opinion_version does not match
    # the case's current version is rejected with ERR_STALE_VERSION (412),
    # preventing the reviewer from overwriting a draft superseded by one they
    # have not observed — this holds even when the case has since left
    # IN_REVIEW, so the staleness check runs before the state check.
    if expected != op["version"]:
        fail("ERR_STALE_VERSION", "expected_opinion_version does not match current case version")
    if op["status"] != "IN_REVIEW":
        fail("ERR_INVALID_STATE", "opinion is not IN_REVIEW")
    if op["reviewer_user_id"] != user_id:
        fail("ERR_NOT_ASSIGNED_REVIEWER", "only the assigned reviewer may submit a recommendation")
    op["recommendation_text"] = text
    op["recommendation_version"] += 1
    op["status"] = "RECOMMENDATION_SUBMITTED"
    touch(op)
    return envelope(op)


@bp.post("/care/expert-opinions/<oid>/deliver")
def deliver_opinion(oid):
    user_id, role = auth()
    require_role(role, {"Member"})
    op = _opinion(oid)
    check_member_scope(op["member_id"], user_id, role)
    if op["status"] != "RECOMMENDATION_SUBMITTED":
        fail("ERR_INVALID_STATE", "opinion is not RECOMMENDATION_SUBMITTED")
    op["status"] = "DELIVERED"
    touch(op)
    return envelope(op)


@bp.post("/care/expert-opinions/<oid>/withdraw")
def withdraw_opinion(oid):
    user_id, role = auth()
    require_role(role, {"Member", "PlatformAdmin"})
    op = _opinion(oid)
    check_member_scope(op["member_id"], user_id, role)
    if op["status"] in ("DELIVERED", "WITHDRAWN"):
        fail("ERR_INVALID_STATE", "opinion is terminal")
    op["status"] = "WITHDRAWN"
    op["compiler_user_id"] = None
    op["reviewer_user_id"] = None
    touch(op)
    return envelope(op)
