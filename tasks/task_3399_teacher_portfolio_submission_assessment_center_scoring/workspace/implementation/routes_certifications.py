"""Certification and renewal endpoints (PRD 3.7)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import constants as C
import errors as E
import serializers as ser
from response import ok, ok_list
from store import DB, new_id, stamp_new, touch, now
from validation import (auth_headers, require_role, body, req_field,
                        as_number, pagination_params, paginate)

bp = Blueprint("certifications", __name__)


def _get_certification_or_404(certification_id):
    cert = DB.certifications.get(certification_id)
    if cert is None:
        E.fail(E.ERR_CERTIFICATION_NOT_FOUND, 404,
               "Certification not found: %s" % certification_id)
    return cert


@bp.get("/certifications/<certification_id>")
def get_certification(certification_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE, C.ROLE_SCORING_ADMIN,
                        C.ROLE_BOARD_ADMIN, C.ROLE_INCENTIVE_ADMIN])
    cert = _get_certification_or_404(certification_id)
    if role == C.ROLE_CANDIDATE and cert["candidate_id"] != uid:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Candidates may read only their own certifications")
    return ok(ser.certification(cert))


@bp.get("/certifications")
def list_certifications():
    _, role = auth_headers()
    require_role(role, [C.ROLE_SCORING_ADMIN, C.ROLE_BOARD_ADMIN,
                        C.ROLE_INCENTIVE_ADMIN])
    limit, offset = pagination_params()
    items = list(DB.certifications.values())
    candidate_id = request.args.get("candidate_id")
    if candidate_id is not None:
        items = [c for c in items if c["candidate_id"] == candidate_id]
    cycle_id = request.args.get("cycle_id")
    if cycle_id is not None:
        items = [c for c in items if c["cycle_id"] == cycle_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return ok_list([ser.certification(c) for c in page], limit, offset, total)


def _parse_evidence_items(data):
    items = req_field(data, "evidence_items")
    if not isinstance(items, list) or len(items) < 1:
        E.fail(E.ERR_INVALID_REQUEST, 400,
               "evidence_items must contain at least one item")
    total = Decimal("0")
    for item in items:
        if not isinstance(item, dict):
            E.fail(E.ERR_INVALID_REQUEST, 400,
                   "each evidence item must be an object")
        if item.get("evidence_type") is None or item.get("description") is None:
            E.fail(E.ERR_INVALID_REQUEST, 400,
                   "each evidence item requires evidence_type and description")
        hours = item.get("hours")
        if hours is None:
            E.fail(E.ERR_INVALID_REQUEST, 400,
                   "each evidence item requires hours")
        hours = as_number(hours, "hours")
        if hours < 0:
            E.fail(E.ERR_INVALID_REQUEST, 400,
                   "evidence item hours must be at least 0")
        total += Decimal(str(hours))
    return items, total


@bp.post("/certifications/<certification_id>/renewals")
def create_renewal(certification_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE])
    cert = _get_certification_or_404(certification_id)
    if cert["candidate_id"] != uid:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Candidates may file renewals only for their own certification")
    if cert["status"] not in ("CERTIFIED", "RENEWED"):
        E.fail(E.ERR_CERTIFICATION_NOT_RENEWABLE, 409,
               "Certification must be CERTIFIED or RENEWED to renew")
    existing = [r for r in DB.renewals.values()
                if r["certification_id"] == cert["id"]]
    if any(r["status"] == "SUBMITTED" for r in existing):
        E.fail(E.ERR_ACTIVE_RENEWAL_EXISTS, 409,
               "Another renewal application of this certification is SUBMITTED")
    window_open = cert["valid_until"] - timedelta(days=C.RENEWAL_LOOKBACK_DAYS)
    window_close = cert["valid_until"] + timedelta(days=C.RENEWAL_GRACE_DAYS)
    # Renewal window is inclusive at both ends (PRD 2.7).
    if not (window_open <= now() <= window_close):
        E.fail(E.ERR_RENEWAL_WINDOW_NOT_OPEN, 422,
               "Logical clock is outside the renewal window")
    data = body()
    items, total = _parse_evidence_items(data)
    returned = [r for r in existing if r["status"] == "RETURNED"]
    if returned:
        # Resubmission supersedes: reuse the RETURNED application.
        renewal = max(returned, key=lambda r: r.get("_seq", 0))
        renewal["evidence_items"] = items
        renewal["total_hours"] = total
        renewal["status"] = "SUBMITTED"
        touch(renewal)
        return ok(ser.renewal(renewal), 201)
    renewal = {
        "id": new_id(),
        "certification_id": cert["id"],
        "evidence_items": items,
        "total_hours": total,
        "status": "SUBMITTED",
        "review_note": None,
    }
    stamp_new(renewal)
    DB.renewals[renewal["id"]] = renewal
    return ok(ser.renewal(renewal), 201)


@bp.get("/certifications/<certification_id>/renewals")
def list_renewals(certification_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE, C.ROLE_BOARD_ADMIN])
    cert = _get_certification_or_404(certification_id)
    if role == C.ROLE_CANDIDATE and cert["candidate_id"] != uid:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Candidates may read only their own renewal applications")
    limit, offset = pagination_params()
    items = [r for r in DB.renewals.values()
             if r["certification_id"] == cert["id"]]
    page, total = paginate(items, limit, offset)
    return ok_list([ser.renewal(r) for r in page], limit, offset, total)


@bp.post("/renewals/<renewal_id>/review")
def review_renewal(renewal_id):
    _, role = auth_headers()
    require_role(role, [C.ROLE_BOARD_ADMIN])
    renewal = DB.renewals.get(renewal_id)
    if renewal is None:
        E.fail(E.ERR_RENEWAL_NOT_FOUND, 404,
               "Renewal not found: %s" % renewal_id)
    if renewal["status"] not in ("SUBMITTED", "RETURNED"):
        E.fail(E.ERR_RENEWAL_NOT_REVIEWABLE, 409,
               "Renewal must be SUBMITTED or RETURNED to review")
    data = body()
    decision = req_field(data, "decision")
    if decision == "APPROVE":
        if renewal["total_hours"] < C.MIN_RENEWAL_HOURS:
            E.fail(E.ERR_RENEWAL_HOURS_INSUFFICIENT, 422,
                   "Renewal requires at least %s hours of evidence"
                   % C.MIN_RENEWAL_HOURS)
        renewal["status"] = "APPROVED"
        cert = DB.certifications[renewal["certification_id"]]
        cert["status"] = "RENEWED"
        cert["valid_until"] = cert["valid_until"] + timedelta(
            days=C.VALIDITY_DAYS)
        touch(cert)
    elif decision == "RETURN":
        renewal["status"] = "RETURNED"
    else:
        E.fail(E.ERR_INVALID_REQUEST, 400,
               "decision must be APPROVE or RETURN")
    renewal["review_note"] = data.get("note")
    touch(renewal)
    return ok(ser.renewal(renewal))
