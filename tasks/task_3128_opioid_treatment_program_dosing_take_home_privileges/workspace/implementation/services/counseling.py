"""Counseling sessions and treatment plan reviews (PRD 3.8; SCAFFOLD R6)."""
from datetime import timedelta

import db
from constants import PHASE_CADENCE
from errors import ApiError
from services import entity, patient as patient_svc, stability


def session_of(session_id):
    row = db.counseling_sessions.get(session_id)
    if row is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", "No CounselingSession with the supplied id")
    return row


def review_of(review_id):
    row = db.treatment_plan_reviews.get(review_id)
    if row is None:
        raise ApiError("ERR_REVIEW_NOT_FOUND", "No TreatmentPlanReview with the supplied id")
    return row


def create_session(patient, session_type, scheduled_datetime, duration_minutes, counselor_staff_id):
    row = entity.make_session(
        patient, session_type, scheduled_datetime, duration_minutes, counselor_staff_id
    )
    db.counseling_sessions[row["id"]] = row
    return row


def complete_session(session, attended_minutes, actor):
    if session.get("status") != "SCHEDULED":
        raise ApiError("ERR_INVALID_REQUEST", "The session is not SCHEDULED")
    if attended_minutes is None or attended_minutes < 0:
        raise ApiError("ERR_INVALID_REQUEST", "attended_minutes must be a non-negative integer")
    if attended_minutes > (session.get("duration_minutes") or 0):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "attended_minutes may not exceed the contracted duration_minutes",
        )
    session["status"] = "COMPLETED"
    session["completed_at"] = db.fmt_dt(db.clock_dt())
    session["attended_minutes"] = attended_minutes
    db.stamp(session)
    patient = db.patients.get(session.get("patient_id"))
    if patient is not None:
        patient_svc.refresh_counseling(patient)
        stability.refresh_patient(patient, publish="A")
        db.stamp(patient)
    return session


def no_show(session, actor):
    session["status"] = "NO_SHOW"
    db.stamp(session)
    patient = db.patients.get(session.get("patient_id"))
    if patient is not None:
        patient_svc.refresh_counseling(patient)
        stability.refresh_patient(patient, publish="A")
        db.stamp(patient)
    return session


def create_review(patient, reviewer_physician_id, reviewed_at, signed_off):
    row = entity.make_review(patient, reviewer_physician_id, reviewed_at, signed_off)
    cadence = PHASE_CADENCE.get(patient.get("treatment_phase"), 7)
    row["cadence_days_applied"] = cadence
    moment = db.parse_iso(reviewed_at)
    if moment is not None:
        row["next_due_at"] = db.fmt_dt(moment + timedelta(days=cadence))
    db.treatment_plan_reviews[row["id"]] = row
    patient_svc.refresh_counseling(patient)
    stability.refresh_patient(patient, publish="A")
    db.stamp(patient)
    return row