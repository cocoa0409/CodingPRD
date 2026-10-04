"""Compliance inspections, findings, corrective actions and diversion cases."""
from flask import Blueprint, request

import db
from constants import (
    DETECTION_SOURCES,
    INSPECTION_TYPES,
    REQUIREMENT_CODES,
    SEVERITIES,
)
from errors import ApiError
from response import ok_array_paged, ok_object, paginate_sorted, parse_pagination
from routes.common import context, path_patient, path_program
from services import compliance, entity
from validation import date_field, text_field

bp = Blueprint("compliance", __name__)

INSPECTION_ROLES = ["ProgramAdministrator", "MedicalDirector", "RegulatoryAuditor"]


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------
@bp.route("/otp/compliance-inspections", methods=["POST"])
def create_inspection():
    context(["RegulatoryAuditor"])
    body = request.get_json(silent=True) or {}
    program_id = text_field(body, "program_id")
    path_program(program_id)
    inspection_type = text_field(body, "inspection_type")
    if inspection_type not in INSPECTION_TYPES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "inspection_type must be %s" % ", ".join(INSPECTION_TYPES),
        )
    row = entity.make_inspection(
        program_id,
        text_field(body, "inspecting_agency"),
        date_field(body, "scheduled_date"),
        inspection_type,
    )
    db.compliance_inspections[row["id"]] = row
    return ok_object(entity.serialize_inspection(row), 201)


@bp.route("/otp/compliance-inspections", methods=["GET"])
def list_inspections():
    context(INSPECTION_ROLES)
    rows = list(db.compliance_inspections.values())
    for name in ("program_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged(
        [entity.serialize_inspection(r) for r in page], limit, offset, total
    )


@bp.route("/otp/compliance-inspections/<inspection_id>", methods=["GET"])
def read_inspection(inspection_id):
    context(INSPECTION_ROLES)
    row = compliance.inspection_of(inspection_id)
    return ok_object(entity.serialize_inspection(row))


@bp.route("/otp/compliance-inspections/<inspection_id>/readiness", methods=["GET"])
def readiness(inspection_id):
    context(INSPECTION_ROLES)
    row = compliance.inspection_of(inspection_id)
    program = db.programs.get(row.get("program_id"))
    score, tier, terms = compliance.compute_readiness(program)
    return ok_object(
        {
            "readiness_score": score,
            "readiness_tier": tier,
            "open_critical_findings": terms["open_critical"],
            "open_diversion_cases": terms["open_diversion_cases"],
        }
    )


@bp.route("/otp/compliance-inspections/<inspection_id>/begin", methods=["POST"])
def begin(inspection_id):
    actor = context(["RegulatoryAuditor"])
    row = compliance.inspection_of(inspection_id)
    compliance.begin_inspection(row, actor)
    return ok_object(entity.serialize_inspection(row))


@bp.route("/otp/compliance-inspections/<inspection_id>/complete", methods=["POST"])
def complete(inspection_id):
    actor = context(["RegulatoryAuditor"])
    row = compliance.inspection_of(inspection_id)
    compliance.complete_inspection(row, actor)
    return ok_object(entity.serialize_inspection(row))


@bp.route("/otp/compliance-inspections/<inspection_id>/cancel", methods=["POST"])
def cancel(inspection_id):
    actor = context(["RegulatoryAuditor"])
    row = compliance.inspection_of(inspection_id)
    compliance.cancel_inspection(row, actor)
    return ok_object(entity.serialize_inspection(row))


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
@bp.route("/otp/compliance-findings", methods=["POST"])
def create_finding():
    actor = context(["RegulatoryAuditor"])
    body = request.get_json(silent=True) or {}
    inspection = compliance.inspection_of(text_field(body, "inspection_id"))
    requirement_code = text_field(body, "requirement_code")
    if requirement_code not in REQUIREMENT_CODES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "requirement_code must be one of %s" % ", ".join(REQUIREMENT_CODES),
        )
    severity = text_field(body, "severity")
    if severity not in SEVERITIES:
        raise ApiError("ERR_INVALID_REQUEST", "severity must be MINOR, MAJOR or CRITICAL")
    row = compliance.create_finding(inspection, requirement_code, severity, actor)
    return ok_object(entity.serialize_finding(row), 201)


