from flask import Blueprint, request

import db
from errors import (
    err_category_required, err_device_not_docked, err_integrity_failed,
    err_invalid_state, err_no_active_policy, err_not_found, err_unauthorized,
    err_validation,
)
from helpers import (
    SYSTEM_ACTOR, active_policy, body, get_agency_or_404, get_scoped, iso_now,
    new_resource, paginate, parse_dt, reject_unknown, require_enum,
    require_hash, require_int, require_str, success_obj, touch, write_audit,
    write_custody,
)
from middleware import authenticate, compute_content_hash, require_roles
import services

bp = Blueprint("evidence", __name__)


def _run_integrity_check(recording, actor, payload_hash=None):
    """Run one integrity verification pass: increments count, writes custody,
    moves RECEIVED -> INTEGRITY_VERIFIED or INTEGRITY_FAILED."""
    server_hash = payload_hash if payload_hash is not None else recording["content_hash_sha256"]
    recording["integrity_check_count"] = recording.get("integrity_check_count", 0) + 1
    if server_hash == recording["content_hash_sha256"]:
        recording["upload_status"] = "INTEGRITY_VERIFIED"
        write_custody(recording["agency_id"], recording["id"], "HASH_VERIFIED",
                      actor, hash_at_event=recording["content_hash_sha256"])
    else:
        recording["upload_status"] = "INTEGRITY_FAILED"
        write_custody(recording["agency_id"], recording["id"], "HASH_MISMATCH",
                      actor, hash_at_event=recording["content_hash_sha256"])
    return recording["upload_status"] == "INTEGRITY_VERIFIED"


def _activate_recording(recording, agency, policy, actor):
    """INTEGRITY_VERIFIED -> ACTIVE: retention, storage, sampling, officer metrics."""
    recording["upload_status"] = "ACTIVE"
    services.compute_recording_retention(recording)

    officer = db.collection("officers").get(recording["officer_id"])
    if officer is not None:
        officer["recordings_uploaded_count"] = officer.get("recordings_uploaded_count", 0) + 1
        if policy is not None:
            services.apply_supervisor_sampling(recording, policy, officer)
        services.recompute_officer_metrics(officer)
        touch(officer)
    else:
        recording["review_status"] = "NOT_FLAGGED"

    services.touch_agency(agency)
    touch(recording)
    write_custody(agency["id"], recording["id"], "UPLOADED", actor)
    write_audit(agency["id"], actor, "RECORDING_UPLOADED", "Recording",
                recording["id"], "recording became ACTIVE")


@bp.route("/agencies/<agency_id>/recordings", methods=["POST"])
def upload_recording(agency_id):
    actor = authenticate()
    require_roles(actor, "Officer")
    agency = get_agency_or_404(agency_id)
    data = body()
    reject_unknown(data, {"device_id", "trigger_code", "duration_seconds",
                          "size_bytes", "recorded_at", "content_hash_sha256",
                          "category"})
    device_id = require_str(data, "device_id")
    device = db.collection("devices").get(device_id)
    if device is None or device["agency_id"] != agency["id"]:
        raise err_not_found("Device not found")
    if device.get("assigned_officer_id") != actor["user_id"]:
        raise err_unauthorized("Device is not assigned to the calling officer")
    if device["dock_status"] != "DOCKED":
        raise err_device_not_docked()

    policy = active_policy(agency["id"])
    if policy is None:
        raise err_no_active_policy()

    trigger = require_str(data, "trigger_code")
    duration = require_int(data, "duration_seconds")
    size = require_int(data, "size_bytes")
    recorded_at_raw = require_str(data, "recorded_at")
    recorded_dt = parse_dt(recorded_at_raw)
    if recorded_dt is None:
        raise err_validation("recorded_at must be an ISO 8601 timestamp")
    content_hash = require_hash(data, "content_hash_sha256")
    category = require_enum(data, "category", services.CATEGORIES, required=False)

    if duration < 1 or duration > 14400:
        raise err_validation("duration_seconds must be 1..14400")
    if size < 1:
        raise err_validation("size_bytes must be >= 1")
    now_dt = parse_dt(iso_now())
    if recorded_dt > now_dt:
        raise err_validation("recorded_at must not be in the future")
    if trigger not in policy["recording_triggers"]:
        raise err_validation("trigger_code not in the ACTIVE policy's recording_triggers")
    if policy["tagging_required"] and category is None:
        raise err_category_required()

    recording = new_resource({
        "agency_id": agency["id"],
        "device_id": device["id"],
        "officer_id": device["assigned_officer_id"],
        "trigger_code": trigger,
        "duration_seconds": duration,
        "size_bytes": size,
        "recorded_at": recorded_at_raw,
        "content_hash_sha256": content_hash,
        "category": category,
        "upload_status": "RECEIVED",
        "review_status": "NOT_FLAGGED",
        "retention_due_at": None,
        "legal_hold_count": 0,
        "integrity_check_count": 0,
    })
    db.collection("recordings")[recording["id"]] = recording

    payload_hash = compute_content_hash(data.get("payload"))
    ok = _run_integrity_check(recording, actor, payload_hash=payload_hash)

    if ok and category is not None:
        _activate_recording(recording, agency, policy, actor)
    else:
        touch(recording)
    return success_obj(recording, 201)


