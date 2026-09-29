"""Small shared helpers for the route modules."""

from errors import ApiError
from store import sort_newest_first, store

NOT_FOUND = {
    "area": "ERR_AREA_NOT_FOUND",
    "recruiter": "ERR_RECRUITER_NOT_FOUND",
    "assignment": "ERR_ASSIGNMENT_NOT_FOUND",
    "student": "ERR_STUDENT_NOT_FOUND",
    "move": "ERR_MOVE_NOT_FOUND",
    "interview": "ERR_INTERVIEW_NOT_FOUND",
    "coe": "ERR_COE_NOT_FOUND",
    "review": "ERR_QC_REVIEW_NOT_FOUND",
    "term": "ERR_TERM_NOT_FOUND",
    "transfer": "ERR_TRANSFER_NOT_FOUND",
    "plan": "ERR_PLAN_NOT_FOUND",
    "delivery": "ERR_DELIVERY_NOT_FOUND",
}

TABLES = {
    "area": "areas",
    "recruiter": "recruiters",
    "assignment": "assignments",
    "student": "students",
    "move": "moves",
    "interview": "interviews",
    "coe": "coes",
    "review": "qc_reviews",
    "term": "terms",
    "transfer": "transfers",
    "plan": "plans",
    "delivery": "deliveries",
}

LABELS = {
    "area": "Agricultural area",
    "recruiter": "Recruiter",
    "assignment": "Recruiter assignment",
    "student": "Student",
    "move": "Qualifying move",
    "interview": "Interview record",
    "coe": "Certificate of eligibility",
    "review": "Quality control review",
    "term": "Eligibility term",
    "transfer": "Record transfer request",
    "plan": "Service plan",
    "delivery": "Service delivery",
}


def fetch(kind, row_id):
    table = getattr(store, TABLES[kind])
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(
            NOT_FOUND[kind],
            "%s '%s' was not found" % (LABELS[kind], row_id),
        )
    return row


def paginate(rows, limit, offset):
    ordered = sort_newest_first(rows)
    total = len(ordered)
    return ordered[offset:offset + limit], total


def matches(row, filters):
    for key, wanted in filters.items():
        if wanted is None:
            continue
        if row.get(key) != wanted:
            return False
    return True
