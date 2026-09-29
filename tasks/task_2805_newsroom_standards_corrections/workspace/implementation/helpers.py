"""Path-identifier resolution (PRD 2.12 step 6) and small shared route helpers."""

from errors import ApiError
from store import db, ordered


def _resolve(collection, key, error_id, label):
    record = getattr(db, collection).get(key)
    if record is None:
        raise ApiError(error_id, "%s '%s' does not resolve." % (label, key))
    return record


def newsroom_or_404(key):
    return _resolve("newsrooms", key, "ERR_NEWSROOM_NOT_FOUND", "newsroom_id")


def journalist_or_404(key):
    return _resolve("journalists", key, "ERR_JOURNALIST_NOT_FOUND", "journalist_id")


def reviewer_or_404(key):
    return _resolve("reviewers", key, "ERR_REVIEWER_NOT_FOUND", "reviewer_id")


def story_or_404(key):
    return _resolve("stories", key, "ERR_STORY_NOT_FOUND", "story_id")


def approval_or_404(key):
    return _resolve("source_approvals", key, "ERR_SOURCE_APPROVAL_NOT_FOUND", "approval_id")


def review_or_404(key):
    return _resolve("reviews", key, "ERR_REVIEW_NOT_FOUND", "review_id")


def assignment_or_404(key):
    return _resolve("assignments", key, "ERR_ASSIGNMENT_NOT_FOUND", "assignment_id")


def correction_or_404(key):
    return _resolve("corrections", key, "ERR_CORRECTION_REQUEST_NOT_FOUND", "request_id")


def investigation_or_404(key):
    return _resolve("investigations", key, "ERR_INVESTIGATION_NOT_FOUND", "investigation_id")


def disclosure_or_404(key):
    return _resolve("disclosures", key, "ERR_DISCLOSURE_NOT_FOUND", "disclosure_id")


def activity_or_404(key):
    return _resolve("activities", key, "ERR_ACTIVITY_REQUEST_NOT_FOUND", "request_id")


def rows(collection, predicate=None):
    """Every row of a collection in default (created_at, insertion) order."""
    values = list(getattr(db, collection).values())
    if predicate is not None:
        values = [v for v in values if predicate(v)]
    return ordered(values)


def matches(record, filters):
    for field, wanted in filters.items():
        if wanted is None:
            continue
        if record.get(field) != wanted:
            return False
    return True
