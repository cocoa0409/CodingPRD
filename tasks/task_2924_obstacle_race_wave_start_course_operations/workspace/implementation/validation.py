"""Rung 3 (path resolution), rung 4 (body/query schema) and rung 5 (body FKs).

Everything here raises ApiError with the exact error_id the PRD's ladder names.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import fail

_MISSING = object()

# ---------------------------------------------------------------------------
# Enumerations (scaffold section 1.1)
# ---------------------------------------------------------------------------

TERRAIN_TYPES = ("FIELD", "FOREST", "QUARRY", "SKI_SLOPE")
WATER_ACCESS = ("NONE", "POND", "RIVER")
SITE_POSTURES = ("OPEN", "FROZEN", "CLOSED_OUT")
PERMIT_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "REVISION_REQUESTED",
    "APPROVED",
    "DENIED",
    "EXPIRED",
)
PERMIT_DECISIONS = ("APPROVED", "REVISION_REQUESTED", "DENIED")
COURSE_STATUSES = ("DRAFT", "VALIDATED", "PUBLISHED", "SUSPENDED", "COMPLETED")
READINESS_POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
BYPASS_MODES = ("NONE", "PENALTY_LOOP", "TIMED_PENALTY", "MANDATORY")
STAFFING_STATES = ("UNSTAFFED", "PARTIAL", "MARSHALED")
DIVISION_TYPES = ("COMPETITIVE", "OPEN", "TEAM")
BYPASS_POLICIES = ("ALLOWED_WITH_PENALTY", "DQ_ON_BYPASS", "MANDATORY_COMPLETION")
SCORING_MODES = ("GUN_TIME", "CHIP_TIME")
RELEASE_STATUSES = ("SCHEDULED", "HELD", "RELEASED", "STARTED", "CLOSED")
ROSTER_STATUSES = ("OPEN", "LOCKED", "SEALED")
CLEARANCE_STATUSES = ("PENDING", "CLEARED", "MEDICALLY_HELD")
PROGRESS_STATUSES = ("REGISTERED", "CHECKED_IN", "STARTED", "FINISHED", "DNF", "DNS")
RESULT_STATUSES = (
    "PENDING",
    "PROVISIONAL",
    "UNDER_PROTEST",
    "OFFICIAL",
    "DISQUALIFIED",
    "NOT_CLASSIFIED",
)
ATTEMPT_OUTCOMES = ("COMPLETED", "BYPASSED", "FAILED_PENALTY", "SKIPPED_UNMARSHALED")
STAFF_ROLES = ("MARSHAL", "MEDIC", "WATER_SAFETY", "SWEEP")
CERTIFICATION_LEVELS = ("BASIC", "ADVANCED", "PARAMEDIC", "LIFEGUARD")
ASSIGNMENT_STATUSES = ("CONFIRMED", "VACATED")
SERVICE_TYPES = ("BAG_CHECK", "RINSE_STATION", "SPECTATOR_ZONE")
FESTIVAL_STATUSES = ("OPEN", "CLOSED")
TASK_TYPES = ("RESEED", "DECOMPACT", "SILT_REMOVAL", "DEBRIS_SWEEP")
TASK_STATUSES = ("PENDING", "VERIFIED", "REMEDIATION_REQUIRED")
INSPECTION_OUTCOMES = ("VERIFIED", "REMEDIATION_REQUIRED")
SETTLEMENT_TYPES = ("PROGRESSIVE", "FINAL")
ADJUDICATION_OUTCOMES = ("UPHELD_ADJUSTED", "DENIED_OFFICIAL", "DISQUALIFIED")
BLOCKING_MEDICAL_FLAGS = ("CARDIAC", "PREGNANCY", "RECENT_SURGERY")


# ---------------------------------------------------------------------------
# Body access
# ---------------------------------------------------------------------------


def body(required=True):
    """Parse the JSON body.  Malformed JSON or a non-object is a schema error."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            fail("ERR_INVALID_REQUEST", "A JSON request body is required.")
        return {}
    payload = request.get_json(silent=True)
    if payload is None or not isinstance(payload, dict):
        if required:
            fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return {}
    return payload


def optional_body():
    return body(required=False)


# ---------------------------------------------------------------------------
# Scalar field validators (rung 4)
# ---------------------------------------------------------------------------


def _bad(key, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (key, why))


def _present(payload, key, default):
    if key not in payload or payload.get(key) is None:
        if default is _MISSING:
            _bad(key, "is required")
        return default, False
    return payload[key], True


