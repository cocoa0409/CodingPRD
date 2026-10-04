"""Rights requests: file, review, escalate, decide (with SoD and cascades)."""
from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_STATE, ERR_SO_DUTY_VIOLATION, ERR_VALIDATION, not_found,
    raise_err, validation,
)
from middleware import require_roles
from models import serialize_rights_request, stamp_new, touch
from response import paginate, parse_pagination, success_list, success_object
from services import apply_rights_request_cascade, recompute_work_availability_and_effects

bp = Blueprint("rights", __name__)


@bp.post("/archive/rights-requests")
def file_rights_request():
    user_id, _ = require_roles("LegalReviewer")
    body = request.get_json(silent=True) or {}
    subject_kind = body.get("subject_kind")
    work_id = body.get("work_id")
    url_prefix = body.get("url_prefix")
    claimant_name = body.get("claimant_name")
    # Priority 3: work existence when supplied.
    if work_id is not None and work_id not in db.works:
        not_found("Work not found")
    # Priority 6: schema + subject-kind consistency.
    if subject_kind not in ("WORK", "CAPTURE_URL_PREFIX"):
        validation("subject_kind must be WORK or CAPTURE_URL_PREFIX")
    if subject_kind == "WORK":
        if not isinstance(work_id, str) or not work_id:
            validation("work_id is required for subject_kind WORK")
        if url_prefix is not None:
            validation("url_prefix must be null for subject_kind WORK")
    else:
        if not isinstance(url_prefix, str) or not url_prefix:
            validation("url_prefix is required for subject_kind CAPTURE_URL_PREFIX")
        if work_id is not None:
            validation("work_id must be null for subject_kind CAPTURE_URL_PREFIX")
    if not isinstance(claimant_name, str) or not claimant_name:
        validation("claimant_name is required")
    r = stamp_new()
    r.update({
        "subject_kind": subject_kind,
        "work_id": work_id if subject_kind == "WORK" else None,
        "url_prefix": url_prefix if subject_kind == "CAPTURE_URL_PREFIX" else None,
        "claimant_name": claimant_name,
        "filed_by": user_id,
        "status": "FILED",
        "reviewed_by": None,
        "decided_by": None,
    })
    db.rights_requests[r["id"]] = r
    return success_object(serialize_rights_request(r), status=201)


@bp.get("/archive/works/<wid>/rights-requests")
def list_work_rights_requests(wid):
    require_roles("Admin", "LegalReviewer")
    if wid not in db.works:
        not_found("Work not found")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    subject_kind = request.args.get("subject_kind")
    rows = [
        r for r in db.rights_requests.values()
        if r["subject_kind"] == "WORK" and r.get("work_id") == wid
    ]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if subject_kind is not None:
        rows = [r for r in rows if r["subject_kind"] == subject_kind]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate([serialize_rights_request(r) for r in rows], limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/archive/rights-requests/<rid>")
def get_rights_request(rid):
    require_roles("Admin", "LegalReviewer")
    r = db.rights_requests.get(rid)
    if r is None:
        not_found("Rights request not found")
    return success_object(serialize_rights_request(r))


@bp.post("/archive/rights-requests/<rid>/begin-review")
def begin_review(rid):
    user_id, _ = require_roles("LegalReviewer")
    r = db.rights_requests.get(rid)
    if r is None:
        not_found("Rights request not found")
    if r["status"] != "FILED":
        raise_err(ERR_INVALID_STATE, "Request is not FILED")
    # Priority 5: SoD — reviewer differs from filer.
    if user_id == r["filed_by"]:
        raise_err(ERR_SO_DUTY_VIOLATION, "The filer may not review their own filing")
    r["reviewed_by"] = user_id
    r["status"] = "UNDER_REVIEW"
    touch(r)
    if r["subject_kind"] == "WORK":
        recompute_work_availability_and_effects(r["work_id"])
    return success_object(serialize_rights_request(r))


@bp.post("/archive/rights-requests/<rid>/escalate-hold")
def escalate_hold(rid):
    user_id, _ = require_roles("LegalReviewer")
    r = db.rights_requests.get(rid)
    if r is None:
        not_found("Rights request not found")
    if r["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Request is not UNDER_REVIEW")
    # Only the assigned reviewer may escalate.
    if user_id != r["reviewed_by"]:
        raise_err(ERR_SO_DUTY_VIOLATION, "Only the assigned reviewer may escalate")
    r["status"] = "LEGAL_HOLD"
    touch(r)
    apply_rights_request_cascade(r)
    return success_object(serialize_rights_request(r))


@bp.post("/archive/rights-requests/<rid>/decide")
def decide_rights_request(rid):
    user_id, _ = require_roles("LegalReviewer")
    r = db.rights_requests.get(rid)
    if r is None:
        not_found("Rights request not found")
    if r["status"] not in ("UNDER_REVIEW", "LEGAL_HOLD"):
        raise_err(ERR_INVALID_STATE, "Request is not UNDER_REVIEW or LEGAL_HOLD")
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("UPHOLD", "DISMISS"):
        validation("decision must be UPHOLD or DISMISS")
    # Two-person rule: decider differs from reviewer.
    if user_id == r["reviewed_by"]:
        raise_err(ERR_SO_DUTY_VIOLATION, "The decider must differ from the reviewer")
    r["decided_by"] = user_id
    r["status"] = "UPHELD_REMOVED" if decision == "UPHOLD" else "DISMISSED"
    touch(r)
    if decision == "UPHOLD":
        apply_rights_request_cascade(r)
    else:
        if r["subject_kind"] == "WORK":
            recompute_work_availability_and_effects(r["work_id"])
    return success_object(serialize_rights_request(r))
