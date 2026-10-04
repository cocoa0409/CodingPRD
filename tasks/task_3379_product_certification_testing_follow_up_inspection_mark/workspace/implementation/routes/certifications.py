"""Certification (listing report) endpoints: list/get, suspend, reinstate."""
from flask import Blueprint, request

import db
from constants import ROLE_COMPLIANCE
from errors import (
    ApiError, ERR_ALREADY_TERMINAL, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_OPEN_CRITICAL_FINDINGS,
)
from middleware import any_authenticated, require_roles
from response import paginated_list, success
from services import calc, lifecycle
from validation import body, req_str

bp = Blueprint("certifications", __name__)


def get_certification_or_404(certification_id):
    cert = db.certifications.get(certification_id)
    if cert is None:
        raise ApiError(ERR_NOT_FOUND, "certification not found")
    return cert


@bp.get("/certifications")
@any_authenticated
def list_certifications(user_id, role):
    items = db.sorted_items(db.certifications)
    for field in ("project_id", "manufacturer_id", "factory_id",
                  "standard_id", "construction_record_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            items = [c for c in items if c[field] == wanted]
    page, pagination = paginated_list(items)
    return success(page, pagination=pagination)


@bp.get("/certifications/<certification_id>")
@any_authenticated
def get_certification(certification_id, user_id, role):
    return success(get_certification_or_404(certification_id))


@bp.post("/certifications/<certification_id>/suspend")
@require_roles(ROLE_COMPLIANCE)
def suspend_certification(certification_id, user_id, role):
    cert = get_certification_or_404(certification_id)
    payload = body(required=True)
    reason = req_str(payload, "reason")
    if cert["status"] in ("WITHDRAWN", "EXPIRED"):
        raise ApiError(ERR_ALREADY_TERMINAL,
                       "certification is %s (terminal)" % cert["status"])
    if cert["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "certification is not ACTIVE")
    lifecycle.suspend_certification(cert, "MANUAL")
    return success(cert)


@bp.post("/certifications/<certification_id>/reinstate")
@require_roles(ROLE_COMPLIANCE)
def reinstate_certification(certification_id, user_id, role):
    cert = get_certification_or_404(certification_id)
    if cert["status"] in ("WITHDRAWN", "EXPIRED"):
        raise ApiError(ERR_ALREADY_TERMINAL,
                       "certification is %s (terminal)" % cert["status"])
    if cert["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "certification is not SUSPENDED")
    open_critical = calc.critical_findings_naming(cert["factory_id"], cert["id"])
    if open_critical > 0:
        raise ApiError(ERR_OPEN_CRITICAL_FINDINGS,
                       "open CRITICAL findings still name this certification")
    lifecycle.reinstate_certification(cert)
    return success(cert)
