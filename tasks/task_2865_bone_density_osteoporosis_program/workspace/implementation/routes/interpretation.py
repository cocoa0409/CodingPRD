"""Fracture risk assessment, diagnostic reports, finalization and amendment."""
from flask import Blueprint, request

import calc
import cascades
import queries
import reporting
import validate
from db import base_record, db, now_iso, public, today, touch
from errors import ApiError
from middleware import (INTERPRETING_PHYSICIAN, PATIENT_PORTAL_USER, PROGRAM_ADMIN,
                        QUALITY_REVIEWER, TECHNOLOGIST, actor_id, endpoint,
                        enforce_patient_scope, is_portal)
from response import created, ok, paginated

bp = Blueprint("interpretation", __name__)

REPORT_INPUT_FIELDS = ("frax_assessment_id", "non_comparability_note", "vfa_narrative")


def _filtered(rows, filters):
    result = rows
    for param, field in filters.items():
        wanted = request.args.get(param)
        if wanted is not None and wanted != "":
            result = [row for row in result if str(row.get(field)) == wanted]
    return result


def _patient_of_report(report):
    session = db.scan_sessions.get(report["scan_session_id"])
    return None if session is None else session["patient_id"]


@bp.post("/frax-assessments")
@endpoint(INTERPRETING_PHYSICIAN)
def create_frax_assessment():
    body = validate.body()
    patient_id = validate.string(body, "patient_id")
    profile_id = validate.string(body, "risk_factor_profile_id")
    session_id = validate.string(body, "scan_session_id", required=False)

    profile = queries.fetch("risk_factor_profiles", profile_id)
    patient = queries.patient(patient_id)
    session = queries.session(session_id) if session_id is not None else None

    if profile["patient_id"] != patient_id or \
            (session is not None and session["patient_id"] != patient_id):
        raise ApiError("ERR_FRAX_PATIENT_MISMATCH",
                       "The referenced records belong to a different patient.")
    if profile["status"] != "ACTIVE":
        raise ApiError("ERR_RISK_PROFILE_NOT_ACTIVE", "The risk factor profile is SUPERSEDED.")

    femoral_neck_t = None
    if session is not None:
        row = queries.measurement_at(session_id, "FEMORAL_NECK")
        if row is None or not row["site_usable_for_diagnosis"]:
            raise ApiError("ERR_FEMORAL_NECK_REQUIRED",
                           "The session carries no usable femoral neck measurement.", 422)
        femoral_neck_t = row["t_score"]

    scored = calc.frax_points(patient, profile, femoral_neck_t, today())
    record = base_record()
    record.update({
        "patient_id": patient_id,
        "risk_factor_profile_id": profile_id,
        "scan_session_id": session_id,
        "variant": "WITH_BMD" if session is not None else "WITHOUT_BMD",
        "assessed_by_user_id": actor_id(),
        "assessed_at_utc": now_iso(),
    })
    record.update(scored)
    db.frax_assessments[record["id"]] = record
    return created(public(record))


@bp.get("/frax-assessments/<assessment_id>")
@endpoint(PROGRAM_ADMIN, INTERPRETING_PHYSICIAN)
def get_frax_assessment(assessment_id):
    return ok(public(queries.fetch("frax_assessments", assessment_id)))


@bp.get("/frax-assessments")
@endpoint(PROGRAM_ADMIN, INTERPRETING_PHYSICIAN)
def list_frax_assessments():
    rows = _filtered(list(db.frax_assessments.values()), {
        "patient_id": "patient_id",
        "risk_factor_profile_id": "risk_factor_profile_id",
        "scan_session_id": "scan_session_id",
        "variant": "variant",
    })
    rows.sort(key=lambda row: (row["assessed_at_utc"], row["created_at"], row["_seq"]),
              reverse=True)
    return paginated(rows, public)


def _blocking_report(session_id, exclude_id=None):
    for row in queries.reports_of_session(session_id):
        if row["id"] == exclude_id:
            continue
        if row["status"] in ("DRAFT", "FINALIZED"):
            return row
    return None


def _check_frax_patient(frax, session):
    if frax is not None and frax["patient_id"] != session["patient_id"]:
        raise ApiError("ERR_FRAX_PATIENT_MISMATCH",
                       "The assessment belongs to a different patient than the session.")


@bp.post("/diagnostic-reports")
@endpoint(INTERPRETING_PHYSICIAN)
def create_diagnostic_report():
    body = validate.body()
    session_id = validate.string(body, "scan_session_id")
    frax_id = validate.string(body, "frax_assessment_id", required=False)
    note = validate.string(body, "non_comparability_note", required=False, max_len=480)
    narrative = validate.string(body, "vfa_narrative", required=False, max_len=480)

    session = queries.session(session_id)
    frax = queries.fetch("frax_assessments", frax_id) if frax_id is not None else None

    if session["acquisition_status"] not in ("SUBMITTED", "ARCHIVED"):
        raise ApiError("ERR_SESSION_NOT_SUBMITTED", "The session is not SUBMITTED.")
    if session["acquisition_status"] == "ARCHIVED":
        raise ApiError("ERR_SESSION_ARCHIVED", "The session is archived.")
    if _blocking_report(session_id) is not None:
        raise ApiError("ERR_REPORT_ALREADY_EXISTS",
                       "A report on that session already exists.")
    _check_frax_patient(frax, session)

    record = base_record()
    record.update({
        "scan_session_id": session_id,
        "frax_assessment_id": frax_id,
        "amends_report_id": None,
        "status": "DRAFT",
        "non_comparability_note": note,
        "vfa_narrative": narrative,
        "amendment_reason": None,
        "finalized_at_utc": None,
        "finalized_by_user_id": None,
    })
    reporting.derive(record, session)
    db.diagnostic_reports[record["id"]] = record
    return created(public(record))


