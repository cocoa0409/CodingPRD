"""Tutors, tutor assignments and support sessions (PRD 3.7)."""

from decimal import Decimal

from flask import Blueprint

import calc
import derive
import helpers as h
import store as st
from errors import ApiError
from store import D, q2
from validation import (authenticate, bad_request, forbid, json_body,
                        want_action, want_decimal, want_enum, want_instant,
                        want_string, want_string_list)

bp = Blueprint("support", __name__)

TUTOR_READ_ONE = ["LearningSpecialist", "AcademicAdvisor", "ComplianceOfficer",
                  "CertificationOfficer", "Tutor"]
TUTOR_LIST = ["LearningSpecialist", "AcademicAdvisor", "ComplianceOfficer",
              "CertificationOfficer"]
ASSIGNMENT_READ = ["LearningSpecialist", "AcademicAdvisor", "ComplianceOfficer",
                   "Tutor"]
SESSION_READ_ONE = ["LearningSpecialist", "AcademicAdvisor", "ComplianceOfficer",
                    "Tutor", "StudentAthlete"]
SESSION_LIST = ["LearningSpecialist", "AcademicAdvisor", "ComplianceOfficer", "Tutor"]

TERMINATED_REASONS = ("TUTOR_SUSPENDED", "SPECIALIST_REQUEST", "TERM_CLOSED",
                      "INCIDENT_SUBSTANTIATED", "ENROLLMENT_DROPPED")


# ------------------------------------------------------------------- tutors
@bp.get("/athletics/tutors/<tutor_id>")
def get_tutor(tutor_id):
    authenticate(TUTOR_READ_ONE)
    return h.ok(h.tutor_or_404(tutor_id))


@bp.get("/athletics/tutors")
def list_tutors():
    authenticate(TUTOR_LIST)
    return h.listing(st.by_created(list(st.tutors.values())),
                     ("status", "subject_code"),
                     {"subject_code": "__subject_codes__"})


@bp.post("/athletics/tutors")
def create_tutor():
    authenticate(["LearningSpecialist"])
    body = json_body()
    full_name = want_string(body, "full_name")
    subject_codes = want_string_list(body, "subject_codes", default=[])
    max_weekly_hours = want_decimal(body, "max_weekly_hours", required=False,
                                    default=Decimal("20"), maximum=40)
    if max_weekly_hours <= 0:
        raise bad_request("Field 'max_weekly_hours' must be greater than zero.")

    tutor = {
        "full_name": full_name,
        "subject_codes": list(subject_codes),
        "max_weekly_hours": q2(max_weekly_hours),
        "status": "UNTRAINED",
        "training_completed_term_index": None,
        "training_valid_through_term_index": None,
        "penalty_points": 0,
        "assigned_weekly_hours": q2("0"),
    }
    st.stamp_new(tutor)
    st.tutors[tutor["id"]] = tutor
    return h.created(tutor)


@bp.post("/athletics/tutors/<tutor_id>/status")
def tutor_status(tutor_id):
    authenticate(["LearningSpecialist", "ComplianceOfficer"])
    tutor = h.tutor_or_404(tutor_id)
    body = json_body()
    term = h.body_fk(body, "term_id", h.term_or_404)
    action = want_action(body, ("COMPLETE_TRAINING", "SUSPEND", "REINSTATE",
                                "TERMINATE"))
    if action == "COMPLETE_TRAINING":
        term_id = want_string(body, "term_id")
        if term is None:
            term = h.term_or_404(term_id)
    else:
        forbid(body, "term_id", action)

    status = tutor["status"]
    if action == "COMPLETE_TRAINING":
        if status not in ("UNTRAINED", "EXPIRED"):
            raise h.invalid_transition()
        tutor["status"] = "TRAINED"
        tutor["training_completed_term_index"] = term["term_index"]
        tutor["training_valid_through_term_index"] = (
            term["term_index"] + calc.TRAINING_VALIDITY_TERMS - 1
        )
        st.touch(tutor)
        return h.ok(tutor)

    if action == "SUSPEND":
        if status not in ("TRAINED", "EXPIRED"):
            raise h.invalid_transition()
        derive.cascade_suspend_tutor(tutor)
        return h.ok(tutor)

    if action == "REINSTATE":
        if status != "SUSPENDED":
            raise h.invalid_transition()
        for incident in st.incidents.values():
            if (incident.get("tutor_id") == tutor["id"]
                    and incident["status"] == "SUBSTANTIATED"):
                raise h.invalid_transition()
        tutor["status"] = "TRAINED"
        st.touch(tutor)
        return h.ok(tutor)

    if status != "SUSPENDED":
        raise h.invalid_transition()
    tutor["status"] = "TERMINATED"
    st.touch(tutor)
    return h.ok(tutor)