def field_str(payload, key, min_len=1, max_len=None, default=_MISSING):
    value, present = _present(payload, key, default)
    if not present:
        return value
    if not isinstance(value, str):
        _bad(key, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(key, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(key, "must be at most %d characters" % max_len)
    return value


def field_int(payload, key, minimum=None, maximum=None, default=_MISSING):
    value, present = _present(payload, key, default)
    if not present:
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(key, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be at most %s" % maximum)
    return value


def field_decimal(payload, key, minimum=None, exclusive_min=None, default=_MISSING):
    """A decimal quantity carried to two places (PRD 2.9)."""
    value, present = _present(payload, key, default)
    if not present:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(key, "must be a number")
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(key, "must be a number")
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        _bad(key, "must be greater than %s" % exclusive_min)
    if minimum is not None and dec < Decimal(str(minimum)):
        _bad(key, "must be at least %s" % minimum)
    return dec


def field_bool(payload, key, default=_MISSING):
    value, present = _present(payload, key, default)
    if not present:
        return value
    if not isinstance(value, bool):
        _bad(key, "must be a boolean")
    return value


def field_enum(payload, key, allowed, default=_MISSING):
    value, present = _present(payload, key, default)
    if not present:
        return value
    if not isinstance(value, str) or value not in allowed:
        _bad(key, "must be one of %s" % ", ".join(allowed))
    return value


def field_datetime(payload, key, default=_MISSING):
    value, present = _present(payload, key, default)
    if not present:
        return value
    return parse_instant(value, key)


def field_id(payload, key, default=_MISSING):
    value, present = _present(payload, key, default)
    if not present:
        return value
    if not isinstance(value, str) or value == "":
        _bad(key, "must be a non-empty string identifier")
    return value


def field_str_list(payload, key, default=_MISSING):
    value, present = _present(payload, key, default)
    if not present:
        return value
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        _bad(key, "must be an array of strings")
    return list(value)


def parse_instant(value, key="timestamp"):
    if not isinstance(value, str) or value.strip() == "":
        _bad(key, "must be an ISO 8601 UTC instant")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _bad(key, "must be an ISO 8601 UTC instant")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def forbid_field(payload, key, error_id="ERR_INVALID_REQUEST", message=None):
    """A field that must not be supplied at all."""
    if key in payload and payload.get(key) is not None:
        fail(error_id, message or "Field '%s' must not be supplied." % key)


# ---------------------------------------------------------------------------
# Query parameters (rung 4)
# ---------------------------------------------------------------------------


def pagination():
    limit = _query_int("limit", 10, minimum=1, maximum=100)
    offset = _query_int("offset", 0, minimum=0)
    return limit, offset


def _query_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be at most %d." % (name, maximum))
    return value


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        fail(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)),
        )
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


# ---------------------------------------------------------------------------
# Path resolution (rung 3) and body foreign keys (rung 5)
# ---------------------------------------------------------------------------


def _resolve(collection, row_id, error_id):
    row = db.get(collection, row_id)
    if row is None:
        fail(error_id, "No such resource: %s." % row_id)
    return row


def path_venue(venue_id):
    return _resolve("venues", venue_id, "ERR_VENUE_NOT_FOUND")


def path_permit(permit_id):
    return _resolve("permits", permit_id, "ERR_PERMIT_NOT_FOUND")


def path_course(course_id):
    return _resolve("courses", course_id, "ERR_COURSE_NOT_FOUND")


def path_obstacle(obstacle_id):
    return _resolve("obstacles", obstacle_id, "ERR_OBSTACLE_NOT_FOUND")


def path_division(division_id):
    return _resolve("divisions", division_id, "ERR_DIVISION_NOT_FOUND")


def path_wave(wave_id):
    return _resolve("waves", wave_id, "ERR_WAVE_NOT_FOUND")


def path_participant(participant_id):
    return _resolve("participants", participant_id, "ERR_PARTICIPANT_NOT_FOUND")


def path_entry(entry_id):
    return _resolve("entries", entry_id, "ERR_ENTRY_NOT_FOUND")


def path_assignment(assignment_id):
    return _resolve("staff_assignments", assignment_id, "ERR_STAFF_ASSIGNMENT_NOT_FOUND")


def path_task(task_id):
    return _resolve("restoration_tasks", task_id, "ERR_RESTORATION_TASK_NOT_FOUND")


def fk_division(division_id):
    return _resolve("divisions", division_id, "ERR_DIVISION_NOT_FOUND")


def fk_participant(participant_id):
    return _resolve("participants", participant_id, "ERR_PARTICIPANT_NOT_FOUND")


def fk_wave(wave_id):
    return _resolve("waves", wave_id, "ERR_WAVE_NOT_FOUND")


def fk_obstacle(obstacle_id, course_id=None):
    """Body obstacle references must resolve on the addressed course."""
    row = db.get("obstacles", obstacle_id)
    if row is None or (course_id is not None and row["course_id"] != course_id):
        fail("ERR_OBSTACLE_NOT_FOUND", "No such obstacle on this course: %s." % obstacle_id)
    return row


def fk_attempt(attempt_id, entry_id=None):
    row = db.get("attempts", attempt_id)
    if row is None or (entry_id is not None and row["entry_id"] != entry_id):
        fail("ERR_ATTEMPT_NOT_FOUND", "No such attempt on this entry: %s." % attempt_id)
    return row
