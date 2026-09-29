"""Small helpers shared by the route modules."""

import db
import response
import serialize
import validation
from errors import not_found

# collection name -> not-found error key
KIND = {
    "producers": "producer",
    "training_courses": "training_course",
    "course_enrollments": "course_enrollment",
    "series": "series",
    "programs": "program",
    "attestations": "attestation",
    "channels": "channel",
    "playback_slots": "playback_slot",
    "studio_resources": "studio_resource",
    "reservations": "reservation",
    "damage_assessments": "damage_assessment",
    "crew_assignments": "crew_assignment",
    "funding_periods": "funding_period",
    "archive_assets": "archive_asset",
}

# collections carrying an explicit monotone counter used as the ordering
# tie-break (PRD 2.3)
SEQUENCE_KEY = {
    "series": "sequence_number",
    "attestations": "sequence_number",
    "playback_slots": "sequence_number",
}


def must_exist(collection, ident):
    row = db.get(collection, ident)
    if row is None:
        raise not_found(KIND[collection], ident)
    return row


def single(collection, row, status=200):
    return response.object_response(serialize.dump(collection, row), status)


def created(collection, row):
    return response.object_response(serialize.dump(collection, row), 201)


def collection_response(collection, rows):
    limit, offset = validation.pagination()
    ordered = validation.sort_rows(rows, SEQUENCE_KEY.get(collection))
    page, total = validation.paginate(ordered, limit, offset)
    return response.list_response(serialize.dump_all(collection, page), limit, offset, total)


def filter_rows(collection, predicates):
    """predicates: list of (field, value) pairs; a None value is not applied."""
    rows = db.all_rows(collection)
    for field, value in predicates:
        if value is None:
            continue
        rows = [row for row in rows if row.get(field) == value]
    return rows
