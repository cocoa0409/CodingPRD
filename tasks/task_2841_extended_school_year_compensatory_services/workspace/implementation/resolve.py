"""Path and body identifier resolution (PRD sections 2.6 / 2.7 checks 5 and 6)."""
from errors import ApiError
from store import db

NOT_FOUND = {
    "student": "ERR_STUDENT_NOT_FOUND",
    "determination": "ERR_DETERMINATION_NOT_FOUND",
    "program": "ERR_PROGRAM_NOT_FOUND",
    "provider": "ERR_PROVIDER_NOT_FOUND",
    "commitment": "ERR_COMMITMENT_NOT_FOUND",
    "assignment": "ERR_ASSIGNMENT_NOT_FOUND",
    "run": "ERR_RUN_NOT_FOUND",
    "log": "ERR_SERVICE_LOG_NOT_FOUND",
    "award": "ERR_AWARD_NOT_FOUND",
    "session": "ERR_MAKEUP_SESSION_NOT_FOUND",
    "allocation": "ERR_FUND_ALLOCATION_NOT_FOUND",
    "record": "ERR_DUE_PROCESS_RECORD_NOT_FOUND",
}

COLLECTIONS = {
    "student": "students",
    "determination": "determinations",
    "program": "programs",
    "provider": "providers",
    "commitment": "commitments",
    "assignment": "assignments",
    "run": "runs",
    "log": "logs",
    "award": "awards",
    "session": "sessions",
    "allocation": "allocations",
    "record": "records",
}


def path_ref(kind, identifier):
    """Resolve one path segment; the first unresolvable segment decides."""
    store = getattr(db, COLLECTIONS[kind])
    record = store.get(identifier)
    if record is None:
        raise ApiError(NOT_FOUND[kind])
    return record


def body_ref(data, key, kind, error_id=None):
    """Resolve a body identifier. Absent or non-string is left to the shape check."""
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if not isinstance(value, str):
        return None
    store = getattr(db, COLLECTIONS[kind])
    record = store.get(value)
    if record is None:
        raise ApiError(error_id or NOT_FOUND[kind])
    return record