@bp.route("/agencies/recordings", methods=["GET"])
def list_recordings():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer",
                  "RedactionTechnician", "Officer")
    items = list(db.collection("recordings").values())
    for param in ("agency_id", "officer_id", "device_id", "upload_status",
                  "review_status", "category"):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if str(r.get(param)) == val]
    return paginate(items)


@bp.route("/agencies/<agency_id>/recordings/<recording_id>", methods=["GET"])
def get_recording(agency_id, recording_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer",
                  "RedactionTechnician", "Officer")
    agency = get_agency_or_404(agency_id)
    recording = get_scoped("recordings", agency, recording_id, "Recording")
    return success_obj(recording)


@bp.route("/agencies/recordings/<recording_id>", methods=["GET"])
def get_recording_flat(recording_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer",
                  "RedactionTechnician", "Officer")
    recording = db.collection("recordings").get(recording_id)
    if recording is None:
        raise err_not_found("Recording not found")
    return success_obj(recording)


@bp.route("/agencies/<agency_id>/recordings/<recording_id>/reverify", methods=["POST"])
def reverify_recording(agency_id, recording_id):
    actor = authenticate()
    require_roles(actor, "Officer", "Supervisor")
    agency = get_agency_or_404(agency_id)
    recording = get_scoped("recordings", agency, recording_id, "Recording")
    if actor["role"] == "Officer" and recording["officer_id"] != actor["user_id"]:
        raise err_unauthorized("Only the uploading officer or a Supervisor may reverify")
    if recording["upload_status"] != "INTEGRITY_FAILED":
        raise err_invalid_state("Only an INTEGRITY_FAILED recording can be reverified")
    data = body()
    reject_unknown(data, {"content_hash_sha256"})
    recording["content_hash_sha256"] = require_hash(data, "content_hash_sha256")
    recording["upload_status"] = "RECEIVED"
    payload_hash = compute_content_hash(data.get("payload"))
    ok = _run_integrity_check(recording, actor, payload_hash=payload_hash)
    if ok and recording.get("category") is not None:
        policy = active_policy(agency["id"])
        if policy is None:
            raise err_no_active_policy()
        _activate_recording(recording, agency, policy, actor)
    else:
        touch(recording)
    return success_obj(recording)


@bp.route("/agencies/<agency_id>/recordings/<recording_id>/categorize", methods=["PATCH"])
def categorize_recording(agency_id, recording_id):
    actor = authenticate()
    require_roles(actor, "Officer", "Supervisor")
    agency = get_agency_or_404(agency_id)
    recording = get_scoped("recordings", agency, recording_id, "Recording")
    if actor["role"] == "Officer" and recording["officer_id"] != actor["user_id"]:
        raise err_unauthorized("Only the owning officer or a Supervisor may categorize")

    if recording["upload_status"] == "INTEGRITY_FAILED":
        raise err_integrity_failed()
    if recording["upload_status"] not in ("INTEGRITY_VERIFIED", "ACTIVE"):
        raise err_invalid_state("Recording cannot be categorized in its current state")

    data = body()
    reject_unknown(data, {"category"})
    category = require_enum(data, "category", services.CATEGORIES)

    policy = active_policy(agency["id"])
    if policy is None:
        raise err_no_active_policy()

    if recording["upload_status"] == "ACTIVE":
        for link in db.collection("links").values():
            if link["recording_id"] == recording["id"] and link["status"] == "LINKED":
                raise err_invalid_state("Cannot re-categorize a recording linked to a case")

    recording["category"] = category
    if recording["upload_status"] == "INTEGRITY_VERIFIED":
        _activate_recording(recording, agency, policy, actor)
    else:
        services.compute_recording_retention(recording)
        services.touch_agency(agency)
        touch(recording)
    return success_obj(recording)