# -------------------------------------------------------- tutor assignments
def _tutor_safety_checks(tutor):
    """Band 11 of the ladder, in the PRD's order."""
    if tutor["status"] == "UNTRAINED":
        raise ApiError("ERR_TUTOR_NOT_TRAINED")
    if tutor["status"] in ("EXPIRED", "SUSPENDED", "TERMINATED"):
        raise ApiError("ERR_TUTOR_TRAINING_EXPIRED")


def _capacity_checks(tutor, student, weekly_hours, exclude_assignment_id=None):
    """Band 15: the tutor ceiling first, then the student's tier ceiling."""
    if D(tutor["assigned_weekly_hours"]) + D(weekly_hours) > D(tutor["max_weekly_hours"]):
        raise ApiError("ERR_TUTOR_WEEKLY_HOURS_EXCEEDED")
    held = Decimal("0")
    for a in st.assignments.values():
        if a["status"] != "ACTIVE" or a["id"] == exclude_assignment_id:
            continue
        enrollment = st.enrollments.get(a["enrollment_id"])
        if enrollment and enrollment["student_athlete_id"] == student["id"]:
            held += D(a["weekly_hours"])
    if held + D(weekly_hours) > calc.TIER_HOURS_CAP[student["risk_tier"]]:
        raise ApiError("ERR_TIER_HOURS_CAP_EXCEEDED")


@bp.get("/athletics/tutor-assignments/<assignment_id>")
def get_assignment(assignment_id):
    authenticate(ASSIGNMENT_READ)
    return h.ok(h.assignment_or_404(assignment_id))


@bp.get("/athletics/tutor-assignments")
def list_assignments():
    authenticate(ASSIGNMENT_READ)
    return h.listing(st.by_created(list(st.assignments.values())),
                     ("tutor_id", "enrollment_id", "status"))


@bp.post("/athletics/tutor-assignments")
def create_assignment():
    authenticate(["LearningSpecialist"])
    body = json_body()
    tutor = h.body_fk(body, "tutor_id", h.tutor_or_404)
    enrollment = h.body_fk(body, "enrollment_id", h.enrollment_or_404)
    tutor_id = want_string(body, "tutor_id")
    enrollment_id = want_string(body, "enrollment_id")
    if tutor is None:
        tutor = h.tutor_or_404(tutor_id)
    if enrollment is None:
        enrollment = h.enrollment_or_404(enrollment_id)
    weekly_hours = want_decimal(body, "weekly_hours", maximum=10)
    if weekly_hours <= 0:
        raise bad_request("Field 'weekly_hours' must be greater than zero.")

    student = st.students[enrollment["student_athlete_id"]]
    course = st.courses.get(enrollment["course_id"])

    _tutor_safety_checks(tutor)
    if course is None or course["subject_code"] not in (tutor["subject_codes"] or []):
        raise ApiError("ERR_TUTOR_SUBJECT_MISMATCH")
    _capacity_checks(tutor, student, weekly_hours)

    assignment = {
        "tutor_id": tutor["id"],
        "enrollment_id": enrollment["id"],
        "weekly_hours": q2(weekly_hours),
        "status": "PROPOSED",
        "suspension_count": 0,
        "terminated_reason": None,
        "logged_hours": q2("0"),
    }
    st.stamp_new(assignment)
    st.assignments[assignment["id"]] = assignment
    return h.created(assignment)


