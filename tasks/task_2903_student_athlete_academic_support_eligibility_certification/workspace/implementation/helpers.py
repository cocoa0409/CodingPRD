"""Route plumbing: existence lookups, list assembly, response shortcuts."""

import envelope
import store as st
from errors import ApiError
from validation import apply_filters, paginate


def public(row):
    """Serialize a stored row: every non-internal key, internals are '_'-prefixed."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ok(row, status=200):
    return envelope.object_response(public(row) if row is not None else {}, status)


def created(row):
    return envelope.object_response(public(row), 201)


def listing(rows, filter_fields=(), aliases=None):
    rows = apply_filters(rows, filter_fields, aliases)
    page, limit, offset, total = paginate(rows)
    return envelope.list_response([public(r) for r in page], limit, offset, total)


def _fetch(collection, identifier, error_id):
    if not isinstance(identifier, str) or identifier not in collection:
        raise ApiError(error_id)
    return collection[identifier]


def term_or_404(identifier):
    return _fetch(st.terms, identifier, "ERR_TERM_NOT_FOUND")


def program_or_404(identifier):
    return _fetch(st.degree_programs, identifier, "ERR_DEGREE_PROGRAM_NOT_FOUND")


def course_or_404(identifier):
    return _fetch(st.courses, identifier, "ERR_COURSE_NOT_FOUND")


def rule_or_404(identifier):
    return _fetch(st.rules, identifier, "ERR_APPLICABILITY_RULE_NOT_FOUND")


def student_or_404(identifier):
    return _fetch(st.students, identifier, "ERR_STUDENT_ATHLETE_NOT_FOUND")


def enrollment_or_404(identifier):
    return _fetch(st.enrollments, identifier, "ERR_ENROLLMENT_NOT_FOUND")


def certification_or_404(identifier):
    return _fetch(st.certifications, identifier, "ERR_CERTIFICATION_NOT_FOUND")


def tutor_or_404(identifier):
    return _fetch(st.tutors, identifier, "ERR_TUTOR_NOT_FOUND")


def assignment_or_404(identifier):
    return _fetch(st.assignments, identifier, "ERR_TUTOR_ASSIGNMENT_NOT_FOUND")


def session_or_404(identifier):
    return _fetch(st.sessions, identifier, "ERR_SUPPORT_SESSION_NOT_FOUND")


def event_or_404(identifier):
    return _fetch(st.events, identifier, "ERR_COMPETITION_EVENT_NOT_FOUND")


def request_or_404(identifier):
    return _fetch(st.requests, identifier, "ERR_MISSED_CLASS_REQUEST_NOT_FOUND")


def appeal_or_404(identifier):
    return _fetch(st.appeals, identifier, "ERR_APPEAL_NOT_FOUND")


def incident_or_404(identifier):
    return _fetch(st.incidents, identifier, "ERR_COMPLIANCE_INCIDENT_NOT_FOUND")


def body_fk(body, field, lookup, required=True):
    """Band-4 resolution of a body-borne foreign key in declared field order.

    A missing or non-string value is left to the band-5 shape check.
    """
    if field not in body or body[field] is None:
        return None
    value = body[field]
    if not isinstance(value, str):
        return None
    return lookup(value)


def sorted_terms():
    return sorted(st.terms.values(),
                  key=lambda r: (r["term_index"], r["created_at"], r["_seq"]))


def sorted_programs():
    return sorted(st.degree_programs.values(),
                  key=lambda r: (r["code"], r["created_at"], r["_seq"]))


def sorted_courses():
    return sorted(st.courses.values(),
                  key=lambda r: (r["subject_code"], r["course_number"],
                                 r["created_at"], r["_seq"]))


def sorted_rules():
    return sorted(st.rules.values(),
                  key=lambda r: (r["effective_catalog_year"], r["created_at"],
                                 r["_seq"]))


def sorted_students():
    return sorted(st.students.values(),
                  key=lambda r: (r["entry_term_index"], r["created_at"], r["_seq"]))


def sorted_sessions():
    return sorted(st.sessions.values(),
                  key=lambda r: (r["start_at"], r["created_at"], r["_seq"]))


def sorted_events():
    return sorted(st.events.values(),
                  key=lambda r: (r["departure_at"], r["created_at"], r["_seq"]))


def sorted_appeals():
    return sorted(st.appeals.values(),
                  key=lambda r: (r["round_number"], r["created_at"], r["_seq"]))


def term_is_open(term):
    return term["apr_status"] == "OPEN"


def require_term_open(term):
    """Band 8: the governing term is still open for APR reporting."""
    if term is None:
        return
    if term["apr_status"] != "OPEN":
        raise ApiError("ERR_APR_TERM_CLOSED")


def invalid_transition():
    return ApiError("ERR_INVALID_STATE_TRANSITION")


def term_containing(instant):
    """The unique term whose `[start_date, end_date)` window contains `instant`."""
    if instant is None:
        return None
    for term in sorted(st.terms.values(), key=lambda r: r["term_index"]):
        if term["_start_dt"] <= instant < term["_end_dt"]:
            return term
    return None
