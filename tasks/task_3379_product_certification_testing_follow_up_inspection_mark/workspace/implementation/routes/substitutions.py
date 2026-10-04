"""Substitution request endpoints (PRD 3.5)."""
from flask import Blueprint

import clock
import db
from constants import ROLE_REP, ROLE_REVIEWER, SUBSTITUTION_OUTCOMES
from errors import (
    ApiError, ERR_ALREADY_TERMINAL, ERR_CERTIFICATION_NOT_ACTIVE,
    ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_STALE_VERSION,
    ERR_UNKNOWN_COMPONENT_SLOT,
)
from middleware import (
    any_authenticated, check_rep_ownership, require_roles,
)
from response import paginated_list, success
from routes.certifications import get_certification_or_404
from routes.projects import _create_revision
from validation import body, req_enum, req_int, req_object, req_str
import validation as v

bp = Blueprint("substitutions", __name__)


def get_substitution_or_404(request_id):
    sub = db.substitution_requests.get(request_id)
    if sub is None:
        raise ApiError(ERR_NOT_FOUND, "substitution request not found")
    return sub


@bp.post("/certifications/<certification_id>/substitution-requests")
@require_roles(ROLE_REP)
def create_substitution_request(certification_id, user_id, role):
    cert = get_certification_or_404(certification_id)
    check_rep_ownership(user_id, role, cert["manufacturer_id"])
    if cert["status"] != "ACTIVE":
        raise ApiError(ERR_CERTIFICATION_NOT_ACTIVE,
                       "substitutions require an ACTIVE certification")
    payload = body(required=True)
    slot = req_str(payload, "slot")
    proposed = req_object(payload, "proposed_component")
    proposed_component = {
        "component_name": v.req_str(proposed, "component_name"),
        "material": v.req_str(proposed, "material"),
        "part_number": v.req_str(proposed, "part_number"),
        "rating": proposed.get("rating"),
    }
    rationale = req_str(payload, "rationale")
    sub = db.new_entity(db.substitution_requests, {
        "certification_id": certification_id,
        "slot": slot,
        "proposed_component": proposed_component,
        "rationale": rationale,
        "status": "SUBMITTED",
        "decided_by": None,
        "decided_on": None,
    })
    return success(sub, status=201)


@bp.get("/certifications/<certification_id>/substitution-requests")
@any_authenticated
def list_substitution_requests(certification_id, user_id, role):
    get_certification_or_404(certification_id)
    items = [s for s in db.sorted_items(db.substitution_requests)
             if s["certification_id"] == certification_id]
    page, pagination = paginated_list(items)
    return success(page, pagination=pagination)


@bp.post("/substitution-requests/<request_id>/decide")
@require_roles(ROLE_REVIEWER)
def decide_substitution(request_id, user_id, role):
    sub = get_substitution_or_404(request_id)
    payload = body(required=True)
    outcome = req_enum(payload, "outcome", SUBSTITUTION_OUTCOMES)

    if sub["status"] in ("REJECTED", "IMPLEMENTED"):
        raise ApiError(ERR_ALREADY_TERMINAL,
                       "substitution request is %s (terminal)" % sub["status"])
    if sub["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE,
                       "substitution request is %s, not SUBMITTED" % sub["status"])

    if outcome == "APPROVE":
        cert = db.certifications[sub["certification_id"]]
        pinned = db.construction_records[cert["construction_record_id"]]
        slots = {c["slot"] for c in pinned["components"]}
        if sub["slot"] not in slots:
            raise ApiError(ERR_UNKNOWN_COMPONENT_SLOT,
                           "slot %s is not in the pinned construction record"
                           % sub["slot"])
        sub["status"] = "APPROVED"
    else:
        sub["status"] = "REJECTED"

    sub["decided_by"] = user_id
    sub["decided_on"] = clock.now()
    db.mutate(sub)
    return success(sub)


@bp.post("/substitution-requests/<request_id>/implement")
@require_roles(ROLE_REP)
def implement_substitution(request_id, user_id, role):
    sub = get_substitution_or_404(request_id)
    cert = db.certifications[sub["certification_id"]]
    check_rep_ownership(user_id, role, cert["manufacturer_id"])
    payload = body(required=True)
    expected_version = req_int(payload, "expected_certification_version")

    # OCC (pipeline stage 5) precedes state admissibility (stage 6).
    if expected_version != cert["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_certification_version does not match the "
                       "certification version")
    if cert["status"] != "ACTIVE":
        raise ApiError(ERR_CERTIFICATION_NOT_ACTIVE,
                       "implementation requires an ACTIVE certification")
    if sub["status"] in ("REJECTED", "IMPLEMENTED"):
        raise ApiError(ERR_ALREADY_TERMINAL,
                       "substitution request is %s (terminal)" % sub["status"])
    if sub["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE,
                       "substitution request is %s, not APPROVED" % sub["status"])

    # Freeze a new construction revision on the project: the pinned components
    # with the substituted slot replaced by the proposed component.
    project = db.projects[cert["project_id"]]
    pinned = db.construction_records[cert["construction_record_id"]]
    new_components = []
    for component in pinned["components"]:
        if component["slot"] == sub["slot"]:
            new_components.append({
                "slot": sub["slot"],
                "component_name": sub["proposed_component"]["component_name"],
                "material": sub["proposed_component"]["material"],
                "part_number": sub["proposed_component"]["part_number"],
                "rating": sub["proposed_component"].get("rating"),
            })
        else:
            new_components.append(dict(component))
    record = _create_revision(project, new_components)

    cert["construction_record_id"] = record["id"]
    cert["construction_record_revision"] = record["revision_no"]
    cert["permitted_variations"].append({
        "slot": sub["slot"],
        "allowed_alternates": [sub["proposed_component"]["part_number"]],
    })
    db.mutate(cert)  # the single standard mutation bump of this write

    sub["status"] = "IMPLEMENTED"
    db.mutate(sub)
    return success(sub)
