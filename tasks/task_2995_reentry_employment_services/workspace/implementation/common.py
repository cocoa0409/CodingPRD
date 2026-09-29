"""Shared route helpers: path resolution, filtering and list responses."""

from envelope import listing
from errors import fail
from store import public
from validation import ALL_ROLES, pagination, query_bool, query_int, query_value

READ_ROLES = list(ALL_ROLES)

NOT_FOUND = {
    "participants": "ERR_PARTICIPANT_NOT_FOUND",
    "supervision_cases": "ERR_SUPERVISION_CASE_NOT_FOUND",
    "partnerships": "ERR_PARTNERSHIP_NOT_FOUND",
    "job_openings": "ERR_JOB_OPENING_NOT_FOUND",
    "placements": "ERR_PLACEMENT_NOT_FOUND",
    "work_shifts": "ERR_WORK_SHIFT_NOT_FOUND",
    "grants": "ERR_GRANT_NOT_FOUND",
    "support_requests": "ERR_SUPPORT_REQUEST_NOT_FOUND",
    "sessions": "ERR_SESSION_NOT_FOUND",
    "enrollments": "ERR_ENROLLMENT_NOT_FOUND",
}


def resolve(collection_name, collection, row_id):
    row = collection.get(row_id)
    if row is None:
        fail(NOT_FOUND[collection_name], "Addressed resource does not exist")
    return row


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit] if limit else []
    return page, total


def list_result(rows, limit=None, offset=None):
    """Emit a paginated list envelope for already-ordered rows."""
    if limit is None or offset is None:
        limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return listing([public(row) for row in page], total, limit, offset)


def match_filters(rows, string_filters=None, bool_filters=None,
                  int_filters=None):
    """Narrow rows by exact-match query parameters; unparsable values ignored."""
    result = rows
    for field in string_filters or []:
        wanted = query_value(field)
        if wanted is not None:
            result = [row for row in result if row.get(field) == wanted]
    for field in bool_filters or []:
        wanted = query_bool(field)
        if wanted is not None:
            result = [row for row in result if bool(row.get(field)) is wanted]
    for field in int_filters or []:
        wanted = query_int(field)
        if wanted is not None:
            result = [row for row in result if row.get(field) == wanted]
    return result
