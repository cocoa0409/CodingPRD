"""Path-identifier resolution (ladder rule 4).

PRD 2.10: "Identifiers embedded in a URL path are resolved strictly left to right,
and the first identifier that fails to resolve determines the error. Each resource
kind has its own not-found code."
"""

import store
from errors import fail


def _get(table, record_id, error_id):
    record = table.get(record_id)
    if record is None:
        fail(error_id)
    return record


def program(record_id):
    return _get(store.programs, record_id, "ERR_PROGRAM_NOT_FOUND")


def youth(record_id):
    return _get(store.youths, record_id, "ERR_YOUTH_NOT_FOUND")


def admission(record_id):
    return _get(store.admissions, record_id, "ERR_ADMISSION_NOT_FOUND")


def notification(record_id):
    return _get(store.guardian_notifications, record_id, "ERR_NOTIFICATION_NOT_FOUND")


def screening(record_id):
    return _get(store.safety_screenings, record_id, "ERR_SCREENING_NOT_FOUND")


def case(record_id):
    return _get(store.reunification_cases, record_id, "ERR_CASE_NOT_FOUND")


def session(record_id):
    return _get(store.mediation_sessions, record_id, "ERR_SESSION_NOT_FOUND")


def placement(record_id):
    return _get(store.tlp_placements, record_id, "ERR_PLACEMENT_NOT_FOUND")


def enrollment(record_id):
    return _get(store.education_enrollments, record_id, "ERR_ENROLLMENT_NOT_FOUND")


def proposal(record_id):
    return _get(store.governance_proposals, record_id, "ERR_PROPOSAL_NOT_FOUND")


def vote(record_id):
    return _get(store.governance_votes, record_id, "ERR_VOTE_NOT_FOUND")
