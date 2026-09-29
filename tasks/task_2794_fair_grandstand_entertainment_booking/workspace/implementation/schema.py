"""Payload and query-string schema validation (PRD section 2.10 step 3).

Every failure in this module is reported as ERR_INVALID_REQUEST (HTTP 400).
"""

from flask import request

from db import parse_date, parse_hhmm, parse_ts
from errors import ApiError

# ---------------------------------------------------------------------------
# enum universes
# ---------------------------------------------------------------------------

GENRES = ("COUNTRY", "ROCK", "HIP_HOP", "LATIN", "CHRISTIAN", "COMEDY", "TRIBUTE")
AUDIENCE_SEGMENTS = ("FAMILY", "YOUNG_ADULT", "ADULT_45_PLUS", "TEEN")
STRATEGY_BASES = ("ATTENDANCE_WEIGHTED", "REVENUE_WEIGHTED")
BOOKING_POSTURES = ("OPEN", "SATURATED")
DEAL_TYPES = ("VERSUS", "GUARANTEE_PLUS_BACKEND")
OFFER_STATUSES = ("DRAFT", "SENT", "COUNTERED", "ACCEPTED", "DECLINED", "WITHDRAWN", "EXPIRED")
PROPOSED_BY = ("BUYER", "AGENT")
BOOKING_STATUSES = ("DATE_HELD", "ANNOUNCED", "PERFORMED", "CANCELLED", "POSTPONED")
TICKETING_STATUSES = ("SCALED_PENDING", "SCALED", "ON_SALE", "SALES_CLOSED", "REFUNDING", "REFUNDED")
SEATING_TYPES = ("RESERVED", "GENERAL_ADMISSION")
SCALE_STATUSES = ("ON_SALE_ELIGIBLE", "REFUND_DUE", "CLOSED")
BATCH_KINDS = ("SALE", "REFUND")
CHANNELS = ("ONLINE", "BOX_OFFICE", "PHONE", "COMP")
ADVANCE_STATUSES = (
    "ADVANCE_PENDING",
    "ADVANCE_IN_REVIEW",
    "ADVANCE_COMPLETE",
    "ADVANCE_BLOCKED",
    "ADVANCE_CANCELLED",
)
RIDER_CATEGORIES = ("STAGING", "SOUND", "LIGHTING", "HOSPITALITY")
RIDER_STATUSES = ("REQUESTED", "APPROVED", "DENIED", "SUBSTITUTED", "VOIDED")
DECISIONS = ("APPROVED", "DENIED", "SUBSTITUTED")
BLOCKED_REASONS = ("DENIED_CRITICAL_ITEM", "MISSING_STAGE_PLOT")
TRADE_CATEGORIES = ("BEVERAGE", "AUTOMOTIVE", "TELECOM", "AGRIBUSINESS", "FINANCIAL", "QSR")
EXCLUSIVITY_TIERS = ("PRESENTING", "SUPPORTING")
RIGHTS = ("STAGE_NAMING", "PRESENTING", "SAMPLING", "SIGNAGE")
ACTIVATION_STATUSES = ("PROPOSED", "CONFIRMED", "FULFILLED", "CANCELLED")
SETTLEMENT_BASES = ("PROVISIONAL", "FINAL")
MERCH_SELLERS = ("ARTIST", "VENUE")
SETTLEMENT_STATUSES = ("DRAFT", "PENDING_APPROVAL", "APPROVED")
REJECTION_REASONS = ("GROSS_MISMATCH", "EXPENSE_UNSUPPORTED", "MERCH_MISSING")
ACTION_TYPES = ("CANCEL", "POSTPONE")
REASON_CODES = ("SEVERE_WEATHER", "LIGHTNING_HOLD", "ARTIST_ILLNESS", "PRODUCTION_FAILURE")
REFUND_POLICIES = ("FULL_REFUND", "RAIN_CHECK", "NO_REFUND_AFTER_DOORS")

_MISSING = object()


def bad(message="Request payload failed schema validation."):
    raise ApiError("ERR_INVALID_REQUEST", message)


