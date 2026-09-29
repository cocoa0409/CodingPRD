"""Helpers shared by every blueprint: envelope shortcuts and small gates."""

import db
import response
import validation
from errors import fail
from services import calc


def created(row):
    return response.object_response(db.serialize(row), 201)


def ok(row):
    return response.object_response(db.serialize(row), 200)


def listing(rows):
    """Rung 4 pagination is parsed here; total_count is taken before the window."""
    limit, offset = validation.pagination()
    window, total = response.paginate(rows, limit, offset)
    return response.array_response(db.serialize_many(window), limit, offset, total)


def require_venue_open(venue):
    """Rung 9: FROZEN and CLOSED_OUT parcels refuse work (PRD 2.10)."""
    if venue["site_posture"] != "OPEN":
        fail(
            "ERR_VENUE_FROZEN",
            "Venue %s reads site_posture %s." % (venue["id"], venue["site_posture"]),
        )


def governing_permit_or_fail(venue):
    """Rung 23: exactly one APPROVED application governs the parcel."""
    permit = calc.governing_permit(venue["id"])
    if permit is None:
        fail("ERR_PERMIT_NOT_APPROVED", "Venue %s has no governing approved permit." % venue["id"])
    return permit


def venue_of(row):
    return db.get("venues", row["venue_id"])


def course_of(row):
    return db.get("courses", row["course_id"])


def wave_of(entry):
    return db.get("waves", entry["wave_id"])


def division_of(wave):
    return db.get("divisions", wave["division_id"])


def participant_of(entry):
    return db.get("participants", entry["participant_id"])


def recount_wave(wave):
    with db.mutation(wave):
        wave["assigned_count"] = len(calc.entries_of_wave(wave["id"]))