@bp.route("/agencies/<agency_id>/recordings/<recording_id>/mark-reviewed", methods=["POST"])
def mark_reviewed(agency_id, recording_id):
    actor = authenticate()
    require_roles(actor, "Supervisor")
    agency = get_agency_or_404(agency_id)
    recording = get_scoped("recordings", agency, recording_id, "Recording")
    if recording["review_status"] != "PENDING_REVIEW":
        raise err_invalid_state("Recording is not PENDING_REVIEW")
    if recording["upload_status"] != "ACTIVE":
        raise err_invalid_state("Recording must be ACTIVE to be marked reviewed")
    recording["review_status"] = "REVIEWED"
    officer = db.collection("officers").get(recording["officer_id"])
    if officer is not None:
        services.recompute_officer_metrics(officer)
        touch(officer)
    touch(recording)
    write_audit(agency["id"], actor, "RECORDING_REVIEWED", "Recording",
                recording["id"], "review_status -> REVIEWED")
    return success_obj(recording)


@bp.route("/agencies/<agency_id>/recordings/<recording_id>/custody-events", methods=["GET"])
def recording_custody_events(agency_id, recording_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer", "Officer")
    agency = get_agency_or_404(agency_id)
    recording = get_scoped("recordings", agency, recording_id, "Recording")
    items = [e for e in db.collection("custody_events").values()
             if e["recording_id"] == recording["id"]]
    # Chronological order (PRD section 4): sort by event time only, stably, so
    # events sharing one logical instant keep their insertion order.
    items = sorted(items, key=lambda e: e.get("created_at") or "")
    from flask import request as _req
    from helpers import parse_pagination, success_arr
    limit, offset = parse_pagination(_req.args)
    page = items[offset:offset + limit]
    return success_arr(page, len(items), limit, offset)


# ---------------------------------------------------------------- retention run

@bp.route("/agencies/<agency_id>/retention/run", methods=["POST"])
def retention_run(agency_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin")
    agency = get_agency_or_404(agency_id)
    now = iso_now()

    marked = 0
    purged = 0
    held_skipped = 0
    purged_ids = []

    recordings = sorted(
        [r for r in db.collection("recordings").values() if r["agency_id"] == agency["id"]],
        key=lambda r: (r["created_at"], r["id"]),
    )

    # Phase 1: ACTIVE -> RETENTION_DUE
    for r in recordings:
        if r["upload_status"] == "ACTIVE" and r.get("retention_due_at") and r["retention_due_at"] <= now:
            r["upload_status"] = "RETENTION_DUE"
            touch(r)
            marked += 1
            for link in db.collection("links").values():
                if link["recording_id"] == r["id"] and link["status"] == "LINKED":
                    case = db.collection("cases").get(link["case_id"])
                    if case is not None:
                        services.touch_case(case)

    # Phase 2: RETENTION_DUE -> PURGED
    for r in recordings:
        if r["upload_status"] != "RETENTION_DUE":
            continue
        if r.get("legal_hold_count", 0) > 0:
            held_skipped += 1
            continue
        r["upload_status"] = "PURGED"
        touch(r)
        purged += 1
        purged_ids.append(r["id"])

        officer = db.collection("officers").get(r["officer_id"])
        if officer is not None:
            services.recompute_officer_metrics(officer)
            touch(officer)

        touched_cases = set()
        for link in db.collection("links").values():
            if link["recording_id"] == r["id"] and link["status"] == "LINKED":
                case = db.collection("cases").get(link["case_id"])
                if case is not None and case["id"] not in touched_cases:
                    services.touch_case(case)
                    touched_cases.add(case["id"])

        write_custody(agency["id"], r["id"], "PURGE_EXECUTED", SYSTEM_ACTOR,
                      hash_at_event=r["content_hash_sha256"])
        write_audit(agency["id"], SYSTEM_ACTOR, "RECORDING_PURGED", "Recording",
                    r["id"], "recording purged by retention run")

    services.touch_agency(agency)
    return success_obj({
        "marked_retention_due": marked,
        "purged": purged,
        "held_skipped": held_skipped,
        "purged_recording_ids": purged_ids,
    })
