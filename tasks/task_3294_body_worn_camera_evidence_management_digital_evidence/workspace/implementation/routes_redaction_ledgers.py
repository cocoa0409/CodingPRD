from flask import Blueprint, request

import db
from errors import (
    err_integrity_failed, err_invalid_state, err_not_found,
    err_segregation_of_duties, err_validation,
)
from helpers import (
    body, get_agency_or_404, get_scoped, new_resource, paginate, reject_unknown,
    require_bool, require_enum, require_int, require_str, success_obj, touch,
    write_audit, write_custody,
)
from middleware import authenticate, require_roles
import services

bp = Blueprint("redaction", __name__)


@bp.route("/agencies/<agency_id>/recordings/<recording_id>/redaction-jobs", methods=["POST"])
def create_redaction_job(agency_id, recording_id):
    actor = authenticate()
    require_roles(actor, "RecordsOfficer", "RedactionTechnician")
    agency = get_agency_or_404(agency_id)
    recording = get_scoped("recordings", agency, recording_id, "Recording")
    if recording["upload_status"] == "INTEGRITY_FAILED":
        raise err_integrity_failed()
    if recording["upload_status"] != "ACTIVE":
        raise err_invalid_state("Redaction jobs may only be created on ACTIVE recordings")
    data = body()
    reject_unknown(data, {"request_reference", "scope_face", "scope_audio", "passes"})
    request_reference = require_str(data, "request_reference")
    scope_face = require_bool(data, "scope_face")
    scope_audio = require_bool(data, "scope_audio")
    passes = require_enum(data, "passes", ["SINGLE_PASS", "MULTI_PASS"])
    if not scope_face and not scope_audio:
        raise err_validation("At least one of scope_face or scope_audio must be true")

    estimate = services.redaction_effort_minutes(
        recording["duration_seconds"], scope_face, scope_audio, passes)
    job = new_resource({
        "agency_id": agency["id"],
        "recording_id": recording["id"],
        "request_reference": request_reference,
        "scope_face": scope_face,
        "scope_audio": scope_audio,
        "passes": passes,
        "estimated_minutes": estimate,
        "actual_minutes": None,
        "status": "QUEUED",
    })
    db.collection("redaction_jobs")[job["id"]] = job
    return success_obj(job, 201)


