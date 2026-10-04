"""Student verifications: create, list, get, revoke."""
from flask import Blueprint, request

from db import db, parse_iso
from errors import err_invalid_request, err_already_terminal, err_invalid_state
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import new_resource, touch, get_or_404
from validate import body_json, req_string, req_enum, req_datetime

bp = Blueprint("student_verifications", __name__)


@bp.post("/student-verifications")
@require_roles("ComplianceAuditor", "PlatformAdmin")
def create_student_verification(auth):
    body = body_json()
    account_id = req_string(body, "account_id")
    get_or_404(db.accounts, account_id)
    institution_name = req_string(body, "institution_name")
    verification_method = req_enum(body, "verification_method", {"SHEERID", "DOCUMENT_REVIEW"})
    valid_through = req_datetime(body, "valid_through")
    if parse_iso(valid_through) <= db.clock.now():
        raise err_invalid_request("valid_through must be strictly after the verification timestamp")

    sv = new_resource()
    sv.update({
        "account_id": account_id,
        "institution_name": institution_name,
        "verification_method": verification_method,
        "valid_through": valid_through,
        "status": "VERIFIED",
    })
    db.student_verifications[sv["id"]] = sv
    return success(sv, status=201)


@bp.get("/student-verifications")
@require_roles("ComplianceAuditor", "PlatformAdmin", "SupportAgent")
def list_student_verifications(auth):
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    items = sorted(db.student_verifications.values(), key=lambda r: r["created_at"])
    if account_id is not None:
        items = [s for s in items if s["account_id"] == account_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/student-verifications/<sid>")
@require_roles("ComplianceAuditor", "PlatformAdmin", "SupportAgent")
def get_student_verification(sid, auth):
    sv = get_or_404(db.student_verifications, sid)
    return success(sv)


@bp.post("/student-verifications/<sid>/revoke")
@require_roles("ComplianceAuditor")
def revoke_student_verification(sid, auth):
    sv = get_or_404(db.student_verifications, sid)
    if sv["status"] in ("EXPIRED", "REVOKED"):
        raise err_already_terminal()
    if sv["status"] != "VERIFIED":
        raise err_invalid_state()
    sv["status"] = "REVOKED"
    touch(sv)
    return success(sv)
