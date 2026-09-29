"""Impermissible assistance, tutor discipline, the APR close and the clock (PRD 3.9)."""

from flask import Blueprint

import calc
import derive
import helpers as h
import store as st
from envelope import object_response
from errors import ApiError
from store import D, q0
from validation import (authenticate, forbid, json_body, want_action,
                        want_enum, want_instant, want_string)

bp = Blueprint("compliance", __name__)

INCIDENT_READ = ["ComplianceOfficer", "CertificationOfficer", "LearningSpecialist",
                 "AppealsCommittee"]
INCIDENT_TYPES = ("IMPERMISSIBLE_WORK_COMPLETION", "UNAUTHORIZED_EXAM_ASSISTANCE",
                  "UNTRAINED_TUTOR_SESSION", "EXCESSIVE_TUTOR_HOURS")
SEVERITIES = ("LEVEL_I", "LEVEL_II", "LEVEL_III")
CLOCK_ROLES = ["Registrar", "AcademicAdvisor", "CertificationOfficer",
               "LearningSpecialist", "ComplianceOfficer", "AppealsCommittee",
               "AthleticsOperations", "Instructor", "Tutor", "StudentAthlete"]
COHORT_ENROLLMENT_STATUSES = ("ENROLLED", "COMPLETED", "INCOMPLETE")


# ---------------------------------------------------------------- incidents
@bp.get("/athletics/compliance-incidents/<incident_id>")
def get_incident(incident_id):
    authenticate(INCIDENT_READ)
    return h.ok(h.incident_or_404(incident_id))


@bp.get("/athletics/compliance-incidents")
def list_incidents():
    authenticate(INCIDENT_READ)
    return h.listing(st.by_created(list(st.incidents.values())),
                     ("student_athlete_id", "tutor_id", "discovered_session_id",
                      "status", "severity"))


@bp.post("/athletics/compliance-incidents")
def create_incident():
    user_id, _role = authenticate(
        ["ComplianceOfficer", "LearningSpecialist", "AcademicAdvisor"])
    body = json_body()
    student = h.body_fk(body, "student_athlete_id", h.student_or_404)
    tutor = h.body_fk(body, "tutor_id", h.tutor_or_404, required=False)
    session = h.body_fk(body, "discovered_session_id", h.session_or_404,
                        required=False)
    student_athlete_id = want_string(body, "student_athlete_id")
    if student is None:
        student = h.student_or_404(student_athlete_id)
    incident_type = want_enum(body, "incident_type", INCIDENT_TYPES)
    narrative = want_string(body, "narrative")

    incident = {
        "student_athlete_id": student["id"],
        "tutor_id": tutor["id"] if tutor else None,
        "discovered_session_id": session["id"] if session else None,
        "incident_type": incident_type,
        "severity": None,
        "status": "REPORTED",
        "penalty_points_assessed": 0,
        "narrative": narrative,
        "reported_by_user_id": user_id,
    }
    st.stamp_new(incident)
    st.incidents[incident["id"]] = incident
    return h.created(incident)


def _substantiate(incident, severity):
    """PRD 3.9: the widest cascade in the specification, and it fires in order."""
    points = calc.INCIDENT_POINTS[severity]
    incident["status"] = "SUBSTANTIATED"
    incident["severity"] = severity
    incident["penalty_points_assessed"] = points
    st.touch(incident)

    student = st.students[incident["student_athlete_id"]]
    student["substantiated_penalty_points"] = (
        int(student["substantiated_penalty_points"]) + points
    )

    tutor = st.tutors.get(incident.get("tutor_id"))
    if tutor is not None:
        tutor["penalty_points"] = int(tutor["penalty_points"]) + points
        if (tutor["penalty_points"] >= calc.TUTOR_SUSPENSION_POINT_THRESHOLD
                and tutor["status"] in ("TRAINED", "EXPIRED")):
            derive.cascade_suspend_tutor(tutor)
        else:
            st.touch(tutor)

    if severity == "LEVEL_III":
        student["support_status"] = "SUPPORT_WITHHELD"
        cert = derive.governing_certification(student["id"])
        if cert is not None and cert["status"] in ("CERTIFIED", "RESTORED"):
            cert["status"] = "REVOKED"
            st.touch(cert)
        derive.derive_eligibility_state(student)

    derive.recompute_risk_and_support(student)
    st.touch(student)


@bp.post("/athletics/compliance-incidents/<incident_id>/status")
def incident_status(incident_id):
    authenticate(["ComplianceOfficer"])
    incident = h.incident_or_404(incident_id)
    body = json_body()
    action = want_action(body, ("OPEN_INVESTIGATION", "SUBSTANTIATE",
                                "UNSUBSTANTIATE", "REMEDIATE"))
    if action == "SUBSTANTIATE":
        severity = want_enum(body, "severity", SEVERITIES, required=True)
    else:
        forbid(body, "severity", action)
        severity = None

    status = incident["status"]
    if action == "OPEN_INVESTIGATION":
        if status != "REPORTED":
            raise h.invalid_transition()
        incident["status"] = "UNDER_INVESTIGATION"
        st.touch(incident)
        return h.ok(incident)

    if action == "UNSUBSTANTIATE":
        if status != "UNDER_INVESTIGATION":
            raise h.invalid_transition()
        incident["status"] = "UNSUBSTANTIATED"
        st.touch(incident)
        return h.ok(incident)

    if action == "SUBSTANTIATE":
        if status != "UNDER_INVESTIGATION":
            raise h.invalid_transition()
        _substantiate(incident, severity)
        return h.ok(incident)

    if status != "SUBSTANTIATED":
        raise h.invalid_transition()
    incident["status"] = "REMEDIATED"
    st.touch(incident)
    student = st.students[incident["student_athlete_id"]]
    derive.recompute_support_only(student)
    st.touch(student)
    return h.ok(incident)