# ---------------------------------------------------------------------------
# body access
# ---------------------------------------------------------------------------

def body():
    """The JSON request body as a dict.  A missing body reads as an empty dict."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _raw(data, name, default):
    if name not in data or data.get(name) is None:
        if default is _MISSING:
            bad("Field '%s' is required." % name)
        return (False, default)
    return (True, data.get(name))


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _as_int(value, name):
    if _is_int(value):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    bad("Field '%s' must be an integer." % name)


def f_int(data, name, default=_MISSING, minimum=None, maximum=None):
    present, value = _raw(data, name, default)
    if not present:
        return value
    number = _as_int(value, name)
    if minimum is not None and number < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and number > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    return number


def f_cents(data, name, default=_MISSING):
    """Any *_cents field: an integer of at least 0."""
    return f_int(data, name, default=default, minimum=0)


def f_number(data, name, default=_MISSING, minimum=None, maximum=None):
    present, value = _raw(data, name, default)
    if not present:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    number = float(value)
    if minimum is not None and number < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and number > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    return number


def f_pct(data, name, default=_MISSING):
    """Any *_pct field: a decimal between 0 and 1 inclusive."""
    return f_number(data, name, default=default, minimum=0.0, maximum=1.0)


def f_bool(data, name, default=_MISSING):
    present, value = _raw(data, name, default)
    if not present:
        return value
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def f_str(data, name, default=_MISSING, allow_blank=False):
    present, value = _raw(data, name, default)
    if not present:
        return value
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if not allow_blank and value.strip() == "":
        bad("Field '%s' must not be blank." % name)
    return value


def f_enum(data, name, members, default=_MISSING):
    present, value = _raw(data, name, default)
    if not present:
        return value
    if not isinstance(value, str) or value not in members:
        bad("Field '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def f_date(data, name, default=_MISSING):
    present, value = _raw(data, name, default)
    if not present:
        return value
    if not isinstance(value, str) or parse_date(value) is None:
        bad("Field '%s' must be a calendar date in YYYY-MM-DD form." % name)
    return value.strip()


def f_ts(data, name, default=_MISSING):
    """Any *_utc field: an ISO 8601 instant carrying a trailing Z."""
    present, value = _raw(data, name, default)
    if not present:
        return value
    if not isinstance(value, str) or parse_ts(value) is None:
        bad("Field '%s' must be an ISO 8601 UTC instant ending in Z." % name)
    return value


def f_hhmm(data, name, default=_MISSING):
    present, value = _raw(data, name, default)
    if not present:
        return value
    if not isinstance(value, str) or parse_hhmm(value) is None:
        bad("Field '%s' must be a UTC time of day in HH:MM form." % name)
    return value.strip()


def reject_unknown(data, allowed):
    """No-op hook kept deliberately permissive: unknown keys are ignored."""
    return data


# ---------------------------------------------------------------------------
# query string
# ---------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or raw.strip() == "" or not _looks_int(raw):
            bad("Query parameter 'limit' must be an integer between 1 and 100.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or raw.strip() == "" or not _looks_int(raw):
            bad("Query parameter 'offset' must be an integer of at least 0.")
        offset = int(raw)
        if offset < 0:
            bad("Query parameter 'offset' must be at least 0.")
    return (limit, offset)


def _looks_int(text):
    body_text = text.strip()
    if body_text.startswith("-") or body_text.startswith("+"):
        body_text = body_text[1:]
    return body_text.isdigit() and body_text != ""


def q_str(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or value.strip() == "":
        bad("Query parameter '%s' must not be blank." % name)
    return value


def q_enum(name, members):
    value = q_str(name)
    if value is None:
        return None
    if value not in members:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def q_int(name, minimum=None, maximum=None):
    if name not in request.args:
        return None
    raw = request.args.get(name)
    if raw is None or not _looks_int(raw):
        bad("Query parameter '%s' must be an integer." % name)
    value = int(raw)
    if minimum is not None and value < minimum:
        bad("Query parameter '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Query parameter '%s' must be at most %s." % (name, maximum))
    return value
