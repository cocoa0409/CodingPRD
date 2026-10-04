"""Payload factories — one per entity, input fields only (PRD §3).

Unique-constrained fields (email, version_code, exam_code, window_code,
module_code, session_code) default to auto-generated values so composed
fixtures never trip the duplicate-value ERR_INVALID_REQUEST gate; every
factory accepts overrides for the values a test needs to control.
"""
import itertools

from . import constants as C

_counter = itertools.count(1)


def _uniq(tag: str) -> str:
    return f"{tag}-{next(_counter):04d}"


# ---------------------------------------------------------------------------
# Candidates (PRD §3.1: email + full_name)
# ---------------------------------------------------------------------------
def create_candidate_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {"email": f"candidate-{n}@example.com", "full_name": f"Test Candidate {n}"}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Syllabus versions and exams (PRD §3.2)
# ---------------------------------------------------------------------------
def create_syllabus_version_payload(**overrides) -> dict:
    defaults = {"version_code": _uniq("SYL")}
    defaults.update(overrides)
    return defaults


def create_exam_payload(syllabus_version_id, **overrides) -> dict:
    defaults = {
        "exam_code": _uniq("EX"),
        "title": "Examination",
        "credit_hours": C.PRELIM_EXAM_CREDIT_HOURS,
        "syllabus_version_id": syllabus_version_id,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Exam windows (PRD §3.3). Defaults are the standard P-2026-10 sitting.
# ---------------------------------------------------------------------------
def create_exam_window_payload(exam_id, **overrides) -> dict:
    defaults = {
        "exam_id": exam_id,
        "window_code": _uniq("WIN"),
        "registration_opens_at": C.WINDOW_REGISTRATION_OPENS,
        "registration_deadline": C.WINDOW_REGISTRATION_DEADLINE,
        "testing_starts_at": C.WINDOW_TESTING_STARTS,
        "testing_ends_at": C.WINDOW_TESTING_ENDS,
        "capacity": C.WINDOW_CAPACITY_DEFAULT,
        "base_fee_cents": C.WINDOW_BASE_FEE_CENTS,
        "late_surcharge_cents": C.WINDOW_LATE_SURCHARGE_CENTS,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Registrations, scores, pass marks (PRD §3.3)
# ---------------------------------------------------------------------------
def create_exam_registration_payload(exam_window_id, **overrides) -> dict:
    defaults = {"exam_window_id": exam_window_id}
    defaults.update(overrides)
    return defaults


def record_score_payload(raw_score=C.RAW_SCORE_AT_MARK, **overrides) -> dict:
    defaults = {"raw_score": raw_score}
    defaults.update(overrides)
    return defaults


def create_pass_mark_setting_payload(proposed_mark=C.PASS_MARK_RATIFIED,
                                     expected_exam_window_version=1, **overrides) -> dict:
    defaults = {
        "proposed_mark": proposed_mark,
        "expected_exam_window_version": expected_exam_window_version,
    }
    defaults.update(overrides)
    return defaults


def ratify_pass_mark_payload(ratified_mark=C.PASS_MARK_RATIFIED, **overrides) -> dict:
    defaults = {"ratified_mark": ratified_mark}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# VEE submissions (PRD §3.4)
# ---------------------------------------------------------------------------
def create_vee_submission_payload(topic="ECONOMICS", **overrides) -> dict:
    defaults = {
        "topic": topic,
        "university": C.VEE_UNIVERSITY,
        "course_title": C.VEE_COURSE_TITLES.get(topic, "GN101"),
        "grade_points": C.VEE_GRADE_PASS,
    }
    defaults.update(overrides)
    return defaults


def review_vee_submission_payload(decision="APPROVE", **overrides) -> dict:
    defaults = {"decision": decision, "reviewer_note": "ok"}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Tracks, modules, attempts (PRD §3.5)
# ---------------------------------------------------------------------------
def create_track_enrollment_payload(track_code=C.TRACK_QFI, **overrides) -> dict:
    defaults = {"track_code": track_code}
    defaults.update(overrides)
    return defaults


def create_module_payload(**overrides) -> dict:
    defaults = {
        "module_code": _uniq("MOD"),
        "track_code": C.TRACK_QFI,
        "sequence_index": 1,
        "title": "Module",
        "passing_score": C.MODULE_PASSING_SCORE,
        "cooldown_days": C.DEFAULT_COOLDOWN_DAYS,
    }
    defaults.update(overrides)
    return defaults


def create_module_attempt_payload(track_enrollment_id, module_id, **overrides) -> dict:
    defaults = {"track_enrollment_id": track_enrollment_id, "module_id": module_id}
    defaults.update(overrides)
    return defaults


def submit_module_attempt_payload(score=C.SUBMIT_SCORE_PASS, **overrides) -> dict:
    defaults = {"score": score}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Project assessments (PRD §3.6)
# ---------------------------------------------------------------------------
def create_project_assessment_payload(track_enrollment_id, **overrides) -> dict:
    defaults = {"track_enrollment_id": track_enrollment_id, "title": C.PROJECT_TITLE}
    defaults.update(overrides)
    return defaults


def grade_project_payload(score=C.PROJECT_SCORE_G1, **overrides) -> dict:
    defaults = {"score": score}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Professionalism course (PRD §3.7)
# ---------------------------------------------------------------------------
def create_course_session_payload(**overrides) -> dict:
    defaults = {
        "session_code": _uniq("APC"),
        "starts_at": C.SESSION_STARTS,
        "ends_at": C.SESSION_ENDS,
        "capacity": C.SESSION_CAPACITY_DEFAULT,
    }
    defaults.update(overrides)
    return defaults


def create_course_attendance_payload(course_session_id, **overrides) -> dict:
    defaults = {"course_session_id": course_session_id}
    defaults.update(overrides)
    return defaults


def verify_course_attendance_payload(outcome="ATTENDED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Transfer credit (PRD §3.8)
# ---------------------------------------------------------------------------
def create_transfer_credit_request_payload(source_body="IFOA", claimed_hours=10, **overrides) -> dict:
    defaults = {"source_body": source_body, "claimed_hours": claimed_hours}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# CPD attestations (PRD §3.8)
# ---------------------------------------------------------------------------
def create_cpd_attestation_payload(**overrides) -> dict:
    defaults = {
        "cycle_year": C.CPD_CYCLE_YEAR,
        "attested_hours": C.CPD_ATTESTED_EXACT,
        "carryover_hours": 0,
    }
    defaults.update(overrides)
    return defaults


def verify_cpd_attestation_payload(verified_hours=C.CPD_VERIFY_EXACT, **overrides) -> dict:
    defaults = {"verified_hours": verified_hours}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Discipline cases (PRD §3.9)
# ---------------------------------------------------------------------------
def create_discipline_case_payload(candidate_id, **overrides) -> dict:
    defaults = {
        "candidate_id": candidate_id,
        "charge": "Professional conduct violation",
        "severity": C.SEVERITY_MID,
    }
    defaults.update(overrides)
    return defaults


def sanction_discipline_case_payload(resolution="REPRIMAND", **overrides) -> dict:
    defaults = {"resolution": resolution}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Credential applications (PRD §3.9)
# ---------------------------------------------------------------------------
def create_credential_application_payload(credential="ASA", expected_candidate_version=1, **overrides) -> dict:
    defaults = {
        "credential": credential,
        "expected_candidate_version": expected_candidate_version,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
def set_clock_payload(to_iso8601=C.CLOCK_DEFAULT, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