# ------------------------------------------------- the academic-progress close
def _has_enrollment(student_id, term_id, statuses):
    for enrollment in st.enrollments.values():
        if (enrollment["student_athlete_id"] == student_id
                and enrollment["term_id"] == term_id
                and enrollment["status"] in statuses):
            return True
    return False


def _next_term(term):
    best = None
    for other in st.terms.values():
        if other["term_index"] <= term["term_index"]:
            continue
        if best is None or other["term_index"] < best["term_index"]:
            best = other
    return best


def _eligibility_point(student, term):
    for cert in st.certifications.values():
        if (cert["student_athlete_id"] == student["id"]
                and cert["term_id"] == term["id"]
                and cert["status"] in ("CERTIFIED", "RESTORED")):
            return 1
    return 0


def _retention_point(student, term):
    """PROJECTED while the next term is open, OBSERVED once it has closed."""
    following = _next_term(term)
    if following is None:
        return 1
    if following["apr_status"] == "OPEN":
        return 1 if _has_enrollment(student["id"], following["id"], ("ENROLLED",)) else 0
    return 1 if _has_enrollment(student["id"], following["id"], ("COMPLETED",)) else 0


def _expire_lapsed_training(term):
    """PRD 3.7: lapsing is not an action anybody takes; it is a close cascade."""
    for tutor in st.by_created(list(st.tutors.values())):
        valid_through = tutor["training_valid_through_term_index"]
        if (tutor["status"] == "TRAINED" and valid_through is not None
                and valid_through <= term["term_index"]):
            tutor["status"] = "EXPIRED"
            derive.cascade_terminate_tutor_assignments(
                tutor, "TERM_CLOSED", new_status="COMPLETED", only_term_id=term["id"])


@bp.post("/athletics/terms/<term_id>/apr-close")
def apr_close(term_id):
    authenticate(["ComplianceOfficer"])
    term = h.term_or_404(term_id)

    # Band 9: four conditions guard the checkpoint, in the PRD's order.
    if term["apr_status"] != "OPEN" or not term["is_apr_reporting_term"]:
        raise h.invalid_transition()
    if st.clock_now() < term["_end_dt"]:
        raise ApiError("ERR_APR_TERM_NOT_ENDED")
    for other in st.terms.values():
        if (other["is_apr_reporting_term"]
                and other["term_index"] < term["term_index"]
                and other["apr_status"] != "CLOSED"):
            raise ApiError("ERR_APR_PRIOR_TERM_OPEN")

    cohort = [
        s for s in st.students.values()
        if s["entry_term_index"] <= term["term_index"]
        and _has_enrollment(s["id"], term["id"], COHORT_ENROLLMENT_STATUSES)
    ]
    cohort.sort(key=lambda s: (s["entry_term_index"], s["created_at"], s["_seq"]))

    term_earned = 0
    term_possible = 0
    for student in cohort:
        earned = _eligibility_point(student, term) + _retention_point(student, term)
        student["apr_points_earned"] = int(student["apr_points_earned"]) + earned
        student["apr_points_possible"] = (
            int(student["apr_points_possible"]) + calc.APR_POINTS_PER_STUDENT
        )
        student["apr_points_forfeited"] = (
            int(student["apr_points_possible"]) - int(student["apr_points_earned"])
        )
        term_earned += earned
        term_possible += calc.APR_POINTS_PER_STUDENT

    term["apr_points_possible"] = term_possible
    term["apr_points_earned"] = term_earned
    if term_possible == 0:
        term["squad_apr"] = None
    else:
        term["squad_apr"] = q0(D(term_earned) / D(term_possible) * calc.APR_SCALE)

    for student in cohort:
        derive.derive_support_status(student)
        st.touch(student)

    _expire_lapsed_training(term)
    term["apr_status"] = "CLOSED"
    for tutor in st.by_created(list(st.tutors.values())):
        points = calc.tutor_penalty_points(tutor["id"])
        if points != int(tutor["penalty_points"]):
            tutor["penalty_points"] = points
            st.touch(tutor)
    st.touch(term)
    return h.ok(term)


# ------------------------------------------------------------- logical clock
@bp.post("/athletics/_clock/set_current_utc")
def set_current_utc():
    authenticate(CLOCK_ROLES)
    body = json_body()
    current_utc = want_instant(body, "current_utc")
    st.set_clock(current_utc)
    return object_response({"current_utc": st.fmt_instant(current_utc)}, 200)