@bp.post("/athletics/tutor-assignments/<assignment_id>/status")
def assignment_status(assignment_id):
    authenticate(["LearningSpecialist"])
    assignment = h.assignment_or_404(assignment_id)
    body = json_body()
    action = want_action(body, ("ACTIVATE", "SUSPEND", "REINSTATE", "COMPLETE",
                                "TERMINATE"))
    if action == "TERMINATE":
        reason = want_enum(body, "terminated_reason", TERMINATED_REASONS,
                           required=True)
    else:
        forbid(body, "terminated_reason", action)
        reason = None

    tutor = st.tutors[assignment["tutor_id"]]
    enrollment = st.enrollments[assignment["enrollment_id"]]
    student = st.students[enrollment["student_athlete_id"]]
    status = assignment["status"]

    if action == "ACTIVATE":
        if status != "PROPOSED":
            raise h.invalid_transition()
        if enrollment["status"] != "ENROLLED":
            raise h.invalid_transition()
        _tutor_safety_checks(tutor)
        if tutor["status"] != "TRAINED":
            raise h.invalid_transition()
        _capacity_checks(tutor, student, assignment["weekly_hours"])
        assignment["status"] = "ACTIVE"
        st.touch(assignment)
        derive.refresh_tutor_capacity(tutor)
        st.touch(tutor)
        derive.recompute_support_only(student)
        st.touch(student)
        return h.ok(assignment)

    if action == "SUSPEND":
        if status != "ACTIVE":
            raise h.invalid_transition()
        assignment["status"] = "SUSPENDED"
        assignment["suspension_count"] = assignment["suspension_count"] + 1
        st.touch(assignment)
        derive.refresh_tutor_capacity(tutor)
        st.touch(tutor)
        derive.recompute_support_only(student)
        st.touch(student)
        return h.ok(assignment)

    if action == "REINSTATE":
        if status != "SUSPENDED":
            raise h.invalid_transition()
        _tutor_safety_checks(tutor)
        if tutor["status"] != "TRAINED":
            raise h.invalid_transition()
        _capacity_checks(tutor, student, assignment["weekly_hours"])
        assignment["status"] = "ACTIVE"
        st.touch(assignment)
        derive.refresh_tutor_capacity(tutor)
        st.touch(tutor)
        derive.recompute_support_only(student)
        st.touch(student)
        return h.ok(assignment)

    if action == "COMPLETE":
        if status not in ("PROPOSED", "ACTIVE"):
            raise h.invalid_transition()
        assignment["status"] = "COMPLETED"
    else:
        if status not in ("PROPOSED", "ACTIVE", "SUSPENDED"):
            raise h.invalid_transition()
        assignment["status"] = "TERMINATED"
        assignment["terminated_reason"] = reason

    st.touch(assignment)
    derive.refresh_tutor_capacity(tutor)
    st.touch(tutor)
    derive.recompute_support_only(student)
    st.touch(student)
    return h.ok(assignment)


# ----------------------------------------------------------- support sessions
@bp.get("/athletics/support-sessions/<session_id>")
def get_session(session_id):
    authenticate(SESSION_READ_ONE)
    return h.ok(h.session_or_404(session_id))


@bp.get("/athletics/support-sessions")
def list_sessions():
    authenticate(SESSION_LIST)
    return h.listing(h.sorted_sessions(),
                     ("student_athlete_id", "tutor_assignment_id", "session_type"))


def _tutor_of(assignment):
    if assignment is None:
        return None
    return st.tutors.get(assignment["tutor_id"])


def _blocking_incident(tutor, student):
    """A SUBSTANTIATED top-severity incident naming this tutor and this student."""
    if tutor is None:
        return False
    for incident in st.incidents.values():
        if (incident.get("tutor_id") == tutor["id"]
                and incident["student_athlete_id"] == student["id"]
                and incident["status"] == "SUBSTANTIATED"
                and incident.get("severity") == "LEVEL_III"):
            return True
    return False


