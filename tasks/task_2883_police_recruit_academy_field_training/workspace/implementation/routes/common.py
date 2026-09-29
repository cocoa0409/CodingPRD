"""Helpers shared by every route module."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import g, request

import calc  # noqa: F401  (re-exported for convenience)
from core import (
    ApiError,
    fail,
    ordered,
    paginate,
    pagination,
    require_roles,
    respond,
    respond_list,
    store,
)

NOT_FOUND = {
    "standards": "ERR_CERTIFICATION_STANDARD_NOT_FOUND",
    "classes": "ERR_ACADEMY_CLASS_NOT_FOUND",
    "recruits": "ERR_RECRUIT_NOT_FOUND",
    "screenings": "ERR_SCREENING_RECORD_NOT_FOUND",
    "instructors": "ERR_INSTRUCTOR_NOT_FOUND",
    "plans": "ERR_LESSON_PLAN_NOT_FOUND",
    "sessions": "ERR_COURSE_SESSION_NOT_FOUND",
    "attendance": "ERR_ATTENDANCE_RECORD_NOT_FOUND",
    "exams": "ERR_EXAMINATION_NOT_FOUND",
    "rotations": "ERR_ROTATION_NOT_FOUND",
    "reports": "ERR_OBSERVATION_REPORT_NOT_FOUND",
    "entries": "ERR_TRAINING_RECORD_ENTRY_NOT_FOUND",
}

TERMINAL_STAGES = ("CERTIFIED", "DISMISSED", "WITHDRAWN")


def path_row(collection, ident):
    """Rung 10: resolve a path identifier, or answer that entity's typed 404."""
    row = getattr(store, collection).get(ident)
    if row is None:
        fail(NOT_FOUND[collection])
    return row


def body_fk(body, key, collection):
    """Rung 12: resolve a body foreign key when it is syntactically usable."""
    value = body.get(key)
    if not isinstance(value, str) or value == "":
        return None
    row = getattr(store, collection).get(value)
    if row is None:
        fail(NOT_FOUND[collection])
    return row


def unique_or_conflict(collection, field, value):
    """Rung 24."""
    for row in getattr(store, collection).values():
        if row.get(field) == value:
            fail("ERR_DUPLICATE_IDENTIFIER", "%s is already in use" % field)


def check_recruit_not_terminal(recruit):
    """Rung 39."""
    if recruit["pipeline_stage"] in TERMINAL_STAGES:
        fail("ERR_RECRUIT_TERMINAL", "recruit has left the pipeline")


def check_recruit_in_academy(recruit):
    """Rung 42."""
    if recruit["academy_status"] not in ("IN_PROGRESS", "REMEDIATION"):
        fail("ERR_RECRUIT_NOT_IN_ACADEMY", "recruit is not in academy standing")


def listing(collection, serializer, predicate=None):
    rows = ordered([r for r in getattr(store, collection).values()
                    if predicate is None or predicate(r)])
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return respond_list([serializer(row) for row in page], limit, offset, total)


def created(payload):
    return respond(payload, 201)


def ok(payload):
    return respond(payload, 200)