@bp.patch("/diagnostic-reports/<report_id>")
@endpoint(INTERPRETING_PHYSICIAN)
def patch_diagnostic_report(report_id):
    body = validate.body()
    frax_id = validate.string(body, "frax_assessment_id", required=False)
    note = validate.string(body, "non_comparability_note", required=False, max_len=480)
    narrative = validate.string(body, "vfa_narrative", required=False, max_len=480)

    report = queries.report(report_id)
    frax = queries.fetch("frax_assessments", frax_id) if frax_id is not None else None
    if report["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_NOT_DRAFT", "The report is not a DRAFT.")

    session = db.scan_sessions[report["scan_session_id"]]
    _check_frax_patient(frax, session)

    if validate.present(body, "frax_assessment_id"):
        report["frax_assessment_id"] = frax_id
    if validate.present(body, "non_comparability_note"):
        report["non_comparability_note"] = note
    if validate.present(body, "vfa_narrative"):
        report["vfa_narrative"] = narrative
    reporting.derive(report, session)
    touch(report)
    return ok(public(report))


@bp.post("/diagnostic-reports/<report_id>/finalize")
@endpoint(INTERPRETING_PHYSICIAN)
def finalize_diagnostic_report(report_id):
    report = queries.report(report_id)
    if report["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_NOT_DRAFT", "The report is not a DRAFT.")
    session = db.scan_sessions[report["scan_session_id"]]
    if session["review_status"] not in ("ACCEPTED", "ACCEPTED_WITH_LIMITATION"):
        raise ApiError("ERR_POSITIONING_NOT_ACCEPTED",
                       "The session's positioning review has not been accepted.")
    reporting.audit_elements(report, session)
    if not report["required_elements_complete"]:
        raise ApiError("ERR_REPORT_ELEMENTS_INCOMPLETE",
                       "The report is missing a mandatory narrative element.", 422)

    patient = db.patients[session["patient_id"]]
    cascades.cascade_a_finalize(report, session, patient, actor_id())
    return ok(public(report))


@bp.post("/diagnostic-reports/<report_id>/amend")
@endpoint(INTERPRETING_PHYSICIAN)
def amend_diagnostic_report(report_id):
    body = validate.body()
    reason = validate.string(body, "amendment_reason", min_len=1, max_len=240)

    report = queries.report(report_id)
    if report["status"] != "FINALIZED":
        raise ApiError("ERR_REPORT_NOT_FINALIZED", "The report is not FINALIZED.")
    session = db.scan_sessions[report["scan_session_id"]]
    if _blocking_report(session["id"], exclude_id=report_id) is not None:
        raise ApiError("ERR_REPORT_ALREADY_EXISTS",
                       "Another report on that session is already open.")

    report["status"] = "AMENDED"
    touch(report)
    if session["acquisition_status"] == "ARCHIVED":
        session["acquisition_status"] = "SUBMITTED"
        touch(session)
    patient = db.patients[session["patient_id"]]
    cascades.compensate_amendment(patient)

    successor = base_record()
    successor.update({
        "scan_session_id": session["id"],
        "frax_assessment_id": report["frax_assessment_id"],
        "amends_report_id": report_id,
        "status": "DRAFT",
        "non_comparability_note": report["non_comparability_note"],
        "vfa_narrative": report["vfa_narrative"],
        "amendment_reason": reason,
        "finalized_at_utc": None,
        "finalized_by_user_id": None,
    })
    reporting.derive(successor, session)
    db.diagnostic_reports[successor["id"]] = successor
    return created(public(successor))


@bp.get("/diagnostic-reports/<report_id>")
@endpoint(PROGRAM_ADMIN, TECHNOLOGIST, QUALITY_REVIEWER, INTERPRETING_PHYSICIAN,
          PATIENT_PORTAL_USER)
def get_diagnostic_report(report_id):
    report = queries.report(report_id)
    if is_portal():
        enforce_patient_scope(_patient_of_report(report))
    return ok(public(report))


@bp.get("/diagnostic-reports")
@endpoint(PROGRAM_ADMIN, TECHNOLOGIST, QUALITY_REVIEWER, INTERPRETING_PHYSICIAN,
          PATIENT_PORTAL_USER)
def list_diagnostic_reports():
    rows = _filtered(list(db.diagnostic_reports.values()), {
        "scan_session_id": "scan_session_id",
        "frax_assessment_id": "frax_assessment_id",
        "amends_report_id": "amends_report_id",
        "status": "status",
    })
    if is_portal():
        rows = [row for row in rows if _patient_of_report(row) == actor_id()]
    rows.sort(key=lambda row: (row["created_at"], row["_seq"]))
    return paginated(rows, public)
