"""Follow-up inspection endpoints (PRD 3.6): schedule, complete, void."""
from datetime import timedelta

from flask import Blueprint

import clock
import db
from constants import (
    MIN_INSPECTION_GAP_DAYS, ROLE_COMPLIANCE, ROLE_INSPECTOR, SEVERITIES,
)
from errors import (
    ApiError, ERR_ALREADY_TERMINAL, ERR_FINDING_CERTIFICATION_MISMATCH,
    ERR_INSPECTION_DATE_PAST, ERR_INSPECTION_GAP_VIOLATION,
    ERR_INVALID_STATE, ERR_NOT_FOUND,
)
from middleware import any_authenticated, require_roles
from response import paginated_list, success
from routes.manufacturers import get_factory_or_404
from services import lifecycle
from validation import body, opt_str, req_datetime, req_list, req_str
import validation as v

bp = Blueprint("inspections", __name__)

_RESULT_BY_SEVERITY = {
    "CRITICAL": "CRITICAL_NC",
    "MAJOR": "MAJOR_NC",
    "MINOR": "MINOR_NC",
}
_SEVERITY_RANK = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}


def get_inspection_or_404(inspection_id):
    inspection = db.inspections.get(inspection_id)
    if inspection is None:
        raise ApiError(ERR_NOT_FOUND, "inspection not found")
    return inspection


@bp.post("/factories/<factory_id>/inspections")
@require_roles(ROLE_INSPECTOR)
def schedule_inspection(factory_id, user_id, role):
    get_factory_or_404(factory_id)
    payload = body(required=True)
    scheduled_for = req_datetime(payload, "scheduled_for")

    if scheduled_for < clock.now():
        raise ApiError(ERR_INSPECTION_DATE_PAST,
                       "scheduled_for is before the current logical time")
    gap = timedelta(days=MIN_INSPECTION_GAP_DAYS)
    for other in db.inspections.values():
        if other["factory_id"] != factory_id or other["status"] == "VOIDED":
            continue
        if abs(scheduled_for - other["scheduled_for"]) < gap:
            raise ApiError(ERR_INSPECTION_GAP_VIOLATION,
                           "within %d days of another inspection"
                           % MIN_INSPECTION_GAP_DAYS)

    inspection = db.new_entity(db.inspections, {
        "factory_id": factory_id,
        "scheduled_for": scheduled_for,
        "inspector_ref": user_id,
        "completed_on": None,
        "result": None,
        "findings": [],
        "status": "SCHEDULED",
    })
    return success(inspection, status=201)


@bp.get("/factories/<factory_id>/inspections")
@any_authenticated
def list_inspections(factory_id, user_id, role):
    get_factory_or_404(factory_id)
    items = [i for i in db.sorted_items(db.inspections)
             if i["factory_id"] == factory_id]
    page, pagination = paginated_list(items)
    return success(page, pagination=pagination)


@bp.post("/inspections/<inspection_id>/complete")
@require_roles(ROLE_INSPECTOR)
def complete_inspection(inspection_id, user_id, role):
    inspection = get_inspection_or_404(inspection_id)
    payload = body(required=True)
    raw_findings = req_list(payload, "findings")

    if inspection["status"] == "VOIDED":
        raise ApiError(ERR_ALREADY_TERMINAL, "inspection is VOIDED (terminal)")
    if inspection["status"] not in ("SCHEDULED", "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE,
                       "inspection is %s" % inspection["status"])

    findings = []
    for entry in raw_findings:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "findings entries must be objects")
        finding = {
            "finding_ref": v.req_str(entry, "finding_ref"),
            "severity": v.req_enum(entry, "severity", SEVERITIES),
            "description": v.req_str(entry, "description"),
        }
        certification_id = entry.get("certification_id")
        if certification_id is not None:
            if not isinstance(certification_id, str):
                raise ApiError("ERR_INVALID_REQUEST",
                               "finding certification_id must be a string")
            cert = db.certifications.get(certification_id)
            if cert is None:
                raise ApiError(ERR_NOT_FOUND,
                               "finding certification not found")
            if cert["factory_id"] != inspection["factory_id"]:
                raise ApiError(ERR_FINDING_CERTIFICATION_MISMATCH,
                               "finding certification does not belong to the "
                               "inspected factory")
            finding["certification_id"] = certification_id
        findings.append(finding)

    inspection["findings"] = findings
    inspection["completed_on"] = clock.now()
    inspection["status"] = "COMPLETED"
    if findings:
        worst = max(findings, key=lambda f: _SEVERITY_RANK[f["severity"]])
        inspection["result"] = _RESULT_BY_SEVERITY[worst["severity"]]
    else:
        inspection["result"] = "CONFORMING"
    db.mutate(inspection)

    factory = db.factories[inspection["factory_id"]]
    lifecycle.recompute_factory(factory, event="complete", inspection=inspection)

    # Every CRITICAL finding naming a certification suspends it (if ACTIVE)
    # with a CRITICAL_FINDING cause, cascading to its mark licenses.
    for finding in findings:
        if finding["severity"] != "CRITICAL" or "certification_id" not in finding:
            continue
        cert = db.certifications[finding["certification_id"]]
        lifecycle.suspend_certification(
            cert, "CRITICAL_FINDING:%s" % finding["finding_ref"])

    return success(inspection)


@bp.post("/inspections/<inspection_id>/void")
@require_roles(ROLE_COMPLIANCE)
def void_inspection(inspection_id, user_id, role):
    inspection = get_inspection_or_404(inspection_id)
    payload = body(required=True)
    req_str(payload, "reason")

    if inspection["status"] == "VOIDED":
        raise ApiError(ERR_ALREADY_TERMINAL, "inspection is already VOIDED")
    if inspection["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE,
                       "only a COMPLETED inspection can be voided")

    inspection["status"] = "VOIDED"
    db.mutate(inspection)

    factory = db.factories[inspection["factory_id"]]
    lifecycle.recompute_factory(factory, event="void", inspection=inspection)
    lifecycle.compensate_voided_inspection(inspection)
    return success(inspection)
