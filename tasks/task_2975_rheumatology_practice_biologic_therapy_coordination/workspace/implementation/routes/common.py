"""Helpers shared by every route module."""

from errors import fail
from response import ok_list
from store import db, sort_rows
from validation import q_pagination


def resolve(collection, row_id, error_id):
    """PRD 2.5: path parameters are resolved strictly left to right."""
    row = collection.get(row_id)
    if row is None:
        fail(error_id)
    return row


def episode_or_404(episode_id):
    return resolve(db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")


def patient_or_404(patient_id):
    return resolve(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")


def paginate(rows, serializer):
    """PRD 2.3: created_at ascending, then the page window, then the meta."""
    limit, offset = q_pagination()
    ordered = sort_rows(rows)
    total = len(ordered)
    window = ordered[offset : offset + limit]
    return ok_list([serializer(row) for row in window], limit, offset, total)


def unique_or_409(collection, field, value):
    """PRD 3.1: five natural keys are unique within their own collection."""
    for row in collection.values():
        if row.get(field) == value:
            fail(
                "ERR_DUPLICATE_IDENTIFIER",
                "A record with %s '%s' already exists." % (field, value),
            )
