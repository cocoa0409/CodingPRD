"""In-memory store. Every collection starts EMPTY on every boot: no seeding, no preload,
no persistence of any kind. Each `bash start.sh` therefore wipes all state.
"""

from flask import g

from core import ApiError, new_id, next_seq, now_utc

TRUCKS = {}
PRODUCTIONS = {}
SURVEYS = {}
CAMERA_POSITIONS = {}
PATHS = {}
BOOKINGS = {}
CREW_MEMBERS = {}
CREW_CALLS = {}
FEEDS = {}
PREPS = {}
REHEARSALS = {}
SHOWS = {}
INCIDENTS = {}

ALL_COLLECTIONS = (
    TRUCKS,
    PRODUCTIONS,
    SURVEYS,
    CAMERA_POSITIONS,
    PATHS,
    BOOKINGS,
    CREW_MEMBERS,
    CREW_CALLS,
    FEEDS,
    PREPS,
    REHEARSALS,
    SHOWS,
    INCIDENTS,
)


def new_row(versioned=True, **fields):
    """Create a row with the common fields described in PRD 2.4.

    `versioned=False` is used for the two append-only log rows (CameraPosition and
    Incident) which carry only `id` and `created_at`.
    """
    row = {"id": new_id(), "_seq": next_seq(), "_created": now_utc()}
    if versioned:
        row["_updated"] = now_utc()
        row["version"] = 1
    row.update(fields)
    return row


def _touched_set():
    try:
        touched = g.get("_touched_rows", None)
    except RuntimeError:
        return None
    if touched is None:
        touched = set()
        g._touched_rows = touched
    return touched


def touch(row):
    """Refresh updated_at and bump version at most once per request per row.

    PRD 2.4 says version increments by exactly 1 on every mutation of the row, and
    PRD 3.3 says a truck assignment (whose own derivation may mutate the same row
    again) increments the production's version by 1 -- so a single request that
    mutates a row, directly and/or through the derivation, advances it by exactly 1.
    """
    if "version" not in row:
        return
    row["_updated"] = now_utc()
    touched = _touched_set()
    if touched is None:
        row["version"] += 1
        return
    if row["id"] in touched:
        return
    touched.add(row["id"])
    row["version"] += 1


def set_fields(row, **changes):
    """Apply changes, bumping version/updated_at only when a value actually changes."""
    dirty = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            dirty = True
    if dirty:
        touch(row)
    return dirty


def ordered(collection):
    """Rows in created_at ascending order (PRD 2.3 default list ordering)."""
    return sorted(collection.values(), key=lambda row: row["_seq"])


def where(collection, **predicates):
    rows = []
    for row in ordered(collection):
        match = True
        for key, value in predicates.items():
            if row.get(key) != value:
                match = False
                break
        if match:
            rows.append(row)
    return rows


def fetch(collection, row_id, error_id, message, http_status=404):
    if not isinstance(row_id, str) or row_id not in collection:
        raise ApiError(error_id, message, http_status)
    return collection[row_id]


def find_production(production_id):
    return fetch(
        PRODUCTIONS, production_id, "ERR_PRODUCTION_NOT_FOUND", "Production not found.",
    )


def find_truck(truck_id):
    return fetch(TRUCKS, truck_id, "ERR_TRUCK_NOT_FOUND", "Production truck not found.")


def find_survey(survey_id):
    return fetch(SURVEYS, survey_id, "ERR_SURVEY_NOT_FOUND", "Venue survey not found.")


def find_path(path_id):
    return fetch(PATHS, path_id, "ERR_PATH_NOT_FOUND", "Transmission path not found.")


def find_booking(booking_id):
    return fetch(BOOKINGS, booking_id, "ERR_BOOKING_NOT_FOUND", "Path booking not found.")


def find_crew_member(member_id):
    return fetch(
        CREW_MEMBERS, member_id, "ERR_CREW_MEMBER_NOT_FOUND", "Crew member not found.",
    )


def find_crew_call(call_id):
    return fetch(CREW_CALLS, call_id, "ERR_CREW_CALL_NOT_FOUND", "Crew call not found.")


def find_feed(feed_id):
    return fetch(FEEDS, feed_id, "ERR_FEED_NOT_FOUND", "Data feed not found.")


def find_prep(prep_id):
    return fetch(PREPS, prep_id, "ERR_PREP_NOT_FOUND", "System prep not found.")


def find_rehearsal(rehearsal_id):
    return fetch(REHEARSALS, rehearsal_id, "ERR_REHEARSAL_NOT_FOUND", "Rehearsal not found.")


def find_show(show_id):
    return fetch(SHOWS, show_id, "ERR_SHOW_NOT_FOUND", "Show execution not found.")
