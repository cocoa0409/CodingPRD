"""Session and SessionNote endpoints (PRD §3.4)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from calc import PAYER_ALLOWED_RATIO, provisional_quote, session_rate_cents
from errors import fail
from middleware import Body, identity, qenum, qstr, require_roles
from response import ok, paginate
from serializers import ser
from store import (
    MODALITIES,
    SCHEDULING_BUFFER_MINUTES,
    active_patient_count,
    all_rows,
    benefit_status,
    create_row,
    get,
    newest_note,
    newest_verified_snapshot,
    now,
    notes_for,
    open_slot_count,
    refresh_posture,
    require,
    session_length_minutes,
    set_derived,
    sort_asc,
    table,
    visit_count_year,
)
from util import dec, fmt_ts, minutes_between, minute_of_day, parse_ts, round_half_up, utc_weekday

bp = Blueprint("sessions", __name__)

SESSION_STATUSES = {"REQUESTED", "SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW"}
BILLING_STATES = {"UNBILLED", "CLAIM_SUBMITTED", "PAYER_PAID", "DENIED", "WRITTEN_OFF"}
NOTE_STATUSES = {"DRAFT", "SIGNED", "LOCKED"}

NON_TERMINAL = ("REQUESTED", "SCHEDULED")


# ---------------------------------------------------------------- helpers


def _owns(session, ident):
    if ident["role"] == "OpsAdmin":
        return
    if ident["role"] != "Clinician":
        raise fail("ERR_UNAUTHORIZED")
    if session.get("clinician_id") != ident["id"]:
        raise fail("ERR_UNAUTHORIZED")


def _read_scope(session, ident):
    if ident["role"] == "Patient" and session.get("patient_id") != ident["id"]:
        raise fail("ERR_UNAUTHORIZED")


def _cancel_duplicate_start(session):
    """PRD §3.4: a session booked on the same patient/scheduled_start supersedes the earlier one."""
    for other in all_rows("sessions"):
        if other["id"] == session["id"]:
            continue
        if other.get("patient_id") != session.get("patient_id"):
            continue
        if other.get("scheduled_start") != session.get("scheduled_start"):
            continue
        if other.get("status") not in NON_TERMINAL:
            continue
        other["status"] = "CANCELLED"
        set_derived(other, "slot_consumed", False)
        other["version"] = int(other.get("version") or 1) + 1
        other["updated_at"] = fmt_ts(now())
        clinician = get("clinicians", other.get("clinician_id"))
        if clinician is not None:
            set_derived(clinician, "open_slot_count", open_slot_count(clinician))


def _interval_checks(session, start, end, ignore_self=True):
    """PRD §3.4: availability first, then clinician overlap, then patient overlap."""
    clinician = get("clinicians", session.get("clinician_id"))
    patient = get("patients", session.get("patient_id"))
    duration = minutes_between(start, end)
    if duration <= 0:
        raise fail("ERR_INVALID_REQUEST", "scheduled_end must be strictly after scheduled_start.")

    if clinician is not None:
        weekday = utc_weekday(start)
        start_minute = minute_of_day(start)
        covered = False
        for block in clinician.get("availability_blocks") or []:
            try:
                same_day = int(block["weekday"]) == weekday
                starts_ok = int(block["start_minute"]) <= start_minute
                ends_ok = start_minute + duration <= int(block["end_minute"])
            except (KeyError, TypeError, ValueError):
                continue
            if same_day and starts_ok and ends_ok:
                covered = True
                break
        if not covered:
            raise fail("ERR_CLINICIAN_SLOT_CONFLICT")

        buffer = timedelta(minutes=SCHEDULING_BUFFER_MINUTES)
        for other in all_rows("sessions"):
            if ignore_self and other["id"] == session["id"]:
                continue
            if other.get("clinician_id") != session.get("clinician_id"):
                continue
            if other.get("status") not in NON_TERMINAL:
                continue
            other_start = other.get("_start_dt")
            other_end = other.get("_end_dt")
            if other_start is None or other_end is None:
                continue
            if start < other_end + buffer and other_start < end + buffer:
                raise fail("ERR_CLINICIAN_SLOT_CONFLICT")

    if patient is not None:
        for other in all_rows("sessions"):
            if ignore_self and other["id"] == session["id"]:
                continue
            if other.get("patient_id") != session.get("patient_id"):
                continue
            if other.get("status") not in NON_TERMINAL:
                continue
            other_start = other.get("_start_dt")
            other_end = other.get("_end_dt")
            if other_start is None or other_end is None:
                continue
            if start < other_end and other_start < end:
                raise fail("ERR_PATIENT_DOUBLE_BOOKED")


def _quote_for(patient, session):
    """Provisional quote (PRD §3.3): the snapshot in force, carrying the copay offset.

    S is the session's allowed envelope, which is zero when no rate row resolves.
    """
    snapshot = newest_verified_snapshot(patient["id"])
    if snapshot is None:
        return None
    allowed = round_half_up(dec(session_rate_cents(session)) * PAYER_ALLOWED_RATIO)
    return provisional_quote(snapshot, allowed)


# ---------------------------------------------------------------- collection


@bp.post("/sessions")
@require_roles("OpsAdmin")
def create_session():
    body = Body.read()
    clinician_id = body.string("clinician_id")
    patient_id = body.string("patient_id")
    scheduled_start = body.instant("scheduled_start")
    scheduled_end = body.instant("scheduled_end")
    cpt_code = body.string("cpt_code")
    modality = body.enum("modality", MODALITIES)
    body.finish()

    require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    require("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    if scheduled_end <= scheduled_start:
        raise fail("ERR_INVALID_REQUEST", "scheduled_end must be strictly after scheduled_start.")

    row = create_row(
        "sessions",
        clinician_id=clinician_id,
        patient_id=patient_id,
        scheduled_start=fmt_ts(scheduled_start),
        scheduled_end=fmt_ts(scheduled_end),
        cpt_code=cpt_code,
        modality=modality,
        status="REQUESTED",
        billing_state="UNBILLED",
        quoted_cost_share_cents=None,
        slot_consumed=False,
        claim_id=None,
        _start_dt=scheduled_start,
        _end_dt=scheduled_end,
    )
    _cancel_duplicate_start(row)
    return ok(ser("sessions", row), 201)


@bp.get("/sessions")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician", "Patient")
def list_sessions():
    ident = identity()
    clinician_id = qstr("clinician_id")
    patient_id = qstr("patient_id")
    status = qenum("status", SESSION_STATUSES)
    billing_state = qenum("billing_state", BILLING_STATES)

    rows = sort_asc(all_rows("sessions"))
    if ident["role"] == "Clinician":
        rows = [r for r in rows if r.get("clinician_id") == ident["id"]]
    elif ident["role"] == "Patient":
        rows = [r for r in rows if r.get("patient_id") == ident["id"]]

    out = [ser("sessions", r) for r in rows]
    if clinician_id is not None:
        out = [r for r in out if r.get("clinician_id") == clinician_id]
    if patient_id is not None:
        out = [r for r in out if r.get("patient_id") == patient_id]
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    if billing_state is not None:
        out = [r for r in out if r.get("billing_state") == billing_state]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.get("/sessions/<session_id>")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician", "Patient")
def get_session(session_id):
    ident = identity()
    row = require("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    _read_scope(row, ident)
    return ok(ser("sessions", row), 200)


@bp.get("/patients/<patient_id>/sessions")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician", "Patient")
def list_patient_sessions(patient_id):
    ident = identity()
    patient = require("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    if ident["role"] == "Patient" and patient["id"] != ident["id"]:
        raise fail("ERR_UNAUTHORIZED")
    status = qenum("status", SESSION_STATUSES)
    billing_state = qenum("billing_state", BILLING_STATES)
    out = [
        ser("sessions", r)
        for r in sort_asc(all_rows("sessions"))
        if r.get("patient_id") == patient_id
    ]
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    if billing_state is not None:
        out = [r for r in out if r.get("billing_state") == billing_state]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


# ---------------------------------------------------------------- transitions


@bp.post("/sessions/<session_id>/schedule")
@require_roles("Clinician", "OpsAdmin")
def schedule_session(session_id):
    ident = identity()
    session = require("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    _owns(session, ident)
    if session.get("status") != "REQUESTED":
        raise fail("ERR_INVALID_STATE")

    clinician = get("clinicians", session.get("clinician_id"))
    patient = get("patients", session.get("patient_id"))
    if clinician is None:
        raise fail("ERR_CLINICIAN_NOT_FOUND")
    if patient is None:
        raise fail("ERR_PATIENT_NOT_FOUND")

    # PRD §3.4: "The clinician's `billing_posture` must be `BILLABLE` or
    # `GATED`; a `FROZEN` clinician cannot have sessions scheduled."  GATED is
    # enough to book on; only FROZEN is refused.
    posture = clinician.get("billing_posture")
    if posture == "FROZEN":
        raise fail("ERR_CLINICIAN_NOT_BILLABLE")
    if benefit_status(patient) != "VERIFIED":
        raise fail("ERR_BENEFIT_UNVERIFIED")

    start = session.get("_start_dt")
    end = session.get("_end_dt")
    _cancel_duplicate_start(session)
    _interval_checks(session, start, end)

    session["status"] = "SCHEDULED"
    session["slot_consumed"] = True
    session["quoted_cost_share_cents"] = _quote_for(patient, session)
    set_derived(clinician, "open_slot_count", open_slot_count(clinician))
    set_derived(patient, "visit_count_year", visit_count_year(patient))
    session["version"] = int(session.get("version") or 1) + 1
    session["updated_at"] = fmt_ts(now())
    return ok(ser("sessions", session), 200)


@bp.post("/sessions/<session_id>/complete")
@require_roles("Clinician", "OpsAdmin")
def complete_session(session_id):
    ident = identity()
    session = require("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    _owns(session, ident)
    if session.get("status") != "SCHEDULED":
        raise fail("ERR_INVALID_STATE")

    clinician = get("clinicians", session.get("clinician_id"))
    patient = get("patients", session.get("patient_id"))
    if clinician is None:
        raise fail("ERR_CLINICIAN_NOT_FOUND")
    if patient is None or session.get("patient_id") is None:
        raise fail("ERR_INVALID_REQUEST", "The session has no attached patient.")

    # PRD §3.4 names the delivery preconditions exhaustively — the patient is
    # attached, a SIGNED note exists, the start is not later than the clock, and
    # the owning clinician is not `OFFBOARDED` — and says nothing about the
    # posture.  §3.7 relies on that gap: "Delivery is deliberately not blocked by
    # the offboarding completeness gate, so escalation can reach a plan while it
    # is still reassignable."  The §2.9 safety gate attaches to completion's
    # claim-side consequences, not to the act of recording delivery.
    notes = notes_for(session["id"])
    if not notes:
        raise fail("ERR_DOCUMENTATION_MISSING")
    newest = notes[-1]
    if newest.get("status") != "SIGNED":
        if any(n.get("status") == "SIGNED" for n in notes):
            raise fail("ERR_NOTE_SUPERSEDED")
        raise fail("ERR_DOCUMENTATION_MISSING")

    length = session_length_minutes(session)
    for note in notes:
        if int(note.get("duration_minutes") or 0) != length:
            raise fail("ERR_DURATION_MISMATCH")

    start = session.get("_start_dt")
    if start is not None and start > now():
        raise fail("ERR_INVALID_STATE", "The scheduled start is later than the logical clock.")
    if clinician.get("status") == "OFFBOARDED":
        raise fail("ERR_INVALID_STATE")

    session["status"] = "COMPLETED"
    session["slot_consumed"] = False
    set_derived(clinician, "open_slot_count", open_slot_count(clinician))
    set_derived(patient, "visit_count_year", visit_count_year(patient))
    session["version"] = int(session.get("version") or 1) + 1
    session["updated_at"] = fmt_ts(now())

    if clinician.get("status") in ("OFFBOARDING", "OFFBOARDED"):
        for plan in all_rows("continuity_plans"):
            if plan.get("clinician_id") != clinician["id"]:
                continue
            if plan.get("patient_id") != patient["id"]:
                continue
            if plan.get("status") == "PENDING":
                plan["status"] = "ESCALATED"
                plan["version"] = int(plan.get("version") or 1) + 1
                plan["updated_at"] = fmt_ts(now())
                patient["swap_requested"] = True
    return ok(ser("sessions", session), 200)


@bp.post("/sessions/<session_id>/reopen")
@require_roles("OpsAdmin")
def reopen_session(session_id):
    session = require("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    if session.get("status") != "COMPLETED":
        raise fail("ERR_INVALID_STATE")
    if session.get("billing_state") != "UNBILLED":
        raise fail("ERR_INVALID_STATE")
    if any(c.get("session_id") == session["id"] for c in all_rows("claims")):
        raise fail("ERR_INVALID_STATE")

    clinician = get("clinicians", session.get("clinician_id"))
    patient = get("patients", session.get("patient_id"))
    session["status"] = "SCHEDULED"
    session["slot_consumed"] = True
    if clinician is not None:
        set_derived(clinician, "open_slot_count", open_slot_count(clinician))
    if patient is not None:
        set_derived(patient, "visit_count_year", visit_count_year(patient))
    session["version"] = int(session.get("version") or 1) + 1
    session["updated_at"] = fmt_ts(now())
    return ok(ser("sessions", session), 200)


@bp.post("/sessions/<session_id>/cancel")
@require_roles("Clinician", "OpsAdmin")
def cancel_session(session_id):
    ident = identity()
    session = require("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    _owns(session, ident)
    if session.get("status") not in NON_TERMINAL:
        raise fail("ERR_INVALID_STATE")
    start = session.get("_start_dt")
    if start is not None and start <= now():
        raise fail("ERR_INVALID_STATE", "A session may only be cancelled before it starts.")

    clinician = get("clinicians", session.get("clinician_id"))
    session["status"] = "CANCELLED"
    session["slot_consumed"] = False
    if clinician is not None:
        set_derived(clinician, "open_slot_count", open_slot_count(clinician))
    session["version"] = int(session.get("version") or 1) + 1
    session["updated_at"] = fmt_ts(now())
    return ok(ser("sessions", session), 200)


@bp.post("/sessions/<session_id>/reschedule")
@require_roles("Clinician", "OpsAdmin")
def reschedule_session(session_id):
    ident = identity()
    session = require("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    _owns(session, ident)
    body = Body.read()
    scheduled_start = body.instant("scheduled_start")
    scheduled_end = body.instant("scheduled_end")
    body.finish()
    if session.get("status") != "CANCELLED":
        raise fail("ERR_INVALID_STATE")
    if scheduled_end <= scheduled_start:
        raise fail("ERR_INVALID_REQUEST", "scheduled_end must be strictly after scheduled_start.")

    clinician = get("clinicians", session.get("clinician_id"))
    patient = get("patients", session.get("patient_id"))
    if patient is None:
        raise fail("ERR_PATIENT_NOT_FOUND")
    if benefit_status(patient) != "VERIFIED":
        raise fail("ERR_BENEFIT_UNVERIFIED")

    old_start, old_end = session.get("_start_dt"), session.get("_end_dt")
    session["_start_dt"] = scheduled_start
    session["_end_dt"] = scheduled_end
    session["scheduled_start"] = fmt_ts(scheduled_start)
    session["scheduled_end"] = fmt_ts(scheduled_end)
    try:
        _interval_checks(session, scheduled_start, scheduled_end)
    except Exception:
        session["_start_dt"] = old_start
        session["_end_dt"] = old_end
        session["scheduled_start"] = fmt_ts(old_start)
        session["scheduled_end"] = fmt_ts(old_end)
        raise

    session["status"] = "SCHEDULED"
    session["slot_consumed"] = True
    session["quoted_cost_share_cents"] = _quote_for(patient, session)
    if clinician is not None:
        set_derived(clinician, "open_slot_count", open_slot_count(clinician))
    session["version"] = int(session.get("version") or 1) + 1
    session["updated_at"] = fmt_ts(now())
    return ok(ser("sessions", session), 200)


# ---------------------------------------------------------------- notes


def _session_and_note(session_id, note_id):
    session = require("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    note = get("session_notes", note_id)
    if note is None or note.get("session_id") != session_id:
        raise fail("ERR_NOTE_NOT_FOUND")
    return session, note


@bp.post("/sessions/<session_id>/notes")
@require_roles("Clinician")
def create_note(session_id):
    ident = identity()
    session = require("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    if session.get("clinician_id") != ident["id"]:
        raise fail("ERR_UNAUTHORIZED")
    body = Body.read()
    diagnosis_code = body.string("diagnosis_code")
    duration_minutes = body.integer("duration_minutes", minimum=1)
    cpt_code = body.string("cpt_code")
    narrative = body.string("narrative", allow_empty=True)
    expected_version = body.version("expected_session_version")
    body.finish()

    if int(session.get("version") or 1) != expected_version:
        raise fail("ERR_STALE_VERSION")

    existing = notes_for(session_id)
    highest = max([int(n.get("note_version") or 0) for n in existing] or [0])
    row = create_row(
        "session_notes",
        session_id=session_id,
        diagnosis_code=diagnosis_code,
        duration_minutes=duration_minutes,
        cpt_code=cpt_code,
        narrative=narrative,
        status="DRAFT",
        signed_at=None,
        signer_clinician_id=None,
        note_version=highest + 1,
    )
    session["version"] = int(session.get("version") or 1) + 1
    session["updated_at"] = fmt_ts(now())
    return ok(ser("session_notes", row), 201)


@bp.get("/sessions/<session_id>/notes")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def list_notes(session_id):
    require("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    status = qenum("status", NOTE_STATUSES)
    out = [ser("session_notes", r) for r in notes_for(session_id)]
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.post("/sessions/<session_id>/notes/<note_id>/sign")
@require_roles("Clinician")
def sign_note(session_id, note_id):
    ident = identity()
    session, note = _session_and_note(session_id, note_id)
    if session.get("clinician_id") != ident["id"]:
        raise fail("ERR_UNAUTHORIZED")
    if note.get("status") != "DRAFT":
        raise fail("ERR_INVALID_STATE")
    if not note.get("diagnosis_code"):
        raise fail("ERR_INVALID_STATE", "diagnosis_code must be present before signing.")
    if not (note.get("narrative") or "").strip():
        raise fail("ERR_INVALID_STATE", "narrative must be non-empty before signing.")
    duration = int(note.get("duration_minutes") or 0)
    if not 45 <= duration <= 120:
        raise fail("ERR_INVALID_STATE", "duration_minutes must be between 45 and 120 inclusive.")

    for other in notes_for(session_id):
        if other["id"] == note["id"]:
            continue
        if other.get("status") == "SIGNED":
            other["status"] = "LOCKED"
            other["version"] = int(other.get("version") or 1) + 1
            other["updated_at"] = fmt_ts(now())

    note["status"] = "SIGNED"
    note["signed_at"] = fmt_ts(now())
    note["signer_clinician_id"] = ident["id"]
    note["version"] = int(note.get("version") or 1) + 1
    note["updated_at"] = fmt_ts(now())
    return ok(ser("session_notes", note), 200)