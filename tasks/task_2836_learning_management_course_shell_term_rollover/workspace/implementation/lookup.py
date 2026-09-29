"""Record resolution.  PRD 2.4: a path identifier or a body foreign key that
does not resolve returns the 404 code specific to that record type."""

from db import db
from errors import ApiError

NOT_FOUND = {
    "terms": "ERR_TERM_NOT_FOUND",
    "people": "ERR_PERSON_NOT_FOUND",
    "shells": "ERR_SHELL_NOT_FOUND",
    "enrollments": "ERR_ENROLLMENT_NOT_FOUND",
    "batches": "ERR_BATCH_NOT_FOUND",
    "merges": "ERR_MERGE_REQUEST_NOT_FOUND",
    "items": "ERR_CONTENT_ITEM_NOT_FOUND",
    "jobs": "ERR_ROLLOVER_JOB_NOT_FOUND",
    "tools": "ERR_TOOL_NOT_FOUND",
    "reviews": "ERR_REVIEW_NOT_FOUND",
    "placements": "ERR_PLACEMENT_NOT_FOUND",
    "passbacks": "ERR_PASSBACK_NOT_FOUND",
    "disputes": "ERR_DISPUTE_NOT_FOUND",
    "windows": "ERR_WINDOW_NOT_FOUND",
}


def peek(collection, record_id):
    if record_id is None or not isinstance(record_id, str):
        return None
    return getattr(db, collection).get(record_id)


def fetch(collection, record_id):
    record = peek(collection, record_id)
    if record is None:
        raise ApiError(NOT_FOUND[collection],
                       "No such record for id '%s'." % record_id)
    return record


def term(record_id):
    return fetch("terms", record_id)


def person(record_id):
    return fetch("people", record_id)


def shell(record_id):
    return fetch("shells", record_id)


def enrollment(record_id):
    return fetch("enrollments", record_id)


def batch(record_id):
    return fetch("batches", record_id)


def merge(record_id):
    return fetch("merges", record_id)


def item(record_id):
    return fetch("items", record_id)


def job(record_id):
    return fetch("jobs", record_id)


def tool(record_id):
    return fetch("tools", record_id)


def review(record_id):
    return fetch("reviews", record_id)


def placement(record_id):
    return fetch("placements", record_id)


def passback(record_id):
    return fetch("passbacks", record_id)


def dispute(record_id):
    return fetch("disputes", record_id)


def window(record_id):
    return fetch("windows", record_id)


def shells_of_term(term_id):
    return [s for s in db.shells.values() if s["term_id"] == term_id]


def enrollments_of_shell(shell_id):
    return [e for e in db.enrollments.values() if e["shell_id"] == shell_id]


def items_of_shell(shell_id):
    return [i for i in db.items.values() if i["shell_id"] == shell_id]


def placements_of_shell(shell_id):
    return [p for p in db.placements.values() if p["shell_id"] == shell_id]


def placements_of_tool(tool_id):
    return [p for p in db.placements.values() if p["tool_id"] == tool_id]


def reviews_of_tool(tool_id):
    return [r for r in db.reviews.values() if r["tool_id"] == tool_id]


def passbacks_of_term(term_id):
    return [p for p in db.passbacks.values() if p["term_id"] == term_id]


def passback_of_shell(shell_id):
    for p in db.passbacks.values():
        if p["shell_id"] == shell_id:
            return p
    return None


def disputes_of_passback(passback_id):
    return [d for d in db.disputes.values() if d["passback_id"] == passback_id]


def disputes_of_enrollment(enrollment_id):
    return [d for d in db.disputes.values() if d["enrollment_id"] == enrollment_id]


def windows_of_term(term_id):
    return [w for w in db.windows.values() if w["term_id"] == term_id]


def jobs_for_target(shell_id):
    return [j for j in db.jobs.values() if j["target_shell_id"] == shell_id]


def fk(payload, name, collection):
    """Resolve a body foreign key.  An absent or empty value is left to the
    request-shape band; any other value that does not resolve returns the
    record-specific 404 of PRD 2.4."""
    if not isinstance(payload, dict) or name not in payload:
        return None
    value = payload[name]
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    record = getattr(db, collection).get(value) if isinstance(value, str) else None
    if record is None:
        raise ApiError(NOT_FOUND[collection],
                       "No such record for id '%s'." % (value,))
    return record
