"""Competition travel and missed-class accounting (PRD 3.8)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import derive
import helpers as h
import store as st
from errors import ApiError
from store import D, q1, q2
from validation import (authenticate, json_body, forbid, want_action,
                        want_enum, want_instant, want_string)

bp = Blueprint("travel", __name__)

SPORT_CODES = ("MBB", "WBB", "FB", "BASE", "SOC", "TRACK")
EVENT_TYPES = ("REGULAR_SEASON", "CONFERENCE_CHAMPIONSHIP", "POSTSEASON",
               "EXHIBITION")
MULTIPLIERS = {
    "REGULAR_SEASON": Decimal("1.0"),
    "CONFERENCE_CHAMPIONSHIP": Decimal("0.5"),
    "POSTSEASON": Decimal("0.0"),
    "EXHIBITION": Decimal("1.0"),
}
EVENT_READ = ["AthleticsOperations", "AcademicAdvisor", "CertificationOfficer",
              "ComplianceOfficer", "Instructor"]
REQUEST_READ = ["AcademicAdvisor", "AthleticsOperations", "CertificationOfficer",
                "ComplianceOfficer", "Instructor"]
HOLDING = ("DRAFT", "PENDING_ACKNOWLEDGEMENT", "ACKNOWLEDGED", "DISPUTED")


# --------------------------------------------------------- competition events
@bp.get("/athletics/competition-events/<event_id>")
def get_event(event_id):
    authenticate(EVENT_READ)
    return h.ok(h.event_or_404(event_id))


@bp.get("/athletics/competition-events")
def list_events():
    authenticate(EVENT_READ)
    return h.listing(h.sorted_events(), ("term_id", "sport_code", "status"))


@bp.post("/athletics/competition-events")
def create_event():
    authenticate(["AthleticsOperations"])
    body = json_body()
    term = h.body_fk(body, "term_id", h.term_or_404)
    sport_code = want_enum(body, "sport_code", SPORT_CODES)
    term_id = want_string(body, "term_id")
    if term is None:
        term = h.term_or_404(term_id)
    event_type = want_enum(body, "event_type", EVENT_TYPES)
    departure_at = want_instant(body, "departure_at")
    return_at = want_instant(body, "return_at")
    if departure_at >= return_at:
        raise ApiError("ERR_INVALID_TIME_WINDOW")

    event = {
        "sport_code": sport_code,
        "term_id": term["id"],
        "event_type": event_type,
        "departure_at": st.fmt_instant(departure_at),
        "return_at": st.fmt_instant(return_at),
        "status": "SCHEDULED",
        "missed_class_unit_multiplier": q1(MULTIPLIERS[event_type]),
        "charged_units_total": q2("0"),
        "_departure_dt": departure_at,
        "_return_dt": return_at,
    }
    st.stamp_new(event)
    st.events[event["id"]] = event
    return h.created(event)


def _student_of(request):
    enrollment = st.enrollments[request["enrollment_id"]]
    return st.students[enrollment["student_athlete_id"]]


def _release_students(students):
    """The unit-release chain: ledger, risk, study hall, support, one version bump."""
    for student in students:
        derive.refresh_missed_class_ledger(student)
        derive.recompute_risk_and_support(student)
        st.touch(student)


def _release_request(request, new_status):
    """The single release chain shared by request CANCEL and event-driven VOID."""
    request["status"] = new_status
    st.touch(request)
    return _student_of(request)


@bp.post("/athletics/competition-events/<event_id>/status")
def event_status(event_id):
    authenticate(["AthleticsOperations"])
    event = h.event_or_404(event_id)
    body = json_body()
    action = want_action(body, ("APPROVE_TRAVEL", "DEPART", "COMPLETE", "CANCEL"))
    status = event["status"]
    now = st.clock_now()

    if action == "APPROVE_TRAVEL":
        if status != "SCHEDULED":
            raise h.invalid_transition()
        h.require_term_open(st.terms.get(event["term_id"]))
        event["status"] = "TRAVEL_APPROVED"
        st.touch(event)
        return h.ok(event)

    if action == "DEPART":
        if status != "TRAVEL_APPROVED":
            raise h.invalid_transition()
        if now < event["_departure_dt"]:
            raise h.invalid_transition()
        event["status"] = "IN_TRAVEL"
        st.touch(event)
        return h.ok(event)

    if action == "COMPLETE":
        if status != "IN_TRAVEL":
            raise h.invalid_transition()
        if now < event["_return_dt"]:
            raise h.invalid_transition()
        event["status"] = "COMPLETED"
        st.touch(event)
        return h.ok(event)

    if status not in ("SCHEDULED", "TRAVEL_APPROVED"):
        raise h.invalid_transition()
    event["status"] = "CANCELLED"
    st.touch(event)
    if status == "TRAVEL_APPROVED":
        rows = [r for r in st.by_created(list(st.requests.values()))
                if r["competition_event_id"] == event["id"] and r["status"] in HOLDING]
        affected_ids = []
        for request in rows:
            student = _release_request(request, "VOIDED")
            if student["id"] not in affected_ids:
                affected_ids.append(student["id"])
        derive.refresh_event_charged_total(event)
        _release_students([st.students[i] for i in affected_ids])
    return h.ok(event)


# ------------------------------------------------------ missed-class requests
@bp.get("/athletics/missed-class-requests/<request_id>")
def get_request(request_id):
    authenticate(REQUEST_READ)
    return h.ok(h.request_or_404(request_id))


@bp.get("/athletics/missed-class-requests")
def list_requests():
    authenticate(REQUEST_READ)
    return h.listing(st.by_created(list(st.requests.values())),
                     ("competition_event_id", "enrollment_id", "status"))


@bp.post("/athletics/missed-class-requests")
def create_request():
    authenticate(["AcademicAdvisor"])
    body = json_body()
    event = h.body_fk(body, "competition_event_id", h.event_or_404)
    enrollment = h.body_fk(body, "enrollment_id", h.enrollment_or_404)
    event_id = want_string(body, "competition_event_id")
    enrollment_id = want_string(body, "enrollment_id")
    if event is None:
        event = h.event_or_404(event_id)
    if enrollment is None:
        enrollment = h.enrollment_or_404(enrollment_id)

    term = st.terms[event["term_id"]]
    # Band 8: the freeze is scoped by the term the write is bound to.
    h.require_term_open(term)

    # Band 10: cross-entity state outranks every business rule below.
    if event["status"] != "TRAVEL_APPROVED":
        raise ApiError("ERR_EVENT_NOT_TRAVEL_APPROVED")

    # Band 12: one student per event roster, and a notifiable instructor.
    student = st.students[enrollment["student_athlete_id"]]
    for other in st.requests.values():
        if other["competition_event_id"] != event["id"]:
            continue
        other_enrollment = st.enrollments.get(other["enrollment_id"])
        if (other_enrollment is not None
                and other_enrollment["student_athlete_id"] != student["id"]):
            raise ApiError("ERR_ENROLLMENT_NOT_NOTIFIABLE")
    course = st.courses[enrollment["course_id"]]
    instructor_user_id = course.get("instructor_user_id")
    if instructor_user_id is None or str(instructor_user_id).strip() == "":
        raise ApiError("ERR_ENROLLMENT_NOT_NOTIFIABLE")

    count, gross, units = calc.missed_class_units(
        course, term["_start_dt"], term["_end_dt"],
        event["_departure_dt"], event["_return_dt"],
        event["missed_class_unit_multiplier"],
    )

    # Band 15: the budget check is the last check the request faces.
    if units > D(student["missed_class_units_remaining"]):
        raise ApiError("ERR_MISSED_CLASS_ALLOWANCE_EXCEEDED")

    request = {
        "competition_event_id": event["id"],
        "enrollment_id": enrollment["id"],
        "status": "DRAFT",
        "missed_meeting_count": count,
        "missed_units_gross": gross,
        "missed_units": units,
        "instructor_user_id": None,
        "notified_at": None,
        "acknowledgement_deadline_at": None,
        "instructor_response_note": None,
        "dispute_count": 0,
    }
    st.stamp_new(request)
    st.requests[request["id"]] = request

    derive.refresh_missed_class_ledger(student)
    derive.refresh_event_charged_total(event)
    st.touch(event)
    derive.recompute_risk_and_support(student)
    st.touch(student)
    return h.created(request)


@bp.post("/athletics/missed-class-requests/<request_id>/status")
def request_status(request_id):
    user_id, role = authenticate(["AcademicAdvisor", "Instructor"])
    request = h.request_or_404(request_id)
    body = json_body()
    action = want_action(body, ("NOTIFY_INSTRUCTOR", "ACKNOWLEDGE", "DISPUTE",
                                "CANCEL"))

    # Band 3: only the instructor named on the request may respond.
    if role == "Instructor" and action in ("ACKNOWLEDGE", "DISPUTE"):
        if request["instructor_user_id"] != user_id:
            raise ApiError("ERR_NOT_COURSE_INSTRUCTOR")

    if action in ("ACKNOWLEDGE", "DISPUTE"):
        note = want_string(body, "instructor_response_note", required=False)
    else:
        forbid(body, "instructor_response_note", action)
        note = None

    event = st.events[request["competition_event_id"]]
    status = request["status"]
    now = st.clock_now()

    if action == "NOTIFY_INSTRUCTOR":
        if status not in ("DRAFT", "DISPUTED"):
            raise h.invalid_transition()
        if event["status"] != "TRAVEL_APPROVED":
            raise ApiError("ERR_EVENT_NOT_TRAVEL_APPROVED")
        if status == "DRAFT":
            lead = event["_departure_dt"] - timedelta(days=calc.NOTIFICATION_LEAD_DAYS)
            if now > lead:
                raise ApiError("ERR_NOTIFICATION_LEAD_TIME_VIOLATION")
        else:
            if request["dispute_count"] >= calc.MAX_DISPUTE_ROUNDS:
                raise ApiError("ERR_APPEAL_ROUNDS_EXHAUSTED")
        enrollment = st.enrollments[request["enrollment_id"]]
        course = st.courses[enrollment["course_id"]]
        request["status"] = "PENDING_ACKNOWLEDGEMENT"
        request["notified_at"] = st.fmt_instant(now)
        request["acknowledgement_deadline_at"] = st.fmt_instant(
            now + timedelta(hours=calc.ACKNOWLEDGEMENT_WINDOW_HOURS))
        request["instructor_user_id"] = course.get("instructor_user_id")
        st.touch(request)
        return h.ok(request)

    if action in ("ACKNOWLEDGE", "DISPUTE"):
        if status != "PENDING_ACKNOWLEDGEMENT":
            raise h.invalid_transition()
        deadline = st.parse_instant(request["acknowledgement_deadline_at"])
        if deadline is not None and now > deadline:
            raise ApiError("ERR_ACKNOWLEDGEMENT_WINDOW_CLOSED")
        if action == "ACKNOWLEDGE":
            request["status"] = "ACKNOWLEDGED"
        else:
            request["status"] = "DISPUTED"
            request["dispute_count"] = request["dispute_count"] + 1
        request["instructor_response_note"] = note
        st.touch(request)
        return h.ok(request)

    if status not in HOLDING:
        raise h.invalid_transition()
    if event["status"] not in ("SCHEDULED", "TRAVEL_APPROVED"):
        raise h.invalid_transition()
    student = _release_request(request, "CANCELLED")
    derive.refresh_event_charged_total(event)
    st.touch(event)
    _release_students([student])
    return h.ok(request)
