"""All /ambient-clinical-documentation route handlers, registered onto the Flask app.

Validation order per PRD §2.9: auth -> unauthorized -> not_found (left-to-right) ->
request shape -> safety gates -> state -> business constraints -> temporal -> fiscal.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import db
import services
from helpers import (
    ApiError, bad_request, unauthorized, not_found, invalid_state, stale_version,
    new_entity, get_body, require_fields, is_string, is_int, is_bool, is_number,
    parse_iso8601_utc, fmt_ts, get_entity, touch, paginate, sort_created,
    now_ts, CODE_VALUE_RE, new_id,
)

ALL_ROLES = ["Patient", "Physician", "QAAuditor", "ComplianceOfficer", "PlatformAdmin"]

SPEAKER_ROLES = {"PHYSICIAN", "PATIENT", "CAREGIVER", "OTHER"}
CODE_TYPES = {"DIAGNOSIS", "ORDER", "BILLING"}
CAPTURED_VIA = {"ROOM_SIGNAGE", "VERBAL", "PORTAL"}
IMPORTANCE = {"CRITICAL", "MAJOR", "MINOR"}
PHYSICIAN_STATUS = {"ACTIVE", "SUSPENDED"}
QA_AUDITOR_STATUS = {"ACTIVE", "INACTIVE"}


def _filters(args, allowed):
    def fn(e):
        for key in allowed:
            v = args.get(key)
            if v is None:
                continue
            if str(e.get(key)) != v:
                return False
        return True
    return fn


def _list(store_name, args, allowed_filters, base_filter=None):
    items = list(db.stores[store_name].values())
    if base_filter is not None:
        items = [e for e in items if base_filter(e)]
    fn = _filters(args, allowed_filters)
    items = [e for e in items if fn(e)]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, meta


# ================================================================ patients
def create_patient(user):
    body = get_body()
    require_fields(body, ["mrn", "full_name"])
    # Reject unknown/system-managed fields
    allowed = {"mrn", "full_name", "default_ambient_opt_in"}
    extra = set(body.keys()) - allowed
    if extra:
        raise bad_request("unknown or system-managed field(s): %s" % ", ".join(sorted(extra)))
    if not is_string(body["mrn"]) or not body["mrn"]:
        raise bad_request("mrn must be a non-empty string")
    if not is_string(body["full_name"]) or not body["full_name"]:
        raise bad_request("full_name must be a non-empty string")
    default_opt_in = body.get("default_ambient_opt_in", True)
    if not is_bool(default_opt_in):
        raise bad_request("default_ambient_opt_in must be a boolean")
    for p in db.stores["patients"].values():
        if p["mrn"] == body["mrn"]:
            raise bad_request("mrn already exists: %s" % body["mrn"])
    patient = new_entity({
        "mrn": body["mrn"],
        "full_name": body["full_name"],
        "default_ambient_opt_in": default_opt_in,
    })
    db.stores["patients"][patient["id"]] = patient
    return patient, 201


def get_patient(user, patient_id):
    return get_entity("patients", patient_id, "patient"), 200


def list_patient_encounters(user, patient_id):
    from flask import request
    get_entity("patients", patient_id, "patient")
    page, meta = _list("encounters", request.args, ["encounter_status"],
                       base_filter=lambda e: e["patient_id"] == patient_id)
    return page, 200, meta


def list_patient_consents(user, patient_id):
    from flask import request
    get_entity("patients", patient_id, "patient")
    # Patient role: ownership — may only see own
    if user["role"] == "Patient" and user["user_id"] != patient_id:
        raise unauthorized("Patient may only access own consents")
    page, meta = _list("consents", request.args, ["status"],
                       base_filter=lambda c: c["patient_id"] == patient_id)
    return page, 200, meta


# ================================================================ physicians
def create_physician(user):
    body = get_body()
    require_fields(body, ["npi", "full_name", "specialty_code"])
    if not is_string(body["npi"]) or not body["npi"]:
        raise bad_request("npi must be a non-empty string")
    if not is_string(body["full_name"]) or not body["full_name"]:
        raise bad_request("full_name must be a non-empty string")
    if not is_string(body["specialty_code"]) or not body["specialty_code"]:
        raise bad_request("specialty_code must be a non-empty string")
    for p in db.stores["physicians"].values():
        if p["npi"] == body["npi"]:
            raise bad_request("npi already exists: %s" % body["npi"])
    physician = new_entity({
        "npi": body["npi"],
        "full_name": body["full_name"],
        "specialty_code": body["specialty_code"],
        "status": "ACTIVE",
    })
    db.stores["physicians"][physician["id"]] = physician
    return physician, 201


def get_physician(user, physician_id):
    return get_entity("physicians", physician_id, "physician"), 200


def update_physician(user, physician_id):
    phys = get_entity("physicians", physician_id, "physician")
    body = get_body()
    require_fields(body, ["status"])
    new_status = body["status"]
    if new_status not in PHYSICIAN_STATUS:
        raise bad_request("status must be ACTIVE or SUSPENDED")
    phys["status"] = new_status
    touch(phys)
    return phys, 200


def list_physician_encounters(user, physician_id):
    from flask import request
    get_entity("physicians", physician_id, "physician")
    page, meta = _list("encounters", request.args, ["encounter_status"],
                       base_filter=lambda e: e["physician_id"] == physician_id)
    return page, 200, meta


def list_physician_drafts(user, physician_id):
    from flask import request
    get_entity("physicians", physician_id, "physician")
    page, meta = _list("note_drafts", request.args, ["status"],
                       base_filter=lambda d: d["author_physician_id"] == physician_id)
    return page, 200, meta


def list_physician_attestations(user, physician_id):
    from flask import request
    get_entity("physicians", physician_id, "physician")
    page, meta = _list("attestations", request.args, [],
                       base_filter=lambda a: a["physician_id"] == physician_id)
    return page, 200, meta


def list_physician_metrics(user, physician_id):
    from flask import request
    get_entity("physicians", physician_id, "physician")
    page, meta = _list("doc_metrics", request.args, ["period_start", "status"],
                       base_filter=lambda m: m["physician_id"] == physician_id)
    return page, 200, meta


def recompute_physician_metric(user, physician_id):
    get_entity("physicians", physician_id, "physician")
    body = get_body()
    require_fields(body, ["period_start"])
    period_start_raw = body["period_start"]
    period_dt = parse_iso8601_utc(period_start_raw) if is_string(period_start_raw) else None
    if period_dt is None:
        raise bad_request("period_start must be an ISO8601 timestamp")
    finalize = body.get("finalize", False)
    if not is_bool(finalize):
        raise bad_request("finalize must be a boolean")

    # Find existing row by (physician, month)
    metric = services.metric_for(physician_id, period_dt)
    if metric is not None and metric["status"] == "FINAL":
        raise ApiError("ERR_METRIC_PERIOD_CLOSED", 409, "metric period is FINAL")
    if metric is None:
        metric = services.ensure_metric(physician_id, period_dt)
    services.recompute_metric(metric, physician_id)
    if finalize and metric["status"] != "FINAL":
        metric["status"] = "FINAL"
        metric["finalized_at"] = now_ts()
    touch(metric)
    return metric, 200


# ================================================================ qa auditors
def create_qa_auditor(user):
    body = get_body()
    require_fields(body, ["employee_code", "full_name", "specialty_codes"])
    if not is_string(body["employee_code"]) or not body["employee_code"]:
        raise bad_request("employee_code must be a non-empty string")
    if not is_string(body["full_name"]) or not body["full_name"]:
        raise bad_request("full_name must be a non-empty string")
    spec = body["specialty_codes"]
    if not isinstance(spec, list) or not spec or any(not is_string(s) or not s for s in spec):
        raise bad_request("specialty_codes must be a non-empty array of non-empty strings")
    for a in db.stores["qa_auditors"].values():
        if a["employee_code"] == body["employee_code"]:
            raise bad_request("employee_code already exists: %s" % body["employee_code"])
    auditor = new_entity({
        "employee_code": body["employee_code"],
        "full_name": body["full_name"],
        "specialty_codes": list(spec),
        "status": "ACTIVE",
    })
    db.stores["qa_auditors"][auditor["id"]] = auditor
    return auditor, 201


def get_qa_auditor(user, auditor_id):
    return get_entity("qa_auditors", auditor_id, "qa_auditor"), 200


def list_auditor_samples(user, auditor_id):
    from flask import request
    get_entity("qa_auditors", auditor_id, "qa_auditor")
    page, meta = _list("qa_samples", request.args, ["status"],
                       base_filter=lambda s: s.get("auditor_id") == auditor_id)
    return page, 200, meta


# ================================================================ note templates
def create_note_template(user):
    body = get_body()
    require_fields(body, ["specialty_code", "template_version", "field_specs"])
    if not is_string(body["specialty_code"]) or not body["specialty_code"]:
        raise bad_request("specialty_code must be a non-empty string")
    if not is_string(body["template_version"]) or not body["template_version"]:
        raise bad_request("template_version must be a non-empty string")
    specs = body["field_specs"]
    if not isinstance(specs, list) or not specs:
        raise bad_request("field_specs must be a non-empty array")
    seen_keys = set()
    for spec in specs:
        if not isinstance(spec, dict):
            raise bad_request("field_specs entries must be objects")
        if "key" not in spec or "importance" not in spec or "required" not in spec:
            raise bad_request("field_specs entries require key, importance, required")
        if not is_string(spec["key"]) or not spec["key"]:
            raise bad_request("field_specs key must be a non-empty string")
        if spec["importance"] not in IMPORTANCE:
            raise bad_request("field_specs importance must be CRITICAL|MAJOR|MINOR")
        if not is_bool(spec["required"]):
            raise bad_request("field_specs required must be boolean")
        if spec["key"] in seen_keys:
            raise bad_request("duplicate field_specs key: %s" % spec["key"])
        seen_keys.add(spec["key"])
    cm = body.get("completeness_multiplier", 1.0)
    if not is_number(cm) or cm <= 0 or cm > 3.0:
        raise bad_request("completeness_multiplier must be > 0 and <= 3.0")
    lct = body.get("low_confidence_threshold", 90)
    if not is_int(lct) or lct < 0 or lct > 100:
        raise bad_request("low_confidence_threshold must be an integer in 0..100")
    active = body.get("active", True)
    if not is_bool(active):
        raise bad_request("active must be a boolean")
    for t in db.stores["note_templates"].values():
        if t["specialty_code"] == body["specialty_code"] and t["template_version"] == body["template_version"]:
            raise bad_request("template_version already exists for specialty_code")
    template = new_entity({
        "specialty_code": body["specialty_code"],
        "template_version": body["template_version"],
        "field_specs": specs,
        "completeness_multiplier": float(cm),
        "low_confidence_threshold": lct,
        "active": active,
    })
    db.stores["note_templates"][template["id"]] = template
    return template, 201


def get_note_template(user, template_id):
    return get_entity("note_templates", template_id, "note_template"), 200


def update_note_template(user, template_id):
    t = get_entity("note_templates", template_id, "note_template")
    body = get_body()
    require_fields(body, ["active"])
    if not is_bool(body["active"]):
        raise bad_request("active must be a boolean")
    t["active"] = body["active"]
    touch(t)
    return t, 200


def list_template_drafts(user, template_id):
    from flask import request
    get_entity("note_templates", template_id, "note_template")
    page, meta = _list("note_drafts", request.args, ["status"],
                       base_filter=lambda d: d["template_id"] == template_id)
    return page, 200, meta


# ================================================================ encounters
def create_encounter(user):
    body = get_body()
    require_fields(body, ["patient_id", "physician_id"])
    if not is_string(body["patient_id"]):
        raise bad_request("patient_id must be a string")
    if not is_string(body["physician_id"]):
        raise bad_request("physician_id must be a string")
    scheduled_start = body.get("scheduled_start")
    if scheduled_start is not None:
        if not is_string(scheduled_start) or parse_iso8601_utc(scheduled_start) is None:
            raise bad_request("scheduled_start must be an ISO8601 timestamp")
    # Existence checks
    get_entity("patients", body["patient_id"], "patient")
    get_entity("physicians", body["physician_id"], "physician")
    # Ownership: attending must equal caller's X-User-ID
    if body["physician_id"] != user["user_id"]:
        raise unauthorized("physician_id must equal caller's X-User-ID")
    enc = new_entity({
        "patient_id": body["patient_id"],
        "physician_id": body["physician_id"],
        "scheduled_start": scheduled_start,
        "started_at": None,
        "ended_at": None,
        "encounter_status": "SCHEDULED",
        "audio_status": "NOT_RECORDING",
        "documentation_status": "NOT_STARTED",
        "cancel_reason": None,
    })
    db.stores["encounters"][enc["id"]] = enc
    return enc, 201


def get_encounter(user, encounter_id):
    return get_entity("encounters", encounter_id, "encounter"), 200


def start_encounter(user, encounter_id):
    enc = get_entity("encounters", encounter_id, "encounter")
    if user["role"] == "Physician" and user["user_id"] != enc["physician_id"]:
        raise unauthorized("only the attending physician may start the encounter")
    if enc["encounter_status"] != "SCHEDULED":
        raise invalid_state("encounter is not SCHEDULED")
    enc["encounter_status"] = "IN_PROGRESS"
    enc["started_at"] = now_ts()
    touch(enc)
    return enc, 200


def complete_encounter(user, encounter_id):
    enc = get_entity("encounters", encounter_id, "encounter")
    if user["role"] == "Physician" and user["user_id"] != enc["physician_id"]:
        raise unauthorized("only the attending physician may complete the encounter")
    if enc["encounter_status"] != "IN_PROGRESS":
        raise invalid_state("encounter is not IN_PROGRESS")
    # no capture in RECORDING or PAUSED
    for cap in services.captures_of_encounter(enc["id"]):
        if cap["status"] in ("RECORDING", "PAUSED"):
            raise invalid_state("cannot complete while a capture is RECORDING or PAUSED")
    enc["encounter_status"] = "COMPLETED"
    enc["ended_at"] = now_ts()
    if services.captures_of_encounter(enc["id"]):
        enc["audio_status"] = "AUDIO_STOPPED"
    touch(enc)
    return enc, 200


def cancel_encounter(user, encounter_id):
    enc = get_entity("encounters", encounter_id, "encounter")
    body = get_body()
    cancel_reason = body.get("cancel_reason")
    if cancel_reason is not None and not is_string(cancel_reason):
        raise bad_request("cancel_reason must be a string")
    if enc["encounter_status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise invalid_state("encounter cannot be cancelled from status %s" % enc["encounter_status"])
    enc["encounter_status"] = "CANCELLED"
    enc["ended_at"] = now_ts()
    if cancel_reason is not None:
        enc["cancel_reason"] = cancel_reason
    # Cascade: GRANTED consent -> EXPIRED with purge_reason CANCEL for in-flight captures
    active = services.active_consent(enc["id"])
    if active is not None:
        # Cancel cascade: only the GRANTED consent expires; in-flight captures purge with CANCEL
        now = now_ts()
        active["status"] = "EXPIRED"
        active["ended_at"] = now
        active["end_reason"] = "EXPIRE"
        touch(active)
        for cap in services.captures_of_encounter(enc["id"]):
            if cap["status"] in ("RECORDING", "PAUSED"):
                cap["status"] = "PURGED"
                cap["purge_reason"] = "CANCEL"
                for iv in cap.get("pause_intervals", []):
                    if iv[1] is None:
                        iv[1] = now
                if cap.get("ended_at") is None:
                    cap["ended_at"] = now
                touch(cap)
        services.refresh_encounter_audio_status(enc)
    touch(enc)
    return enc, 200


# ================================================================ consents
def list_encounter_consents(user, encounter_id):
    from flask import request
    enc = get_entity("encounters", encounter_id, "encounter")
    # Patient: may only list consents on encounters that belong to them
    if user["role"] == "Patient" and user["user_id"] != enc["patient_id"]:
        raise unauthorized("Patient may only access own encounter consents")
    page, meta = _list("consents", request.args, ["status"],
                       base_filter=lambda c: c["encounter_id"] == encounter_id)
    return page, 200, meta


def create_consent(user, encounter_id):
    enc = get_entity("encounters", encounter_id, "encounter")
    body = get_body()
    require_fields(body, ["patient_id", "signage_posted", "captured_via"])
    if not is_string(body["patient_id"]):
        raise bad_request("patient_id must be a string")
    if not is_bool(body["signage_posted"]):
        raise bad_request("signage_posted must be a boolean")
    if body["captured_via"] not in CAPTURED_VIA:
        raise bad_request("captured_via must be ROOM_SIGNAGE|VERBAL|PORTAL")
    # Referential: patient must exist; patient must equal encounter's patient
    get_entity("patients", body["patient_id"], "patient")
    if body["patient_id"] != enc["patient_id"]:
        raise bad_request("patient_id must equal encounter's patient_id")
    # Ownership for Patient role
    if user["role"] == "Patient" and user["user_id"] != body["patient_id"]:
        raise unauthorized("Patient may only grant consent for own patient_id")
    # Business: signage
    if body["signage_posted"] is not True:
        raise ApiError("ERR_SIGNAGE_NOT_POSTED", 422, "signage_posted must be true")
    # Business: at most one GRANTED per encounter
    if services.active_consent(enc["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_CONSENT", 409, "encounter already has a GRANTED consent")
    consent = new_entity({
        "encounter_id": enc["id"],
        "patient_id": body["patient_id"],
        "status": "GRANTED",
        "signage_posted": True,
        "captured_via": body["captured_via"],
        "granted_at": now_ts(),
        "ended_at": None,
        "end_reason": None,
        "revocation_reason": None,
    })
    db.stores["consents"][consent["id"]] = consent
    return consent, 201


def opt_out_consent(user, consent_id):
    consent = get_entity("consents", consent_id, "consent")
    body = get_body()
    reason = body.get("reason")
    if reason is not None and not is_string(reason):
        raise bad_request("reason must be a string")
    # Ownership: Patient must act on own consent
    if user["role"] == "Patient" and user["user_id"] != consent["patient_id"]:
        raise unauthorized("Patient may only opt out of own consent")
    if consent["status"] != "GRANTED":
        raise invalid_state("consent is not GRANTED")
    enc = get_entity("encounters", consent["encounter_id"], "encounter")
    services.cascade_consent_end(enc, consent, "OPTED_OUT", "OPT_OUT", "OPT_OUT",
                                 revocation_reason=reason)
    return consent, 200


def revoke_consent(user, consent_id):
    consent = get_entity("consents", consent_id, "consent")
    body = get_body()
    reason = body.get("reason")
    if reason is not None and not is_string(reason):
        raise bad_request("reason must be a string")
    if consent["status"] != "GRANTED":
        raise invalid_state("consent is not GRANTED")
    enc = get_entity("encounters", consent["encounter_id"], "encounter")
    services.cascade_consent_end(enc, consent, "REVOKED", "REVOKE", "REVOKE",
                                 revocation_reason=reason)
    return consent, 200


# ================================================================ audio captures
def list_encounter_captures(user, encounter_id):
    from flask import request
    enc = get_entity("encounters", encounter_id, "encounter")
    if user["role"] == "Patient" and user["user_id"] != enc["patient_id"]:
        raise unauthorized("Patient may only access own encounter captures")
    page, meta = _list("audio_captures", request.args, ["status"],
                       base_filter=lambda c: c["encounter_id"] == encounter_id)
    return page, 200, meta


def create_audio_capture(user, encounter_id):
    enc = get_entity("encounters", encounter_id, "encounter")
    if user["role"] == "Physician" and user["user_id"] != enc["physician_id"]:
        raise unauthorized("only the attending physician may start a capture")
    body = get_body()
    require_fields(body, ["planned_retention_days"])
    pr = body["planned_retention_days"]
    if not is_int(pr) or pr < 1 or pr > 3650:
        raise bad_request("planned_retention_days must be an integer in 1..3650")
    # Safety gates: consent, then encounter state
    if services.active_consent(enc["id"]) is None:
        raise ApiError("ERR_CONSENT_REQUIRED", 422, "encounter requires a GRANTED consent")
    if enc["encounter_status"] != "IN_PROGRESS":
        raise ApiError("ERR_ENCOUNTER_NOT_IN_PROGRESS", 409,
                       "encounter must be IN_PROGRESS to start a capture")
    # Business: no other active capture
    for cap in services.captures_of_encounter(enc["id"]):
        if cap["status"] in ("RECORDING", "PAUSED"):
            raise ApiError("ERR_CAPTURE_ACTIVE_EXISTS", 409,
                           "another capture of the encounter is RECORDING or PAUSED")
    # Temporal: 60s gap after most recent stopped (CAPTURED, not yet transcribed) capture
    stopped = [c for c in services.captures_of_encounter(enc["id"])
               if c["status"] == "CAPTURED" and c.get("ended_at")]
    if stopped:
        def _ended_key(c):
            dt = parse_iso8601_utc(c["ended_at"])
            return dt or datetime.min.replace(tzinfo=timezone.utc)
        latest = max(stopped, key=_ended_key)
        latest_end = parse_iso8601_utc(latest["ended_at"])
        if latest_end is not None:
            now_dt = db.get_clock()
            delta = (now_dt - latest_end).total_seconds()
            if delta < services.CAPTURE_GAP_SECONDS:
                raise ApiError("ERR_CAPTURE_GAP_VIOLATION", 409,
                               "new capture must start >= 60s after the previous capture's ended_at")
    cap = new_entity({
        "encounter_id": enc["id"],
        "status": "RECORDING",
        "started_at": now_ts(),
        "ended_at": None,
        "planned_retention_days": pr,
        "retention_days_effective": pr,
        "legal_hold": False,
        "recorded_seconds": 0,
        "purge_reason": None,
        "pause_intervals": [],  # list of [start_iso, end_iso_or_None]
        "_recording_started_at": now_ts(),  # internal tracking
    })
    db.stores["audio_captures"][cap["id"]] = cap
    enc["audio_status"] = "RECORDING_ACTIVE"
    touch(enc)
    return cap, 201


def _serialize_capture(cap):
    """Public view — strip internal fields."""
    return {k: v for k, v in cap.items() if not k.startswith("_") and k != "pause_intervals"}


def get_audio_capture(user, capture_id):
    cap = get_entity("audio_captures", capture_id, "audio_capture")
    return _serialize_capture(cap), 200


def pause_capture(user, capture_id):
    cap = get_entity("audio_captures", capture_id, "audio_capture")
    enc = get_entity("encounters", cap["encounter_id"], "encounter")
    if user["role"] == "Physician" and user["user_id"] != enc["physician_id"]:
        raise unauthorized("only the attending physician may pause")
    if cap["status"] != "RECORDING":
        raise invalid_state("capture is not RECORDING")
    # Close current recording interval (accrue recorded_seconds)
    now = now_ts()
    rec_start = parse_iso8601_utc(cap.get("_recording_started_at"))
    now_dt = parse_iso8601_utc(now)
    if rec_start and now_dt:
        cap["recorded_seconds"] += int((now_dt - rec_start).total_seconds())
    cap["_recording_started_at"] = None
    cap["pause_intervals"].append([now, None])
    cap["status"] = "PAUSED"
    touch(cap)
    return _serialize_capture(cap), 200


def resume_capture(user, capture_id):
    cap = get_entity("audio_captures", capture_id, "audio_capture")
    enc = get_entity("encounters", cap["encounter_id"], "encounter")
    if user["role"] == "Physician" and user["user_id"] != enc["physician_id"]:
        raise unauthorized("only the attending physician may resume")
    if cap["status"] != "PAUSED":
        raise invalid_state("capture is not PAUSED")
    now = now_ts()
    # Close the open pause interval
    for iv in cap["pause_intervals"]:
        if iv[1] is None:
            iv[1] = now
            break
    cap["_recording_started_at"] = now
    cap["status"] = "RECORDING"
    touch(cap)
    return _serialize_capture(cap), 200


def stop_capture(user, capture_id):
    cap = get_entity("audio_captures", capture_id, "audio_capture")
    enc = get_entity("encounters", cap["encounter_id"], "encounter")
    if user["role"] == "Physician" and user["user_id"] != enc["physician_id"]:
        raise unauthorized("only the attending physician may stop")
    if cap["status"] not in ("RECORDING", "PAUSED"):
        raise invalid_state("capture is not RECORDING or PAUSED")
    now = now_ts()
    if cap["status"] == "RECORDING":
        rec_start = parse_iso8601_utc(cap.get("_recording_started_at"))
        now_dt = parse_iso8601_utc(now)
        if rec_start and now_dt:
            cap["recorded_seconds"] += int((now_dt - rec_start).total_seconds())
    else:
        # Close open pause interval
        for iv in cap["pause_intervals"]:
            if iv[1] is None:
                iv[1] = now
                break
    cap["_recording_started_at"] = None
    cap["status"] = "CAPTURED"
    cap["ended_at"] = now
    enc["audio_status"] = "AUDIO_STOPPED"
    touch(enc)
    touch(cap)
    return _serialize_capture(cap), 200


def purge_capture(user, capture_id):
    cap = get_entity("audio_captures", capture_id, "audio_capture")
    # Safety: legal hold
    if cap.get("legal_hold"):
        raise ApiError("ERR_LEGAL_HOLD_ACTIVE", 422, "capture is under legal hold")
    if cap["status"] not in ("CAPTURED", "TRANSCRIBED"):
        raise invalid_state("capture is not CAPTURED or TRANSCRIBED")
    cap["status"] = "PURGED"
    cap["purge_reason"] = "MANUAL"
    touch(cap)
    # Encounter audio_status may now be NOT_RECORDING if no captures remain
    enc = get_entity("encounters", cap["encounter_id"], "encounter")
    services.refresh_encounter_audio_status(enc)
    return _serialize_capture(cap), 200


def legal_hold_capture(user, capture_id):
    cap = get_entity("audio_captures", capture_id, "audio_capture")
    body = get_body()
    require_fields(body, ["hold"])
    if not is_bool(body["hold"]):
        raise bad_request("hold must be a boolean")
    cap["legal_hold"] = body["hold"]
    touch(cap)
    return _serialize_capture(cap), 200


# ================================================================ segments
def add_segment(user, capture_id):
    cap = get_entity("audio_captures", capture_id, "audio_capture")
    enc = get_entity("encounters", cap["encounter_id"], "encounter")
    if user["role"] == "Physician" and user["user_id"] != enc["physician_id"]:
        raise unauthorized("only the attending physician may append segments")
    body = get_body()
    require_fields(body, ["start_offset_ms", "end_offset_ms", "speaker_role", "base_confidence"])
    if not is_int(body["start_offset_ms"]) or body["start_offset_ms"] < 0:
        raise bad_request("start_offset_ms must be an integer >= 0")
    if not is_int(body["end_offset_ms"]) or body["end_offset_ms"] <= body["start_offset_ms"]:
        raise bad_request("end_offset_ms must be an integer > start_offset_ms")
    if body["speaker_role"] not in SPEAKER_ROLES:
        raise ApiError("ERR_SPEAKER_ROLE_INVALID", 400,
                       "speaker_role must be PHYSICIAN|PATIENT|CAREGIVER|OTHER")
    bc = body["base_confidence"]
    if not is_number(bc) or bc < 0 or bc > 1:
        raise bad_request("base_confidence must be a number in 0..1")
    # 4-decimal cap
    bc_dec = Decimal(str(bc))
    if bc_dec != bc_dec.quantize(Decimal("0.0001")):
        raise bad_request("base_confidence must have at most 4 decimal places")
    # State: encounter must be IN_PROGRESS
    if enc["encounter_status"] != "IN_PROGRESS":
        raise ApiError("ERR_ENCOUNTER_NOT_IN_PROGRESS", 409,
                       "encounter must be IN_PROGRESS to append segments")
    # Temporal: pairwise disjoint half-open intervals
    new_s, new_e = body["start_offset_ms"], body["end_offset_ms"]
    for seg in db.stores["segments"].values():
        if seg["audio_capture_id"] != capture_id:
            continue
        # overlap if new_s < seg.end and seg.start < new_e (half-open)
        if new_s < seg["end_offset_ms"] and seg["start_offset_ms"] < new_e:
            raise ApiError("ERR_SEGMENT_OVERLAP", 409,
                           "segment interval overlaps an existing segment")
    seg = new_entity({
        "audio_capture_id": capture_id,
        "start_offset_ms": new_s,
        "end_offset_ms": new_e,
        "speaker_role": body["speaker_role"],
        "base_confidence": float(bc),
        "reassignment_count": 0,
        "effective_confidence": float(bc_dec.quantize(Decimal("0.0001"))),
    })
    db.stores["segments"][seg["id"]] = seg
    return seg, 201


def list_segments(user, capture_id):
    from flask import request
    cap = get_entity("audio_captures", capture_id, "audio_capture")
    if cap["status"] == "PURGED":
        items = []
        page, meta = paginate(items)
        return page, 200, meta
    page, meta = _list("segments", request.args, ["speaker_role"],
                       base_filter=lambda s: s["audio_capture_id"] == capture_id)
    return page, 200, meta


def reassign_segment(user, segment_id):
    seg = get_entity("segments", segment_id, "segment")
    cap = get_entity("audio_captures", seg["audio_capture_id"], "audio_capture")
    enc = get_entity("encounters", cap["encounter_id"], "encounter")
    if user["role"] == "Physician" and user["user_id"] != enc["physician_id"]:
        raise unauthorized("only the attending physician may reassign a segment")
    body = get_body()
    require_fields(body, ["new_speaker_role"])
    new_role = body["new_speaker_role"]
    if new_role not in SPEAKER_ROLES:
        raise ApiError("ERR_SPEAKER_ROLE_INVALID", 400,
                       "new_speaker_role must be PHYSICIAN|PATIENT|CAREGIVER|OTHER")
    seg["speaker_role"] = new_role
    seg["reassignment_count"] = seg.get("reassignment_count", 0) + 1
    # effective_confidence = round_half_up(base * 0.9^reassignment_count, 4)
    from helpers import round_half_up_4
    base_dec = Decimal(str(seg["base_confidence"]))
    decay = services.REASSIGNMENT_DECAY ** seg["reassignment_count"]
    seg["effective_confidence"] = round_half_up_4(base_dec * decay)
    touch(seg)
    return seg, 200


# ================================================================ note drafts
def list_encounter_drafts(user, encounter_id):
    from flask import request
    enc = get_entity("encounters", encounter_id, "encounter")
    if user["role"] == "Patient" and user["user_id"] != enc["patient_id"]:
        raise unauthorized("Patient may only access own encounter drafts")
    page, meta = _list("note_drafts", request.args, ["status"],
                       base_filter=lambda d: d["encounter_id"] == encounter_id)
    return page, 200, meta


def create_note_draft(user, encounter_id):
    enc = get_entity("encounters", encounter_id, "encounter")
    if user["role"] == "Physician" and user["user_id"] != enc["physician_id"]:
        raise unauthorized("only the attending physician may create a draft")
    body = get_body()
    require_fields(body, ["template_id", "expected_encounter_version"])
    if not is_string(body["template_id"]):
        raise bad_request("template_id must be a string")
    if not is_int(body["expected_encounter_version"]):
        raise bad_request("expected_encounter_version must be an integer")
    template = get_entity("note_templates", body["template_id"], "note_template")
    # OCC: encounter version check
    if body["expected_encounter_version"] != enc["version"]:
        raise stale_version("expected_encounter_version mismatch")
    # Safety: consent
    if services.active_consent(enc["id"]) is None:
        raise ApiError("ERR_CONSENT_NOT_ACTIVE", 422,
                       "encounter must hold a GRANTED consent")
    # Business: template active
    if not template.get("active", False):
        raise ApiError("ERR_TEMPLATE_INACTIVE", 422, "template is inactive")
    # Business: at least one TRANSCRIBED capture
    has_transcribed = any(c["status"] == "TRANSCRIBED"
                          for c in services.captures_of_encounter(enc["id"]))
    if not has_transcribed:
        raise ApiError("ERR_NO_TRANSCRIBED_AUDIO", 422,
                       "draft creation requires a TRANSCRIBED capture")
    # Supersede existing non-terminal drafts
    services.supersede_existing_drafts(enc)
    # Create the new draft
    draft = new_entity({
        "encounter_id": enc["id"],
        "template_id": template["id"],
        "author_physician_id": enc["physician_id"],
        "status": "DRAFT",
        "completeness_score": 0,
        "billing_provisional_cents": 0,
        "billing_final_cents": 0,
        "regeneration_count": 0,
        "amendment_count": 0,
        "phi_review_required": False,
        "attested_at": None,
    })
    db.stores["note_drafts"][draft["id"]] = draft
    # Seed NoteField rows from template field_specs
    for spec in template["field_specs"]:
        f = new_entity({
            "note_draft_id": draft["id"],
            "field_key": spec["key"],
            "field_value": None,
            "importance": spec["importance"],
            "required": spec["required"],
            "source": "SYSTEM",
            "validated": False,
        })
        db.stores["note_fields"][f["id"]] = f
    services.recompute_draft_completeness(draft)
    enc["documentation_status"] = "DRAFTING"
    touch(enc)
    return draft, 201


def get_note_draft(user, draft_id):
    return get_entity("note_drafts", draft_id, "note_draft"), 200


def patch_note_draft(user, draft_id):
    draft = get_entity("note_drafts", draft_id, "note_draft")
    if user["role"] == "Physician" and user["user_id"] != draft["author_physician_id"]:
        raise unauthorized("only the author may edit the draft")
    body = get_body()
    require_fields(body, ["expected_note_draft_version", "field_updates"])
    if not is_int(body["expected_note_draft_version"]):
        raise bad_request("expected_note_draft_version must be an integer")
    field_updates = body["field_updates"]
    # field_updates is an array of {field_key, field_value} entries
    if not isinstance(field_updates, list):
        raise bad_request("field_updates must be an array")
    parsed_updates = []
    for entry in field_updates:
        if not isinstance(entry, dict):
            raise bad_request("each field_updates entry must be an object")
        if "field_key" not in entry or "field_value" not in entry:
            raise bad_request("each field_updates entry requires field_key and field_value")
        if not is_string(entry["field_key"]):
            raise bad_request("field_key must be a string")
        if entry["field_value"] is not None and not is_string(entry["field_value"]):
            raise bad_request("field_value must be a string or null")
        parsed_updates.append((entry["field_key"], entry["field_value"]))
    template = services.get_template(draft)
    valid_keys = {spec["key"] for spec in (template["field_specs"] if template else [])}
    for k, _v in parsed_updates:
        if k not in valid_keys:
            raise ApiError("ERR_TEMPLATE_FIELD_MISMATCH", 422,
                           "field_updates key not in template field_specs: %s" % k)
    # State check
    if draft["status"] in ("ATTESTED", "VOID"):
        raise ApiError("ERR_NOTE_LOCKED", 409,
                       "cannot edit a draft in %s" % draft["status"])
    if draft["status"] not in ("DRAFT", "EDITED", "IN_REVIEW", "AMENDED"):
        raise invalid_state("draft is not editable from %s" % draft["status"])
    # OCC
    if body["expected_note_draft_version"] != draft["version"]:
        raise stale_version("expected_note_draft_version mismatch")
    # Apply edits
    fields = {f["field_key"]: f for f in services.fields_of_draft(draft_id)}
    for k, v in parsed_updates:
        f = fields.get(k)
        if f is None:
            continue
        f["field_value"] = v
        f["source"] = "MANUAL"
        f["validated"] = True
        touch(f)
    if draft["status"] == "IN_REVIEW":
        draft["status"] = "EDITED"
    services.recompute_draft_completeness(draft)
    touch(draft)
    return draft, 200


def submit_review_draft(user, draft_id):
    draft = get_entity("note_drafts", draft_id, "note_draft")
    if user["role"] == "Physician" and user["user_id"] != draft["author_physician_id"]:
        raise unauthorized("only the author may submit the draft")
    if draft["status"] not in ("DRAFT", "EDITED", "AMENDED"):
        raise invalid_state("draft is not in DRAFT/EDITED/AMENDED")
    draft["status"] = "IN_REVIEW"
    enc = services.get_encounter_of_draft(draft)
    if enc is not None:
        enc["documentation_status"] = "IN_REVIEW"
        touch(enc)
    touch(draft)
    return draft, 200


def regenerate_draft(user, draft_id):
    draft = get_entity("note_drafts", draft_id, "note_draft")
    if user["role"] == "Physician" and user["user_id"] != draft["author_physician_id"]:
        raise unauthorized("only the author may regenerate the draft")
    enc = services.get_encounter_of_draft(draft)
    # Safety: consent
    if enc is None or services.active_consent(enc["id"]) is None:
        raise ApiError("ERR_CONSENT_NOT_ACTIVE", 422,
                       "encounter must hold a GRANTED consent")
    # State
    if draft["status"] != "IN_REVIEW":
        raise invalid_state("draft is not IN_REVIEW")
    # Business: transcribed audio
    has_transcribed = any(c["status"] == "TRANSCRIBED"
                          for c in services.captures_of_encounter(enc["id"]))
    if not has_transcribed:
        raise ApiError("ERR_NO_TRANSCRIBED_AUDIO", 422,
                       "regenerate requires a TRANSCRIBED capture")
    for f in services.fields_of_draft(draft_id):
        if f.get("source") == "MANUAL":
            continue
        f["field_value"] = "drafted:" + f["field_key"]
        f["source"] = "AUDIO"
        f["validated"] = False
        touch(f)
    draft["regeneration_count"] = draft.get("regeneration_count", 0) + 1
    draft["status"] = "DRAFT"
    services.recompute_draft_completeness(draft)
    enc["documentation_status"] = "DRAFTING"
    touch(enc)
    touch(draft)
    return draft, 200


def attest_draft(user, draft_id):
    draft = get_entity("note_drafts", draft_id, "note_draft")
    if user["role"] == "Physician" and user["user_id"] != draft["author_physician_id"]:
        raise unauthorized("only the author may attest the draft")
    enc = services.get_encounter_of_draft(draft)
    # Safety: physician status
    physician = db.stores["physicians"].get(draft["author_physician_id"])
    if physician is None or physician.get("status") != "ACTIVE":
        raise ApiError("ERR_PHYSICIAN_NOT_ACTIVE", 422,
                       "attesting physician must be ACTIVE")
    # Safety: consent
    if enc is None or services.active_consent(enc["id"]) is None:
        raise ApiError("ERR_CONSENT_NOT_ACTIVE", 422,
                       "encounter must hold a GRANTED consent")
    # State: must be IN_REVIEW
    if draft["status"] != "IN_REVIEW":
        raise invalid_state("draft is not IN_REVIEW")
    # State: QA hold
    for s in db.stores["qa_samples"].values():
        if s["note_draft_id"] == draft_id and s["status"] == "ASSIGNED":
            raise ApiError("ERR_QA_HOLD_ACTIVE", 409,
                           "draft has an ASSIGNED QA sample")
    # Business: completeness
    if draft["completeness_score"] < services.ATTEST_MINIMUM:
        raise ApiError("ERR_NOTE_INCOMPLETE", 422,
                       "completeness_score must be >= 80")
    # Create Attestation
    now = now_ts()
    att_type = "INITIAL" if draft.get("amendment_count", 0) == 0 else "AMENDMENT"
    att = {
        "id": new_id(),
        "created_at": now,
        "note_draft_id": draft["id"],
        "physician_id": draft["author_physician_id"],
        "attestation_type": att_type,
        "attested_at": now,
        "completeness_at_attestation": draft["completeness_score"],
    }
    db.stores["attestations"][att["id"]] = att
    draft["status"] = "ATTESTED"
    draft["attested_at"] = now
    # Expire SUGGESTED/MODIFIED suggestions
    for s in services.suggestions_of_draft(draft_id):
        if s["status"] in ("SUGGESTED", "MODIFIED"):
            s["status"] = "EXPIRED"
            touch(s)
    services.recompute_billing_totals(draft)
    # Metric counter
    att_dt = parse_iso8601_utc(now)
    metric = services.ensure_metric(draft["author_physician_id"], att_dt)
    metric["notes_attested"] = metric.get("notes_attested", 0) + 1
    touch(metric)
    # Low-confidence QA sample
    template = services.get_template(draft)
    if template and draft["completeness_score"] < template["low_confidence_threshold"]:
        sample = new_entity({
            "note_draft_id": draft["id"],
            "auditor_id": None,
            "status": "QUEUED",
            "sampling_reason": "LOW_CONFIDENCE",
            "created_by_user_id": "system",
            "accuracy_score": None,
            "completeness_score": None,
            "timeliness_score": None,
            "composite_score": None,
            "appeal_count": 0,
            "last_scorer_id": None,
        })
        db.stores["qa_samples"][sample["id"]] = sample
    enc["documentation_status"] = "ATTESTED"
    touch(enc)
    touch(draft)
    return draft, 200


def amend_draft(user, draft_id):
    draft = get_entity("note_drafts", draft_id, "note_draft")
    if user["role"] == "Physician" and user["user_id"] != draft["author_physician_id"]:
        raise unauthorized("only the author may amend the draft")
    if draft["status"] != "ATTESTED":
        raise invalid_state("draft is not ATTESTED")
    draft["status"] = "AMENDED"
    draft["amendment_count"] = draft.get("amendment_count", 0) + 1
    enc = services.get_encounter_of_draft(draft)
    if enc is not None:
        enc["documentation_status"] = "AMENDED"
        touch(enc)
    # Decrement metric notes_attested for the attestation period (most recent attestation)
    atts = [a for a in db.stores["attestations"].values()
            if a["note_draft_id"] == draft["id"]]
    if atts:
        atts.sort(key=lambda a: a["attested_at"])
        latest = atts[-1]
        att_dt = parse_iso8601_utc(latest["attested_at"])
        metric = services.metric_for(draft["author_physician_id"], att_dt)
        if metric is not None and metric.get("notes_attested", 0) > 0:
            metric["notes_attested"] -= 1
            touch(metric)
    touch(draft)
    return draft, 200


def void_draft(user, draft_id):
    draft = get_entity("note_drafts", draft_id, "note_draft")
    if user["role"] == "Physician" and user["user_id"] != draft["author_physician_id"]:
        raise unauthorized("only the author may void the draft")
    if draft["status"] not in ("DRAFT", "EDITED", "IN_REVIEW", "AMENDED"):
        raise invalid_state("draft cannot be voided from %s" % draft["status"])
    draft["status"] = "VOID"
    enc = services.get_encounter_of_draft(draft)
    if enc is not None:
        services.update_encounter_documentation_status(enc)
        touch(enc)
    touch(draft)
    return draft, 200


def list_draft_fields(user, draft_id):
    from flask import request
    get_entity("note_drafts", draft_id, "note_draft")
    items = [f for f in db.stores["note_fields"].values() if f["note_draft_id"] == draft_id]
    src = request.args.get("source")
    if src is not None:
        items = [f for f in items if f.get("source") == src]
    val = request.args.get("validated")
    if val is not None:
        v = val.lower() in ("true", "1", "yes")
        items = [f for f in items if bool(f.get("validated")) == v]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def list_draft_attestations(user, draft_id):
    from flask import request
    get_entity("note_drafts", draft_id, "note_draft")
    page, meta = _list("attestations", request.args, [],
                       base_filter=lambda a: a["note_draft_id"] == draft_id)
    return page, 200, meta


# ================================================================ code suggestions
def _validate_suggestion_payload(s):
    if not isinstance(s, dict):
        raise bad_request("each suggestion must be an object")
    if "code_type" not in s or "code_value" not in s or "confidence" not in s:
        raise bad_request("each suggestion requires code_type, code_value, confidence")
    if s["code_type"] not in CODE_TYPES:
        raise bad_request("code_type must be DIAGNOSIS|ORDER|BILLING")
    if not is_string(s["code_value"]):
        raise bad_request("code_value must be a string")
    conf = s["confidence"]
    if not is_number(conf) or conf < 0 or conf > 1:
        raise bad_request("confidence must be a number in 0..1")
    conf_dec = Decimal(str(conf))
    if conf_dec != conf_dec.quantize(Decimal("0.0001")):
        raise bad_request("confidence must have at most 4 decimal places")
    if s["code_type"] == "BILLING":
        if "unit_fee_cents" not in s or s["unit_fee_cents"] is None:
            raise bad_request("unit_fee_cents is required for BILLING")
        if not is_int(s["unit_fee_cents"]) or s["unit_fee_cents"] < 0:
            raise bad_request("unit_fee_cents must be an integer >= 0")
        qty = s.get("quantity", 1)
        if not is_int(qty) or qty < 1:
            raise bad_request("quantity must be an integer >= 1")
        adj = s.get("adjustment_pct", 1.0)
        if not is_number(adj) or adj <= 0 or adj > 5.0:
            raise bad_request("adjustment_pct must be > 0 and <= 5.0")


def create_code_suggestions(user, draft_id):
    draft = get_entity("note_drafts", draft_id, "note_draft")
    if user["role"] == "Physician" and user["user_id"] != draft["author_physician_id"]:
        raise unauthorized("only the author may generate suggestions")
    body = get_body()
    require_fields(body, ["suggestions"])
    suggestions = body["suggestions"]
    if not isinstance(suggestions, list):
        raise bad_request("suggestions must be an array")
    for s in suggestions:
        _validate_suggestion_payload(s)
    # code_value format check
    for s in suggestions:
        if not CODE_VALUE_RE.match(s["code_value"]):
            raise ApiError("ERR_CODE_VALUE_MALFORMED", 422,
                           "code_value fails ^[A-Z][0-9A-Z.]{2,15}$")
    # Business: active cap
    existing_active = sum(1 for x in services.suggestions_of_draft(draft_id)
                          if x["status"] in ("SUGGESTED", "MODIFIED"))
    if existing_active + len(suggestions) > services.MAX_ACTIVE_SUGGESTIONS:
        raise ApiError("ERR_CODE_LIMIT_EXCEEDED", 422,
                       "active suggestions would exceed %d" % services.MAX_ACTIVE_SUGGESTIONS)
    # State: draft must not be ATTESTED or VOID
    if draft["status"] in ("ATTESTED", "VOID"):
        raise ApiError("ERR_CODE_SUGGESTION_LOCKED", 409,
                       "draft is %s" % draft["status"])
    created = []
    for s in suggestions:
        sugg = new_entity({
            "note_draft_id": draft_id,
            "code_type": s["code_type"],
            "code_value": s["code_value"],
            "confidence": float(s["confidence"]),
            "quantity": s.get("quantity", 1) if s["code_type"] == "BILLING" else None,
            "unit_fee_cents": s.get("unit_fee_cents") if s["code_type"] == "BILLING" else None,
            "adjustment_pct": float(s.get("adjustment_pct", 1.0)) if s["code_type"] == "BILLING" else None,
            "status": "SUGGESTED",
            "rank": None,
            "line_total_cents": 0,
            "confirmed_by": None,
        })
        sugg["line_total_cents"] = services.line_total_cents(sugg)
        db.stores["code_suggestions"][sugg["id"]] = sugg
        created.append(sugg)
    services.recompute_ranks(draft_id)
    services.recompute_billing_totals(draft)
    return created, 201, {"limit": len(created), "offset": 0,
                          "total_count": len(created), "has_more": False}


def list_code_suggestions(user, draft_id):
    from flask import request
    get_entity("note_drafts", draft_id, "note_draft")
    items = [s for s in db.stores["code_suggestions"].values()
             if s["note_draft_id"] == draft_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    ct = request.args.get("code_type")
    if ct is not None:
        items = [s for s in items if s["code_type"] == ct]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def _get_suggestion_with_authz(user, suggestion_id):
    sugg = get_entity("code_suggestions", suggestion_id, "code_suggestion")
    draft = db.stores["note_drafts"].get(sugg["note_draft_id"])
    if draft is None:
        raise not_found("owning note draft not found")
    if user["role"] == "Physician" and user["user_id"] != draft["author_physician_id"]:
        raise unauthorized("only the author may operate on this suggestion")
    return sugg, draft


def confirm_suggestion(user, suggestion_id):
    sugg, draft = _get_suggestion_with_authz(user, suggestion_id)
    # State: draft must not be ATTESTED or VOID
    if draft["status"] in ("ATTESTED", "VOID"):
        raise ApiError("ERR_CODE_SUGGESTION_LOCKED", 409,
                       "draft is %s" % draft["status"])
    if sugg["status"] not in ("SUGGESTED", "MODIFIED"):
        raise invalid_state("suggestion is not SUGGESTED or MODIFIED")
    # Fiscal cap for BILLING
    if sugg["code_type"] == "BILLING":
        confirmed_total = sum(s["line_total_cents"]
                              for s in services.suggestions_of_draft(draft["id"])
                              if s["code_type"] == "BILLING" and s["status"] == "CONFIRMED")
        if confirmed_total + sugg["line_total_cents"] > services.BILLING_CAP_CENTS:
            raise ApiError("ERR_BILLING_CAP_EXCEEDED", 422,
                           "confirmed billing total would exceed cap")
    sugg["status"] = "CONFIRMED"
    sugg["confirmed_by"] = user["user_id"]
    touch(sugg)
    services.recompute_ranks(draft["id"])
    services.recompute_billing_totals(draft)
    return sugg, 200


def reject_suggestion(user, suggestion_id):
    sugg, draft = _get_suggestion_with_authz(user, suggestion_id)
    if draft["status"] in ("ATTESTED", "VOID"):
        raise ApiError("ERR_CODE_SUGGESTION_LOCKED", 409,
                       "draft is %s" % draft["status"])
    if sugg["status"] not in ("SUGGESTED", "MODIFIED"):
        raise invalid_state("suggestion is not SUGGESTED or MODIFIED")
    sugg["status"] = "REJECTED"
    touch(sugg)
    services.recompute_ranks(draft["id"])
    services.recompute_billing_totals(draft)
    return sugg, 200


def modify_suggestion(user, suggestion_id):
    sugg, draft = _get_suggestion_with_authz(user, suggestion_id)
    if draft["status"] in ("ATTESTED", "VOID"):
        raise ApiError("ERR_CODE_SUGGESTION_LOCKED", 409,
                       "draft is %s" % draft["status"])
    body = get_body()
    require_fields(body, ["new_code_value"])
    if not is_string(body["new_code_value"]):
        raise bad_request("new_code_value must be a string")
    if not CODE_VALUE_RE.match(body["new_code_value"]):
        raise ApiError("ERR_CODE_VALUE_MALFORMED", 422,
                       "new_code_value fails ^[A-Z][0-9A-Z.]{2,15}$")
    new_qty = body.get("new_quantity")
    if new_qty is not None:
        if not is_int(new_qty) or new_qty < 1:
            raise bad_request("new_quantity must be an integer >= 1")
    if sugg["status"] != "SUGGESTED":
        raise invalid_state("suggestion is not SUGGESTED")
    sugg["code_value"] = body["new_code_value"]
    if new_qty is not None:
        sugg["quantity"] = new_qty
    sugg["status"] = "MODIFIED"
    sugg["line_total_cents"] = services.line_total_cents(sugg)
    touch(sugg)
    services.recompute_ranks(draft["id"])
    services.recompute_billing_totals(draft)
    return sugg, 200


# ================================================================ QA samples
def create_qa_sample(user, draft_id):
    draft = get_entity("note_drafts", draft_id, "note_draft")
    body = get_body()
    auditor_id = body.get("auditor_id")
    if auditor_id is not None:
        if not is_string(auditor_id):
            raise bad_request("auditor_id must be a string")
        get_entity("qa_auditors", auditor_id, "qa_auditor")
    sample = new_entity({
        "note_draft_id": draft["id"],
        "auditor_id": auditor_id,
        "status": "QUEUED",
        "sampling_reason": "MANUAL",
        "created_by_user_id": user["user_id"],
        "accuracy_score": None,
        "completeness_score": None,
        "timeliness_score": None,
        "composite_score": None,
        "appeal_count": 0,
        "last_scorer_id": None,
    })
    db.stores["qa_samples"][sample["id"]] = sample
    return sample, 201


def list_draft_qa_samples(user, draft_id):
    from flask import request
    get_entity("note_drafts", draft_id, "note_draft")
    page, meta = _list("qa_samples", request.args, ["status"],
                       base_filter=lambda s: s["note_draft_id"] == draft_id)
    return page, 200, meta


def assign_qa_sample(user, sample_id):
    sample = get_entity("qa_samples", sample_id, "qa_sample")
    body = get_body()
    require_fields(body, ["auditor_id"])
    if not is_string(body["auditor_id"]):
        raise bad_request("auditor_id must be a string")
    auditor = get_entity("qa_auditors", body["auditor_id"], "qa_auditor")
    if sample["status"] != "QUEUED":
        raise invalid_state("sample is not QUEUED")
    if auditor.get("status") != "ACTIVE":
        raise invalid_state("auditor is not ACTIVE")
    # Specialty match
    draft = db.stores["note_drafts"].get(sample["note_draft_id"])
    template = db.stores["note_templates"].get(draft["template_id"]) if draft else None
    spec = template["specialty_code"] if template else None
    if spec is None or spec not in auditor.get("specialty_codes", []):
        raise ApiError("ERR_AUDITOR_SPECIALTY_MISMATCH", 422,
                       "auditor specialty_codes do not cover the draft template specialty")
    sample["auditor_id"] = auditor["id"]
    sample["status"] = "ASSIGNED"
    touch(sample)
    return sample, 200


def _validate_score(name, v):
    if not is_int(v) or v < 0 or v > 100:
        raise bad_request("%s must be an integer 0..100" % name)


def score_qa_sample(user, sample_id):
    sample = get_entity("qa_samples", sample_id, "qa_sample")
    body = get_body()
    require_fields(body, ["accuracy_score", "completeness_score", "timeliness_score"])
    _validate_score("accuracy_score", body["accuracy_score"])
    _validate_score("completeness_score", body["completeness_score"])
    _validate_score("timeliness_score", body["timeliness_score"])
    # State
    if sample["status"] != "ASSIGNED":
        raise invalid_state("sample is not ASSIGNED")
    # Ownership: only the assigned auditor may score
    if user["user_id"] != sample.get("auditor_id"):
        raise unauthorized("only the assigned auditor may score")
    # Segregation of duties: creator may not score
    if sample.get("created_by_user_id") == user["user_id"]:
        raise ApiError("ERR_QA_SELF_REVIEW_FORBIDDEN", 403,
                       "sample creator may not score the sample")
    a = body["accuracy_score"]; c = body["completeness_score"]; t = body["timeliness_score"]
    sample["accuracy_score"] = a
    sample["completeness_score"] = c
    sample["timeliness_score"] = t
    wa, wc, wt = services.QA_W_BASE
    composite = (Decimal(a) * wa + Decimal(c) * wc + Decimal(t) * wt)
    from helpers import round_half_up_int
    sample["composite_score"] = round_half_up_int(composite)
    sample["last_scorer_id"] = user["user_id"]
    sample["status"] = "SCORED"
    touch(sample)
    return sample, 200


def appeal_qa_sample(user, sample_id):
    sample = get_entity("qa_samples", sample_id, "qa_sample")
    body = get_body()
    reason = body.get("reason")
    if reason is not None and not is_string(reason):
        raise bad_request("reason must be a string")
    draft = db.stores["note_drafts"].get(sample["note_draft_id"])
    if draft is None:
        raise not_found("owning note draft not found")
    if user["role"] == "Physician" and user["user_id"] != draft["author_physician_id"]:
        raise unauthorized("only the author may appeal")
    if sample["status"] not in ("SCORED", "RESCORED"):
        raise invalid_state("sample is not SCORED or RESCORED")
    if sample.get("appeal_count", 0) >= 2:
        raise ApiError("ERR_QA_MAX_APPEALS", 422, "appeal_count has reached 2")
    sample["appeal_count"] = sample.get("appeal_count", 0) + 1
    sample["status"] = "APPEALED"
    touch(sample)
    return sample, 200


def rescore_qa_sample(user, sample_id):
    sample = get_entity("qa_samples", sample_id, "qa_sample")
    body = get_body()
    require_fields(body, ["accuracy_score", "completeness_score", "timeliness_score"])
    _validate_score("accuracy_score", body["accuracy_score"])
    _validate_score("completeness_score", body["completeness_score"])
    _validate_score("timeliness_score", body["timeliness_score"])
    if sample["status"] != "APPEALED":
        raise invalid_state("sample is not APPEALED")
    # Rescorer must differ from last_scorer_id AND from created_by_user_id
    if sample.get("last_scorer_id") == user["user_id"]:
        raise ApiError("ERR_QA_SELF_REVIEW_FORBIDDEN", 403,
                       "rescorer must differ from last_scorer_id")
    if sample.get("created_by_user_id") == user["user_id"]:
        raise ApiError("ERR_QA_SELF_REVIEW_FORBIDDEN", 403,
                       "sample creator may not rescore the sample")
    a = body["accuracy_score"]; c = body["completeness_score"]; t = body["timeliness_score"]
    sample["accuracy_score"] = a
    sample["completeness_score"] = c
    sample["timeliness_score"] = t
    wa, wc, wt = services.QA_W_APPEAL
    composite = (Decimal(a) * wa + Decimal(c) * wc + Decimal(t) * wt)
    from helpers import round_half_up_int
    sample["composite_score"] = round_half_up_int(composite)
    sample["last_scorer_id"] = user["user_id"]
    sample["status"] = "RESCORED"
    touch(sample)
    return sample, 200


def close_qa_sample(user, sample_id):
    sample = get_entity("qa_samples", sample_id, "qa_sample")
    if sample["status"] not in ("SCORED", "RESCORED"):
        raise invalid_state("sample is not SCORED or RESCORED")
    sample["status"] = "CLOSED"
    touch(sample)
    return sample, 200


# ================================================================ test-driving
def set_clock(user):
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso8601_utc(body["to_iso8601"])
    if dt is None:
        raise bad_request("to_iso8601 must be a valid ISO8601 timestamp")
    db.set_clock(dt)
    return {"current_utc": fmt_ts(db.get_clock())}, 200


def simulate_transcription(user):
    body = get_body()
    require_fields(body, ["audio_capture_id"])
    if not is_string(body["audio_capture_id"]):
        raise bad_request("audio_capture_id must be a string")
    cap = get_entity("audio_captures", body["audio_capture_id"], "audio_capture")
    enc = get_entity("encounters", cap["encounter_id"], "encounter")
    # Safety: consent must be GRANTED
    if services.active_consent(enc["id"]) is None:
        raise ApiError("ERR_CONSENT_NOT_ACTIVE", 422,
                       "encounter must hold a GRANTED consent")
    if cap["status"] != "CAPTURED":
        raise invalid_state("capture is not CAPTURED")
    cap["status"] = "TRANSCRIBED"
    touch(cap)
    out = _serialize_capture(cap)
    out["audio_capture_id"] = cap["id"]
    return out, 200


def run_retention_sweep(user):
    now_dt = db.get_clock()
    expired_capture_ids = []
    expired_consent_ids = []
    # Expire GRANTED consents on CANCELLED encounters
    for consent in list(db.stores["consents"].values()):
        if consent["status"] != "GRANTED":
            continue
        enc = db.stores["encounters"].get(consent["encounter_id"])
        if enc is None or enc["encounter_status"] != "CANCELLED":
            continue
        now = now_ts()
        consent["status"] = "EXPIRED"
        consent["ended_at"] = now
        consent["end_reason"] = "EXPIRE"
        touch(consent)
        # Cascade: in-flight captures purge with reason CANCEL
        for cap in services.captures_of_encounter(enc["id"]):
            if cap["status"] in ("RECORDING", "PAUSED"):
                cap["status"] = "PURGED"
                cap["purge_reason"] = "CANCEL"
                for iv in cap.get("pause_intervals", []):
                    if iv[1] is None:
                        iv[1] = now
                if cap.get("ended_at") is None:
                    cap["ended_at"] = now
                touch(cap)
        expired_consent_ids.append(consent["id"])
    # Expire TRANSCRIBED captures past retention
    for cap in list(db.stores["audio_captures"].values()):
        if cap["status"] != "TRANSCRIBED":
            continue
        if cap.get("legal_hold"):
            continue
        ended_at = parse_iso8601_utc(cap.get("ended_at") or "")
        if ended_at is None:
            continue
        deadline = ended_at + timedelta(days=cap.get("retention_days_effective",
                                                      cap.get("planned_retention_days", 0)))
        if now_dt >= deadline:
            cap["status"] = "RETENTION_EXPIRED"
            cap["purge_reason"] = "RETENTION"
            touch(cap)
            expired_capture_ids.append(cap["id"])
    return {"expired_capture_ids": expired_capture_ids,
            "expired_consent_ids": expired_consent_ids}, 200


# ================================================================ route table
# (method, path, handler, allowed_roles)
ROUTES = [
    ("POST", "/ambient-clinical-documentation/patients", create_patient, ["PlatformAdmin"]),
    ("GET", "/ambient-clinical-documentation/patients/<patient_id>", get_patient,
     ["PlatformAdmin", "Physician", "ComplianceOfficer", "QAAuditor"]),
    ("GET", "/ambient-clinical-documentation/patients/<patient_id>/encounters", list_patient_encounters,
     ["PlatformAdmin", "Physician", "ComplianceOfficer"]),
    ("GET", "/ambient-clinical-documentation/patients/<patient_id>/consents", list_patient_consents,
     ["Patient", "Physician", "ComplianceOfficer", "PlatformAdmin"]),

    ("POST", "/ambient-clinical-documentation/physicians", create_physician, ["PlatformAdmin"]),
    ("GET", "/ambient-clinical-documentation/physicians/<physician_id>", get_physician,
     ["PlatformAdmin", "Physician", "ComplianceOfficer", "QAAuditor"]),
    ("PATCH", "/ambient-clinical-documentation/physicians/<physician_id>", update_physician,
     ["PlatformAdmin"]),
    ("GET", "/ambient-clinical-documentation/physicians/<physician_id>/encounters", list_physician_encounters,
     ["Physician", "ComplianceOfficer", "PlatformAdmin"]),
    ("GET", "/ambient-clinical-documentation/physicians/<physician_id>/note-drafts", list_physician_drafts,
     ["Physician", "QAAuditor", "ComplianceOfficer", "PlatformAdmin"]),
    ("GET", "/ambient-clinical-documentation/physicians/<physician_id>/attestations", list_physician_attestations,
     ["Physician", "ComplianceOfficer", "PlatformAdmin"]),
    ("GET", "/ambient-clinical-documentation/physicians/<physician_id>/documentation-metrics", list_physician_metrics,
     ["Physician", "ComplianceOfficer", "PlatformAdmin"]),
    ("POST", "/ambient-clinical-documentation/physicians/<physician_id>/documentation-metrics/recompute",
     recompute_physician_metric, ["Physician", "ComplianceOfficer", "PlatformAdmin"]),

    ("POST", "/ambient-clinical-documentation/qa-auditors", create_qa_auditor, ["PlatformAdmin"]),
    ("GET", "/ambient-clinical-documentation/qa-auditors/<auditor_id>", get_qa_auditor,
     ["QAAuditor", "ComplianceOfficer", "PlatformAdmin"]),
    ("GET", "/ambient-clinical-documentation/qa-auditors/<auditor_id>/qa-samples", list_auditor_samples,
     ["QAAuditor", "ComplianceOfficer", "PlatformAdmin"]),

    ("POST", "/ambient-clinical-documentation/note-templates", create_note_template, ["PlatformAdmin"]),
    ("GET", "/ambient-clinical-documentation/note-templates/<template_id>", get_note_template,
     ["PlatformAdmin", "Physician", "ComplianceOfficer", "QAAuditor", "Patient"]),
    ("PATCH", "/ambient-clinical-documentation/note-templates/<template_id>", update_note_template,
     ["PlatformAdmin"]),
    ("GET", "/ambient-clinical-documentation/note-templates/<template_id>/note-drafts", list_template_drafts,
     ["Physician", "QAAuditor", "ComplianceOfficer", "PlatformAdmin"]),

    ("POST", "/ambient-clinical-documentation/encounters", create_encounter, ["Physician"]),
    ("GET", "/ambient-clinical-documentation/encounters/<encounter_id>", get_encounter,
     ["Physician", "Patient", "QAAuditor", "ComplianceOfficer", "PlatformAdmin"]),
    ("POST", "/ambient-clinical-documentation/encounters/<encounter_id>/start", start_encounter,
     ["Physician"]),
    ("POST", "/ambient-clinical-documentation/encounters/<encounter_id>/complete", complete_encounter,
     ["Physician"]),
    ("POST", "/ambient-clinical-documentation/encounters/<encounter_id>/cancel", cancel_encounter,
     ["Physician", "ComplianceOfficer"]),

    ("GET", "/ambient-clinical-documentation/encounters/<encounter_id>/consents", list_encounter_consents,
     ["Patient", "Physician", "ComplianceOfficer", "PlatformAdmin"]),
    ("POST", "/ambient-clinical-documentation/encounters/<encounter_id>/consents", create_consent,
     ["Patient", "ComplianceOfficer"]),
    ("POST", "/ambient-clinical-documentation/consents/<consent_id>/opt-out", opt_out_consent,
     ["Patient"]),
    ("POST", "/ambient-clinical-documentation/consents/<consent_id>/revoke", revoke_consent,
     ["ComplianceOfficer"]),

    ("GET", "/ambient-clinical-documentation/encounters/<encounter_id>/audio-captures", list_encounter_captures,
     ["Physician", "Patient", "ComplianceOfficer", "QAAuditor", "PlatformAdmin"]),
    ("POST", "/ambient-clinical-documentation/encounters/<encounter_id>/audio-captures", create_audio_capture,
     ["Physician"]),
    ("GET", "/ambient-clinical-documentation/audio-captures/<capture_id>", get_audio_capture,
     ["Physician", "ComplianceOfficer", "QAAuditor", "PlatformAdmin"]),
    ("POST", "/ambient-clinical-documentation/audio-captures/<capture_id>/pause", pause_capture,
     ["Physician"]),
    ("POST", "/ambient-clinical-documentation/audio-captures/<capture_id>/resume", resume_capture,
     ["Physician"]),
    ("POST", "/ambient-clinical-documentation/audio-captures/<capture_id>/stop", stop_capture,
     ["Physician"]),
    ("POST", "/ambient-clinical-documentation/audio-captures/<capture_id>/purge", purge_capture,
     ["ComplianceOfficer"]),
    ("POST", "/ambient-clinical-documentation/audio-captures/<capture_id>/legal-hold", legal_hold_capture,
     ["ComplianceOfficer"]),
    ("POST", "/ambient-clinical-documentation/audio-captures/<capture_id>/segments", add_segment,
     ["Physician"]),
    ("GET", "/ambient-clinical-documentation/audio-captures/<capture_id>/segments", list_segments,
     ["Physician", "QAAuditor", "ComplianceOfficer", "PlatformAdmin"]),
    ("POST", "/ambient-clinical-documentation/segments/<segment_id>/reassign-speaker", reassign_segment,
     ["Physician"]),

    ("GET", "/ambient-clinical-documentation/encounters/<encounter_id>/note-drafts", list_encounter_drafts,
     ["Physician", "Patient", "QAAuditor", "ComplianceOfficer", "PlatformAdmin"]),
    ("POST", "/ambient-clinical-documentation/encounters/<encounter_id>/note-drafts", create_note_draft,
     ["Physician"]),
    ("GET", "/ambient-clinical-documentation/note-drafts/<draft_id>", get_note_draft,
     ["Physician", "QAAuditor", "ComplianceOfficer", "PlatformAdmin"]),
    ("PATCH", "/ambient-clinical-documentation/note-drafts/<draft_id>", patch_note_draft,
     ["Physician"]),
    ("POST", "/ambient-clinical-documentation/note-drafts/<draft_id>/submit-review", submit_review_draft,
     ["Physician"]),
    ("POST", "/ambient-clinical-documentation/note-drafts/<draft_id>/regenerate", regenerate_draft,
     ["Physician"]),
    ("POST", "/ambient-clinical-documentation/note-drafts/<draft_id>/attest", attest_draft,
     ["Physician"]),
    ("POST", "/ambient-clinical-documentation/note-drafts/<draft_id>/amend", amend_draft,
     ["Physician"]),
    ("POST", "/ambient-clinical-documentation/note-drafts/<draft_id>/void", void_draft,
     ["Physician", "ComplianceOfficer"]),
    ("GET", "/ambient-clinical-documentation/note-drafts/<draft_id>/fields", list_draft_fields,
     ["Physician", "QAAuditor", "ComplianceOfficer", "PlatformAdmin"]),
    ("GET", "/ambient-clinical-documentation/note-drafts/<draft_id>/attestations", list_draft_attestations,
     ["Physician", "QAAuditor", "ComplianceOfficer", "PlatformAdmin"]),

    ("POST", "/ambient-clinical-documentation/note-drafts/<draft_id>/code-suggestions", create_code_suggestions,
     ["Physician"]),
    ("GET", "/ambient-clinical-documentation/note-drafts/<draft_id>/code-suggestions", list_code_suggestions,
     ["Physician", "QAAuditor", "ComplianceOfficer", "PlatformAdmin"]),
    ("POST", "/ambient-clinical-documentation/code-suggestions/<suggestion_id>/confirm", confirm_suggestion,
     ["Physician"]),
    ("POST", "/ambient-clinical-documentation/code-suggestions/<suggestion_id>/reject", reject_suggestion,
     ["Physician"]),
    ("POST", "/ambient-clinical-documentation/code-suggestions/<suggestion_id>/modify", modify_suggestion,
     ["Physician"]),

    ("POST", "/ambient-clinical-documentation/note-drafts/<draft_id>/qa-samples", create_qa_sample,
     ["ComplianceOfficer", "QAAuditor"]),
    ("GET", "/ambient-clinical-documentation/note-drafts/<draft_id>/qa-samples", list_draft_qa_samples,
     ["Physician", "QAAuditor", "ComplianceOfficer", "PlatformAdmin"]),
    ("POST", "/ambient-clinical-documentation/qa-samples/<sample_id>/assign", assign_qa_sample,
     ["QAAuditor", "ComplianceOfficer"]),
    ("POST", "/ambient-clinical-documentation/qa-samples/<sample_id>/score", score_qa_sample,
     ["QAAuditor"]),
    ("POST", "/ambient-clinical-documentation/qa-samples/<sample_id>/appeal", appeal_qa_sample,
     ["Physician"]),
    ("POST", "/ambient-clinical-documentation/qa-samples/<sample_id>/rescore", rescore_qa_sample,
     ["QAAuditor"]),
    ("POST", "/ambient-clinical-documentation/qa-samples/<sample_id>/close", close_qa_sample,
     ["QAAuditor", "ComplianceOfficer"]),

    ("POST", "/ambient-clinical-documentation/_clock/set_current_utc", set_clock, ["PlatformAdmin"]),
    ("POST", "/ambient-clinical-documentation/_audio/simulate-transcription", simulate_transcription,
     ["PlatformAdmin"]),
    ("POST", "/ambient-clinical-documentation/_maintenance/run-retention-sweep", run_retention_sweep,
     ["PlatformAdmin"]),
]