@bp.post("/athletics/support-sessions")
def create_session():
    user_id, role = authenticate(["LearningSpecialist", "Tutor"])
    body = json_body()

    # Band 4: body foreign keys resolve in the endpoint's declared field order.
    student = h.body_fk(body, "student_athlete_id", h.student_or_404)
    assignment = h.body_fk(body, "tutor_assignment_id", h.assignment_or_404,
                           required=False)

    # Band 3: a tutor may only log against its own assignment.
    if role == "Tutor" and assignment is not None:
        if assignment["tutor_id"] != user_id:
            raise ApiError("ERR_NOT_ASSIGNED_TUTOR")

    student_athlete_id = want_string(body, "student_athlete_id")
    if student is None:
        student = h.student_or_404(student_athlete_id)
    session_type = want_enum(body, "session_type", ("STUDY_HALL", "TUTOR_SESSION"))
    start_at = want_instant(body, "start_at")
    end_at = want_instant(body, "end_at")

    if session_type == "TUTOR_SESSION":
        assignment_id = want_string(body, "tutor_assignment_id")
        if assignment is None:
            assignment = h.assignment_or_404(assignment_id)
    else:
        if "tutor_assignment_id" in body and body["tutor_assignment_id"] is not None:
            raise bad_request(
                "Field 'tutor_assignment_id' must be omitted for a STUDY_HALL session.")
        assignment = None

    # Band 6: instant pairs are strictly ordered.
    if start_at >= end_at:
        raise ApiError("ERR_INVALID_TIME_WINDOW")

    tutor = _tutor_of(assignment)
    term = h.term_containing(start_at)

    # Band 11: only a TRAINED tutor whose training still covers the term of
    # record may have sessions logged against them; a tutoring session is also
    # blocked for a withheld student or a tutor implicated with that student.
    if tutor is not None:
        if tutor["status"] == "UNTRAINED":
            raise ApiError("ERR_TUTOR_NOT_TRAINED")
        if tutor["status"] in ("EXPIRED", "SUSPENDED", "TERMINATED"):
            raise ApiError("ERR_TUTOR_TRAINING_EXPIRED")
        valid_through = tutor["training_valid_through_term_index"]
        if (term is not None and valid_through is not None
                and term["term_index"] > valid_through):
            raise ApiError("ERR_TUTOR_TRAINING_EXPIRED")
    if session_type == "TUTOR_SESSION":
        if student["support_status"] == "SUPPORT_WITHHELD":
            raise ApiError("ERR_IMPERMISSIBLE_ASSISTANCE_BLOCK")
        if _blocking_incident(tutor, student):
            raise ApiError("ERR_IMPERMISSIBLE_ASSISTANCE_BLOCK")

    # Band 13: the session lies inside its term of record.
    if term is None:
        raise ApiError("ERR_SESSION_OUTSIDE_TERM")
    if start_at < term["_start_dt"] or end_at > term["_end_dt"]:
        raise ApiError("ERR_SESSION_OUTSIDE_TERM")

    # Band 14: no overlap for the same student, then the tutor's clear-time buffer.
    for other in st.sessions.values():
        if other["student_athlete_id"] != student["id"]:
            continue
        if start_at < other["_end_dt"] and other["_start_dt"] < end_at:
            raise ApiError("ERR_STUDENT_SESSION_OVERLAP")
    if tutor is not None:
        buffer_gap = calc.TUTOR_TRAVEL_BUFFER_MINUTES * 60
        for other in st.sessions.values():
            other_assignment = st.assignments.get(other.get("tutor_assignment_id"))
            if other_assignment is None or other_assignment["tutor_id"] != tutor["id"]:
                continue
            if start_at >= other["_end_dt"]:
                gap = (start_at - other["_end_dt"]).total_seconds()
            elif end_at <= other["_start_dt"]:
                gap = (other["_start_dt"] - end_at).total_seconds()
            else:
                gap = -1
            if gap < buffer_gap:
                raise ApiError("ERR_TUTOR_BUFFER_VIOLATION")

    minutes = D(str((end_at - start_at).total_seconds() / 60.0))
    hours_credited = q2(minutes / Decimal("60"))
    session = {
        "student_athlete_id": student["id"],
        "tutor_assignment_id": assignment["id"] if assignment else None,
        "session_type": session_type,
        "start_at": st.fmt_instant(start_at),
        "end_at": st.fmt_instant(end_at),
        "hours_credited": hours_credited,
        "term_index_of_record": term["term_index"],
        "logged_by_user_id": user_id,
        "_start_dt": start_at,
        "_end_dt": end_at,
    }
    st.stamp_session(session)
    st.sessions[session["id"]] = session

    if assignment is not None:
        assignment["logged_hours"] = q2(D(assignment["logged_hours"]) + hours_credited)
        st.touch(assignment)
    return h.created(session)