@bp.route("/agencies/redaction-jobs", methods=["GET"])
def list_redaction_jobs():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "RecordsOfficer", "RedactionTechnician",
                  "Supervisor")
    items = list(db.collection("redaction_jobs").values())
    for param in ("agency_id", "recording_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [j for j in items if str(j.get(param)) == val]
    return paginate(items)


@bp.route("/agencies/redaction-jobs/<job_id>", methods=["GET"])
def get_redaction_job(job_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "RecordsOfficer", "RedactionTechnician",
                  "Supervisor")
    job = db.collection("redaction_jobs").get(job_id)
    if job is None:
        raise err_not_found("Redaction job not found")
    return success_obj(job)


def _job_context(agency_id, job_id):
    actor = authenticate()
    agency = get_agency_or_404(agency_id)
    job = get_scoped("redaction_jobs", agency, job_id, "RedactionJob")
    return actor, agency, job


def _recording_for_job(agency, job):
    recording = db.collection("recordings").get(job["recording_id"])
    if recording is None:
        raise err_not_found("Recording not found")
    return recording


@bp.route("/agencies/<agency_id>/redaction-jobs/<job_id>/start", methods=["POST"])
def start_redaction_job(agency_id, job_id):
    actor, agency, job = _job_context(agency_id, job_id)
    require_roles(actor, "RedactionTechnician")
    recording = _recording_for_job(agency, job)
    from_queued = job["status"] == "QUEUED"
    if job["status"] not in ("QUEUED", "RETURNED"):
        raise err_invalid_state("Only a QUEUED or RETURNED job can be started")
    if recording["upload_status"] != "ACTIVE":
        raise err_invalid_state("Recording must be ACTIVE to start redaction")
    if job["status"] == "RETURNED":
        job["actual_minutes"] = None
    job["status"] = "IN_PROGRESS"
    touch(job)
    if from_queued:
        write_custody(agency["id"], recording["id"], "REDACTION_STARTED", actor)
    return success_obj(job)


@bp.route("/agencies/<agency_id>/redaction-jobs/<job_id>/submit", methods=["POST"])
def submit_redaction_job(agency_id, job_id):
    actor, agency, job = _job_context(agency_id, job_id)
    require_roles(actor, "RedactionTechnician")
    if job["status"] != "IN_PROGRESS":
        raise err_invalid_state("Only an IN_PROGRESS job can be submitted")
    data = body()
    reject_unknown(data, {"actual_minutes"})
    actual = require_int(data, "actual_minutes")
    if actual < 1:
        raise err_validation("actual_minutes must be >= 1")
    job["actual_minutes"] = actual
    job["status"] = "SUBMITTED"
    job["submitted_by"] = actor["user_id"]
    touch(job)
    return success_obj(job)


@bp.route("/agencies/<agency_id>/redaction-jobs/<job_id>/approve", methods=["POST"])
def approve_redaction_job(agency_id, job_id):
    actor, agency, job = _job_context(agency_id, job_id)
    require_roles(actor, "RecordsOfficer")
    if job["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED job can be approved")
    if job.get("submitted_by") is not None and job["submitted_by"] == actor["user_id"]:
        raise err_segregation_of_duties()
    job["status"] = "APPROVED"
    touch(job)
    return success_obj(job)


@bp.route("/agencies/<agency_id>/redaction-jobs/<job_id>/return", methods=["POST"])
def return_redaction_job(agency_id, job_id):
    actor, agency, job = _job_context(agency_id, job_id)
    require_roles(actor, "RecordsOfficer")
    if job["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED job can be returned")
    job["status"] = "RETURNED"
    touch(job)
    return success_obj(job)


@bp.route("/agencies/<agency_id>/redaction-jobs/<job_id>/release", methods=["POST"])
def release_redaction_job(agency_id, job_id):
    actor, agency, job = _job_context(agency_id, job_id)
    require_roles(actor, "RecordsOfficer")
    recording = _recording_for_job(agency, job)
    if job["status"] != "APPROVED":
        raise err_invalid_state("Only an APPROVED job can be released")
    if recording["upload_status"] != "ACTIVE":
        raise err_invalid_state("Recording must be ACTIVE to release redaction")
    job["status"] = "RELEASED"
    touch(job)
    write_custody(agency["id"], recording["id"], "REDACTION_RELEASED", actor)
    write_audit(agency["id"], actor, "REDACTION_RELEASED", "RedactionJob",
                job["id"], "status APPROVED -> RELEASED")
    return success_obj(job)


@bp.route("/agencies/<agency_id>/redaction-jobs/<job_id>/cancel", methods=["POST"])
def cancel_redaction_job(agency_id, job_id):
    actor, agency, job = _job_context(agency_id, job_id)
    require_roles(actor, "RedactionTechnician", "RecordsOfficer")
    if job["status"] not in ("QUEUED", "IN_PROGRESS", "RETURNED"):
        raise err_invalid_state("Only a QUEUED, IN_PROGRESS, or RETURNED job can be cancelled")
    job["status"] = "CANCELLED"
    touch(job)
    return success_obj(job)


# ---------------------------------------------------------------- ledgers

@bp.route("/agencies/custody-events", methods=["GET"])
def list_custody_events():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer", "Officer")
    items = list(db.collection("custody_events").values())
    for param in ("agency_id", "recording_id"):
        val = request.args.get(param)
        if val is not None:
            items = [e for e in items if str(e.get(param)) == val]
    return paginate(items)


@bp.route("/agencies/custody-events/<event_id>", methods=["GET"])
def get_custody_event(event_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer")
    event = db.collection("custody_events").get(event_id)
    if event is None:
        raise err_not_found("Custody event not found")
    return success_obj(event)


@bp.route("/agencies/audit-log", methods=["GET"])
def list_audit_log():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer")
    items = list(db.collection("audit_log").values())
    for param in ("agency_id", "entity_type", "entity_id", "action"):
        val = request.args.get(param)
        if val is not None:
            items = [e for e in items if str(e.get(param)) == val]
    return paginate(items)


@bp.route("/agencies/audit-log/<entry_id>", methods=["GET"])
def get_audit_entry(entry_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer")
    entry = db.collection("audit_log").get(entry_id)
    if entry is None:
        raise err_not_found("Audit log entry not found")
    return success_obj(entry)
