"""Row lookups (PRD 2.6) and list-filter helpers.

Rank 8 of PRD 2.9 resolves the path identifier; rank 9 resolves body foreign
keys in the endpoint's declared input order. Both raise the referenced
resource's own not-found error.
"""

from flask import request

from db import S, ordered
from errors import ApiError


def _find(collection, row_id, error_id, label):
    if not isinstance(row_id, str) or row_id not in collection:
        raise ApiError(error_id, "No %s matches the supplied identifier." % label)
    return collection[row_id]


def department_or_404(row_id):
    return _find(S.departments, row_id, "ERR_DEPARTMENT_NOT_FOUND", "department")


def faculty_or_404(row_id):
    return _find(S.faculty_members, row_id, "ERR_FACULTY_MEMBER_NOT_FOUND", "faculty member")


def student_or_404(row_id):
    return _find(S.students, row_id, "ERR_STUDENT_NOT_FOUND", "student")


def offering_or_404(row_id):
    return _find(S.offerings, row_id, "ERR_OFFERING_NOT_FOUND", "course offering")


def report_or_404(row_id):
    return _find(S.reports, row_id, "ERR_REPORT_NOT_FOUND", "integrity report")


def evidence_or_404(row_id):
    return _find(S.evidence_items, row_id, "ERR_EVIDENCE_ITEM_NOT_FOUND", "evidence item")


def case_or_404(row_id):
    return _find(S.cases, row_id, "ERR_CASE_NOT_FOUND", "case")


def notification_or_404(row_id):
    return _find(S.notifications, row_id, "ERR_NOTIFICATION_NOT_FOUND", "notification")


def engagement_or_404(row_id):
    return _find(S.engagements, row_id, "ERR_ADVISOR_ENGAGEMENT_NOT_FOUND",
                 "advisor engagement")


def meeting_or_404(row_id):
    return _find(S.meetings, row_id, "ERR_MEETING_NOT_FOUND", "case meeting")


def room_or_404(row_id):
    return _find(S.rooms, row_id, "ERR_ROOM_NOT_FOUND", "hearing room")


def session_or_404(row_id):
    return _find(S.sessions, row_id, "ERR_SESSION_NOT_FOUND", "hearing session")


def vote_or_404(row_id):
    return _find(S.votes, row_id, "ERR_PANEL_VOTE_NOT_FOUND", "panel vote")


def sanction_or_404(row_id):
    return _find(S.sanctions, row_id, "ERR_SANCTION_NOT_FOUND", "sanction")


def appeal_or_404(row_id):
    return _find(S.appeals, row_id, "ERR_APPEAL_NOT_FOUND", "appeal")


def filter_rows(collection, keys):
    """List rows in created_at ascending order, applying equality filters.

    `keys` maps a query-parameter name to the row key it filters on. A filter
    whose value matches nothing simply yields an empty page.
    """
    rows = ordered(collection)
    for param, field in keys.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        rows = [row for row in rows if row.get(field) == raw]
    return rows


def bool_filter(rows, param, predicate):
    raw = request.args.get(param)
    if raw is None:
        return rows
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        wanted = True
    elif lowered in ("false", "0"):
        wanted = False
    else:
        return []
    return [row for row in rows if predicate(row) == wanted]
