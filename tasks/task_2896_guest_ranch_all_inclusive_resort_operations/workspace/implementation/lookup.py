"""Path and body identifier resolution (PRD 2.8, precedence rules 7 and 8)."""

from errors import ApiError
from store import db

NOT_FOUND = {
    "seasons": "ERR_SEASON_NOT_FOUND",
    "cabins": "ERR_CABIN_NOT_FOUND",
    "guests": "ERR_GUEST_NOT_FOUND",
    "rider_assessments": "ERR_ASSESSMENT_NOT_FOUND",
    "bookings": "ERR_BOOKING_NOT_FOUND",
    "horses": "ERR_HORSE_NOT_FOUND",
    "horse_health_events": "ERR_HORSE_NOT_FOUND",
    "activity_slots": "ERR_SLOT_NOT_FOUND",
    "guide_assignments": "ERR_GUIDE_ASSIGNMENT_NOT_FOUND",
    "activity_reservations": "ERR_RESERVATION_NOT_FOUND",
    "staff_members": "ERR_STAFF_MEMBER_NOT_FOUND",
    "incident_reports": "ERR_INCIDENT_NOT_FOUND",
}


def find(collection, ident, error_id=None):
    row = getattr(db, collection).get(ident)
    if row is None:
        raise ApiError(error_id or NOT_FOUND[collection])
    return row


def find_body_ref(collection, data, field, error_id=None):
    """Resolves a payload foreign key when it is present and string-shaped."""
    value = data.get(field)
    if value is None or not isinstance(value, str):
        return None
    return find(collection, value, error_id)


def health_event(ident):
    row = db.horse_health_events.get(ident)
    if row is None:
        raise ApiError("ERR_HORSE_NOT_FOUND", "Health event not found.")
    return row
