"""Schema validation (PRD §2.11 rung 12) and pagination parsing (rung 13)."""

import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError

# ---------------------------------------------------------------- enumerations
ROLES = [
    "FacilityAdmin",
    "PostSupervisor",
    "SoundEditor",
    "Mixer",
    "QcOperator",
    "ClientReviewer",
]
PLATFORMS = ["THEATRICAL", "BROADCAST", "STREAMING", "INTERNATIONAL_ME"]
CHANNEL_LAYOUTS = ["STEREO", "5_1", "7_1", "ATMOS"]
ASSET_KINDS = ["SFX", "FOLEY", "MUSIC_LIBRARY"]
LICENSE_TYPES = ["ROYALTY_FREE", "RIGHTS_MANAGED"]
TERRITORIES = ["WORLDWIDE", "DOMESTIC"]
UNION_STATUSES = ["UNION", "NON_UNION"]
TURNAROUND_CLASSES = ["STANDARD", "EXPEDITED", "RUSH"]
STEM_LAYOUTS = ["STEREO", "5_1", "7_1", "ATMOS"]
CUE_SOURCES = ["COMPOSER_ORIGINAL", "LIBRARY"]
BOOKING_TYPES = ["PREMIX", "FINAL_MIX", "PRINTMASTER"]
CLIENT_ATTENDANCE = ["ONSITE", "REMOTE", "NONE"]
CANCELLATION_REASONS = ["CLIENT_REQUEST", "SCHEDULE_CONFLICT", "TALENT_NO_SHOW"]

PIPELINE_STAGES = ["INTAKE", "EDITORIAL", "PREMIX", "FINAL_MIX", "QC", "DELIVERED", "ARCHIVED"]
POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
PROJECT_PICTURE_STATUSES = ["NOT_LOCKED", "LOCKED", "LOCK_BROKEN"]
STEM_STATUSES = ["DRAFT", "CONFORMED", "STALE", "RETIRED"]
CUE_STATUSES = ["ACTIVE", "SUPERSEDED"]
USAGE_CLEARANCE_STATUSES = ["CLEARED", "UNLICENSED"]
ADR_STATUSES = ["PROPOSED", "CONFIRMED", "RECORDED", "CANCELLED", "NO_SHOW"]
BOOKING_STATUSES = ["RESERVED", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "RELEASED", "SUPERSEDED"]
DELIVERABLE_STATUSES = [
    "PREPARED",
    "QC_SUBMITTED",
    "QC_REJECTED",
    "REMEDIATION",
    "QC_PASSED",
    "DELIVERED",
    "INVALIDATED",
    "SUPERSEDED",
]
ASSET_STATUSES = ["ACTIVE", "REVOKED"]

TWO = Decimal("0.01")

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|z|[+-]\d{2}:?\d{2})$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def bad_request(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parses the JSON request body.  A body that is not a JSON object is a
    schema violation (PRD §2.11 rung 12)."""
    raw = request.get_data()
    if raw is None or len(raw) == 0:
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None or not isinstance(parsed, dict):
        bad_request("The request body must be a JSON object.")
    return parsed


def parse_instant(value, field):
    """PRD §2.4: 'A malformed instant in any request body is a schema violation'."""
    if not isinstance(value, str):
        bad_request("Field '%s' must be an ISO-8601 UTC instant string." % field)
    text = value.strip()
    m = _INSTANT_RE.match(text)
    if m:
        year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
        frac = m.group(7)
        micro = 0
        if frac:
            micro = int(round(float(frac) * 1000000))
        offset = m.group(8)
        try:
            dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
        except ValueError:
            bad_request("Field '%s' is not a valid instant." % field)
        if offset not in ("Z", "z"):
            sign = 1 if offset[0] == "+" else -1
            digits = offset[1:].replace(":", "")
            delta_minutes = int(digits[:2]) * 60 + int(digits[2:])
            dt = dt.fromtimestamp(dt.timestamp() - sign * delta_minutes * 60, tz=timezone.utc)
        return dt
    m = _DATE_RE.match(text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            bad_request("Field '%s' is not a valid instant." % field)
    bad_request("Field '%s' must be an ISO-8601 UTC instant string." % field)


def _missing(payload, name):
    return name not in payload or payload[name] is None


def v_string(payload, name, required=True, minlen=1, maxlen=None, default=None):
    if _missing(payload, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % name)
    if len(value) < minlen:
        bad_request("Field '%s' must be at least %d characters." % (name, minlen))
    if maxlen is not None and len(value) > maxlen:
        bad_request("Field '%s' must be at most %d characters." % (name, maxlen))
    return value


def v_int(payload, name, required=True, minv=None, maxv=None, default=None):
    if _missing(payload, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field '%s' must be an integer." % name)
    if minv is not None and value < minv:
        bad_request("Field '%s' must be at least %s." % (name, minv))
    if maxv is not None and value > maxv:
        bad_request("Field '%s' must be at most %s." % (name, maxv))
    return value


def v_decimal(payload, name, required=True, minv=None, maxv=None, default=None):
    """Hours, minutes and loudness quantities: carried to exactly 2 dp (PRD §2.8)."""
    if _missing(payload, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad_request("Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except Exception:
        bad_request("Field '%s' must be a number." % name)
    if minv is not None and dec < Decimal(str(minv)):
        bad_request("Field '%s' must be at least %s." % (name, minv))
    if maxv is not None and dec > Decimal(str(maxv)):
        bad_request("Field '%s' must be at most %s." % (name, maxv))
    return dec.quantize(TWO, rounding=ROUND_HALF_UP)


def v_bool(payload, name, required=True, default=None):
    if _missing(payload, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % name)
    return value


def v_enum(payload, name, allowed, required=True, default=None):
    if _missing(payload, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        bad_request("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def v_instant(payload, name, required=True, default=None):
    if _missing(payload, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    return parse_instant(payload[name], name)


def v_str_array(payload, name, allowed, required=True, min_items=1):
    if _missing(payload, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return None
    value = payload[name]
    if not isinstance(value, list):
        bad_request("Field '%s' must be an array." % name)
    if len(value) < min_items:
        bad_request("Field '%s' must hold at least %d entries." % (name, min_items))
    for entry in value:
        if not isinstance(entry, str) or entry not in allowed:
            bad_request("Field '%s' entries must be one of %s." % (name, ", ".join(allowed)))
    return list(value)


_INT_RE = re.compile(r"^[+-]?\d+$")


def pagination():
    """PRD §2.3.  limit defaults to 10, min 1, max 100; offset defaults to 0, min 0."""
    limit = 10
    offset = 0
    if "limit" in request.args:
        raw = request.args.get("limit")
        if raw is None or not _INT_RE.match(raw.strip()):
            raise ApiError("ERR_INVALID_PAGINATION")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if "offset" in request.args:
        raw = request.args.get("offset")
        if raw is None or not _INT_RE.match(raw.strip()):
            raise ApiError("ERR_INVALID_PAGINATION")
        offset = int(raw.strip())
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def query_filter(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value
