"""Path-parameter and body foreign-key resolution (PRD sec 2.6)."""
from errors import ApiError
from store import db

_TABLES = {
    "program": ("programs", "ERR_PROGRAM_NOT_FOUND"),
    "course": ("courses", "ERR_COURSE_NOT_FOUND"),
    "credential": ("credentials", "ERR_CREDENTIAL_NOT_FOUND"),
    "student": ("students", "ERR_STUDENT_NOT_FOUND"),
    "attainment": ("attainments", "ERR_ATTAINMENT_NOT_FOUND"),
    "committee": ("committees", "ERR_COMMITTEE_NOT_FOUND"),
    "member": ("members", "ERR_MEMBER_NOT_FOUND"),
    "meeting": ("meetings", "ERR_MEETING_NOT_FOUND"),
    "award": ("awards", "ERR_GRANT_NOT_FOUND"),
    "expenditure": ("expenditures", "ERR_EXPENDITURE_NOT_FOUND"),
    "indicator": ("indicators", "ERR_INDICATOR_NOT_FOUND"),
    "plan": ("plans", "ERR_PLAN_NOT_FOUND"),
    "educator": ("educators", "ERR_EDUCATOR_NOT_FOUND"),
}


def _fetch(kind, record_id):
    table, error_id = _TABLES[kind]
    record = getattr(db, table).get(record_id)
    if record is None:
        raise ApiError(error_id, "No %s exists with id '%s'." % (kind, record_id))
    return record


def program(record_id):
    return _fetch("program", record_id)


def course(record_id):
    return _fetch("course", record_id)


def credential(record_id):
    return _fetch("credential", record_id)


def student(record_id):
    return _fetch("student", record_id)


def attainment(record_id):
    return _fetch("attainment", record_id)


def committee(record_id):
    return _fetch("committee", record_id)


def member(record_id):
    return _fetch("member", record_id)


def meeting(record_id):
    return _fetch("meeting", record_id)


def award(record_id):
    return _fetch("award", record_id)


def expenditure(record_id):
    return _fetch("expenditure", record_id)


def indicator(record_id):
    return _fetch("indicator", record_id)


def plan(record_id):
    return _fetch("plan", record_id)


def educator(record_id):
    return _fetch("educator", record_id)


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])
