"""Shared helpers: envelope, timestamps, ids, decimal rounding, errors."""
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import get_clock


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- error helpers ---------------------------------------------------------

def err_missing_user_context(msg="X-User-ID and X-User-Role headers are required"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def err_insufficient_permissions(msg="Role not permitted for this operation"):
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, msg)


def err_data_share_forbidden(msg="No active data-share grant covers this read"):
    return ApiError("ERR_DATA_SHARE_FORBIDDEN", 403, msg)


def err_invalid_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_mode_config(msg):
    return ApiError("ERR_INVALID_MODE_CONFIG", 400, msg)


def err_not_found(error_id, msg):
    return ApiError(error_id, 404, msg)


def err_connection_invalid_state(msg="Connection state does not allow this transition"):
    return ApiError("ERR_CONNECTION_INVALID_STATE", 409, msg)


def err_connection_not_active(msg="Connection must be TESTING or ACTIVE"):
    return ApiError("ERR_CONNECTION_NOT_ACTIVE", 409, msg)


def err_remediation_not_proven(msg="A heartbeat must be recorded after suspended_at"):
    return ApiError("ERR_REMEDIATION_NOT_PROVEN", 409, msg)


def err_testing_window_conflict(msg="Testing window intersects another TESTING connection"):
    return ApiError("ERR_TESTING_WINDOW_CONFLICT", 409, msg)


def err_quality_gate_not_met(msg="data_quality_score must be at least 70"):
    return ApiError("ERR_QUALITY_GATE_NOT_MET", 422, msg)


def err_shipment_not_trackable(msg="Shipment is DELIVERED or CANCELLED"):
    return ApiError("ERR_SHIPMENT_NOT_TRACKABLE", 409, msg)


def err_shipment_not_cancellable(msg="Shipment is not in a cancellable state"):
    return ApiError("ERR_SHIPMENT_NOT_CANCELLABLE", 409, msg)


def err_shipment_terminal(msg="Shipment is DELIVERED or CANCELLED"):
    return ApiError("ERR_SHIPMENT_TERMINAL", 409, msg)


def err_match_score_below_threshold(msg="match_score must be strictly greater than 0.90"):
    return ApiError("ERR_MATCH_SCORE_BELOW_THRESHOLD", 422, msg)


def err_link_not_proposed(msg="Link is not in a state that allows this transition"):
    return ApiError("ERR_LINK_NOT_PROPOSED", 409, msg)


def err_alert_invalid_state(msg="Alert state does not allow this transition"):
    return ApiError("ERR_ALERT_INVALID_STATE", 409, msg)


def err_facility_not_active(msg="Facility must be ACTIVE"):
    return ApiError("ERR_FACILITY_NOT_ACTIVE", 409, msg)


def err_appointment_window_conflict(msg="Appointment window overlaps an existing SCHEDULED appointment"):
    return ApiError("ERR_APPOINTMENT_WINDOW_CONFLICT", 409, msg)


def err_appointment_invalid_state(msg="Appointment state does not allow this transition"):
    return ApiError("ERR_APPOINTMENT_INVALID_STATE", 409, msg)


def err_grant_already_revoked(msg="Grant is already REVOKED"):
    return ApiError("ERR_GRANT_ALREADY_REVOKED", 409, msg)


def err_stale_version(msg="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


# --- ids / timestamps -------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:24]


def _iso_utc(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-09-01T00:00:00.000Z"""
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def now_ts():
    """Current logical time as ISO string."""
    return _iso_utc(get_clock())


def wall_ts():
    """Wall-clock UTC timestamp for meta.api_request_timestamp."""
    dt = datetime.now(timezone.utc)
    return _iso_utc(dt)


def to_iso(dt):
    return _iso_utc(dt)


# --- datetime parsing --------------------------------------------------------

ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(?:Z|([+-])(\d{2}):(\d{2}))?$"
)


def parse_iso(s):
    """Parse an ISO 8601 timestamp to an aware UTC datetime; None if unparseable."""
    if not isinstance(s, str):
        return None
    m = ISO_RE.match(s.strip())
    if not m:
        return None
    year, mon, day, hh, mm, ss = (int(x) for x in m.group(1, 2, 3, 4, 5, 6))
    frac = m.group(7) or "0"
    # clamp to microseconds
    frac = (frac + "000000")[:6]
    micro = int(frac)
    sign = m.group(8)
    if sign:
        off_h = int(m.group(9))
        off_m = int(m.group(10))
        delta = timedelta(hours=off_h, minutes=off_m)
        if sign == "-":
            delta = -delta
        tz = timezone(delta)
    else:
        tz = timezone.utc
    try:
        dt = datetime(year, mon, day, hh, mm, ss, micro, tzinfo=tz)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def minutes_between(later, earlier):
    """Whole-minute difference later - earlier as a Decimal (may be fractional)."""
    delta = later - earlier
    return Decimal(delta.total_seconds()) / Decimal(60)


# --- rounding ----------------------------------------------------------------

def rhu(value):
    """Round half up to an integer. Accepts int/Decimal/float-as-Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to two decimals, returning a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