@bp.route("/otp/compliance-findings", methods=["GET"])
def list_findings():
    context(INSPECTION_ROLES)
    rows = list(db.compliance_findings.values())
    for name in ("inspection_id", "program_id", "status", "severity"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged([entity.serialize_finding(r) for r in page], limit, offset, total)


@bp.route("/otp/compliance-findings/<finding_id>", methods=["GET"])
def read_finding(finding_id):
    context(INSPECTION_ROLES)
    row = compliance.finding_of(finding_id)
    return ok_object(entity.serialize_finding(row))


# ---------------------------------------------------------------------------
# Corrective actions
# ---------------------------------------------------------------------------
@bp.route("/otp/corrective-actions", methods=["POST"])
def create_action():
    actor = context(["ProgramAdministrator"])
    body = request.get_json(silent=True) or {}
    program_id = text_field(body, "program_id")
    path_program(program_id)
    finding_id = body.get("finding_id")
    if finding_id:
        compliance.finding_of(finding_id)
    severity = text_field(body, "severity")
    if severity not in SEVERITIES:
        raise ApiError("ERR_INVALID_REQUEST", "severity must be MINOR, MAJOR or CRITICAL")
    row = compliance.create_action(
        program_id,
        finding_id,
        severity,
        body.get("plan_text"),
        date_field(body, "due_date"),
        actor,
    )
    return ok_object(entity.serialize_action(row), 201)


@bp.route("/otp/corrective-actions", methods=["GET"])
def list_actions():
    context(INSPECTION_ROLES)
    rows = list(db.corrective_actions.values())
    for name in ("program_id", "finding_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged([entity.serialize_action(r) for r in page], limit, offset, total)


@bp.route("/otp/corrective-actions/<action_id>", methods=["GET"])
def read_action(action_id):
    context(INSPECTION_ROLES)
    row = compliance.action_of(action_id)
    return ok_object(entity.serialize_action(row))


@bp.route("/otp/corrective-actions/<action_id>/implement", methods=["POST"])
def implement(action_id):
    actor = context(["ProgramAdministrator"])
    row = compliance.action_of(action_id)
    compliance.implement_action(row, actor)
    return ok_object(entity.serialize_action(row))


@bp.route("/otp/corrective-actions/<action_id>/verify", methods=["POST"])
def verify(action_id):
    actor = context(["RegulatoryAuditor"])
    row = compliance.action_of(action_id)
    compliance.verify_action(row, actor)
    return ok_object(entity.serialize_action(row))


@bp.route("/otp/corrective-actions/<action_id>/cancel", methods=["POST"])
def cancel_action(action_id):
    actor = context(["MedicalDirector"])
    row = compliance.action_of(action_id)
    compliance.cancel_action(row, actor)
    return ok_object(entity.serialize_action(row))


# ---------------------------------------------------------------------------
# Diversion cases
# ---------------------------------------------------------------------------
@bp.route("/otp/diversion-cases", methods=["POST"])
def create_case():
    actor = context(["RegulatoryAuditor", "Nurse", "ProgramAdministrator"])
    body = request.get_json(silent=True) or {}
    program_id = text_field(body, "program_id")
    path_program(program_id)
    patient = path_patient(text_field(body, "patient_id"))
    related = body.get("related_dose_dispense_id")
    if related and related not in db.dose_dispenses:
        raise ApiError("ERR_DOSE_NOT_FOUND", "No DoseDispense with the supplied id")
    detection_source = text_field(body, "detection_source")
    if detection_source not in DETECTION_SOURCES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "detection_source must be one of %s" % ", ".join(DETECTION_SOURCES),
        )
    severity = text_field(body, "severity")
    if severity not in SEVERITIES:
        raise ApiError("ERR_INVALID_REQUEST", "severity must be MINOR, MAJOR or CRITICAL")
    row = compliance.create_case(
        program_id, patient, related, detection_source, severity, actor
    )
    return ok_object(entity.serialize_diversion_case(row), 201)


@bp.route("/otp/diversion-cases", methods=["GET"])
def list_cases():
    context(INSPECTION_ROLES)
    rows = list(db.diversion_cases.values())
    for name in (
        "program_id",
        "patient_id",
        "related_dose_dispense_id",
        "opened_by_user_id",
        "status",
    ):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged(
        [entity.serialize_diversion_case(r) for r in page], limit, offset, total
    )


@bp.route("/otp/diversion-cases/<case_id>", methods=["GET"])
def read_case(case_id):
    context(INSPECTION_ROLES)
    row = compliance.case_of(case_id)
    return ok_object(entity.serialize_diversion_case(row))


@bp.route("/otp/diversion-cases/<case_id>/begin-review", methods=["POST"])
def begin_review(case_id):
    actor = context(["RegulatoryAuditor"])
    row = compliance.case_of(case_id)
    compliance.begin_review(row, actor)
    return ok_object(entity.serialize_diversion_case(row))


@bp.route("/otp/diversion-cases/<case_id>/confirm", methods=["POST"])
def confirm(case_id):
    actor = context(["RegulatoryAuditor"])
    row = compliance.case_of(case_id)
    body = request.get_json(silent=True) or {}
    compliance.confirm(row, body.get("outcome_summary"), actor)
    return ok_object(entity.serialize_diversion_case(row))


@bp.route("/otp/diversion-cases/<case_id>/unsubstantiate", methods=["POST"])
def unsubstantiate(case_id):
    actor = context(["RegulatoryAuditor"])
    row = compliance.case_of(case_id)
    body = request.get_json(silent=True) or {}
    compliance.unsubstantiate(row, body.get("outcome_summary"), actor)
    return ok_object(entity.serialize_diversion_case(row))


@bp.route("/otp/diversion-cases/<case_id>/close", methods=["POST"])
def close_case(case_id):
    actor = context(["RegulatoryAuditor"])
    row = compliance.case_of(case_id)
    compliance.close_case(row, actor)
    return ok_object(entity.serialize_diversion_case(row))