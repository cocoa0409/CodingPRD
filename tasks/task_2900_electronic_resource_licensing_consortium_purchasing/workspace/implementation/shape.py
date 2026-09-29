"""Priority 6 - request shape validation. Every failure is ERR_INVALID_REQUEST."""

import re

from flask import request

from errors import ApiError

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")

CARNEGIE_CLASSES = ("R1", "R2", "MASTERS", "BACCALAUREATE")
ARCHIVAL_AGENCIES = ("PORTICO", "CLOCKSS", "LOCKSS")
PERPETUAL_MODES = ("NONE", "POST_CANCELLATION_SUBSET", "FULL_ARCHIVE")
ILL_MODES = ("PROHIBITED", "PRINT_ONLY", "SECURE_ELECTRONIC")
ACCESSIBILITY_LEVELS = ("NONE", "VPAT_PARTIAL", "WCAG_2_1_AA")
CRITERION_CODES = ("CONTENT_FIT", "INTERFACE", "ILL_TERMS", "TEXT_MINING", "ACCESSIBILITY", "PRICE_VALUE")
STAKEHOLDER_GROUPS = ("FACULTY", "GRADUATE", "UNDERGRADUATE", "LIBRARIAN")
TRIAL_STATUSES = ("DRAFT", "ACTIVE", "CLOSED", "ENDORSED", "DECLINED", "WITHDRAWN")
NEGOTIATION_STATUSES = ("DRAFTING", "VENDOR_REVIEW", "COUNTERED", "AGREED", "SIGNED")
COMMITMENT_STATUSES = ("PLEDGED", "CONFIRMED", "WITHDRAWN", "RELEASED")
CONTRACT_STATUSES = ("PENDING_ACTIVATION", "ACTIVE", "NOTICE_GIVEN", "CANCELLED", "EXPIRED")
ACCESS_STATUSES = ("UNCONFIGURED", "CONFIGURED", "DEGRADED", "POST_CANCELLATION", "SUSPENDED")
AUTH_METHODS = ("IP_RANGE", "EZPROXY", "SHIBBOLETH", "OPENATHENS")
PROBE_RESULTS = ("PASS", "FAIL_OFF_CAMPUS", "FAIL_ON_CAMPUS")
SYMPTOM_CODES = ("OFF_CAMPUS_DENIED", "WALK_IN_BLOCKED", "PROXY_LOOP", "SAML_ATTRIBUTE_MISSING")
ROOT_CAUSE_CODES = ("IP_RANGE_STALE", "PROXY_MISCONFIGURED", "VENDOR_SIDE", "ENTITLEMENT_MISSING")
REMEDY_CODES = ("IP_RANGE_UPDATED", "PROXY_FIXED", "VENDOR_TICKET_CLOSED", "ENTITLEMENT_LOADED")
INCIDENT_STATUSES = ("OPEN", "DIAGNOSED", "RESOLVED", "REOPENED")
DECISION_ACTIONS = ("RENEW", "CANCEL", "RESTRUCTURE")
DECISION_STATUSES = (
    "DRAFT", "VOTING", "DECIDED_RENEW", "DECIDED_CANCEL", "DECIDED_RESTRUCTURE",
    "EXECUTED", "REVERTED", "SUPERSEDED",
)
ARCHIVAL_STATUSES = ("PENDING", "ATTESTED", "VERIFIED", "FAILED")
DISPOSITIONS = ("ACCEPT", "COUNTER")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The parsed JSON body. A missing or unparsable body reads as empty."""
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover - defensive
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("The request body must be a JSON object.")
    return data


def present(data, field):
    return field in data and data[field] is not None


def req_string(data, field, allow_empty=False):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    if not allow_empty and value.strip() == "":
        bad("Field '%s' must not be empty." % field)
    return value


def opt_string(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    return value


def req_enum(data, field, allowed):
    value = req_string(data, field)
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def _coerce_int(field, value):
    if isinstance(value, bool):
        bad("Field '%s' must be an integer." % field)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    bad("Field '%s' must be an integer." % field)


def req_int(data, field, minimum=None, maximum=None):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    value = _coerce_int(field, data[field])
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (field, maximum))
    return value


def opt_int(data, field, minimum=None, maximum=None, default=None):
    if not present(data, field):
        return default
    value = _coerce_int(field, data[field])
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (field, maximum))
    return value


def _coerce_number(field, value):
    if isinstance(value, bool):
        bad("Field '%s' must be a number." % field)
    if isinstance(value, (int, float)):
        return value
    bad("Field '%s' must be a number." % field)


def req_number(data, field, minimum=None, maximum=None):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    value = _coerce_number(field, data[field])
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (field, maximum))
    return value


def req_bool(data, field):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def opt_bool(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def req_date(data, field):
    value = req_string(data, field)
    if not DATE_RE.match(value):
        bad("Field '%s' must be a YYYY-MM-DD calendar date." % field)
    import datetime
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        bad("Field '%s' must be a valid calendar date." % field)
    return value


def req_month(data, field):
    value = req_string(data, field)
    if not MONTH_RE.match(value):
        bad("Field '%s' must be a YYYY-MM month." % field)
    return value


def req_string_array(data, field, allow_empty=False):
    if not present(data, field):
        bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % field)
    if not allow_empty and len(value) == 0:
        bad("Field '%s' must not be empty." % field)
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            bad("Field '%s' must contain non-empty strings." % field)
    return list(value)


def opt_string_array(data, field, default=None):
    if not present(data, field):
        return list(default) if default is not None else []
    value = data[field]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % field)
    for item in value:
        if not isinstance(item, str):
            bad("Field '%s' must contain strings." % field)
    return list(value)


def req_criteria(data, field="criteria"):
    """1..6 entries, codes from the declared set and unique, weights summing to
    exactly 100. The order of the array is significant and is preserved."""
    from decimal import Decimal

    if not present(data, field):
        bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % field)
    if len(value) < 1 or len(value) > 6:
        bad("Field '%s' must carry between one and six entries." % field)
    seen = []
    total = Decimal("0")
    normalised = []
    for entry in value:
        if not isinstance(entry, dict):
            bad("Each criterion must be an object.")
        code = entry.get("code")
        if not isinstance(code, str) or code not in CRITERION_CODES:
            bad("Criterion code must be one of %s." % ", ".join(CRITERION_CODES))
        if code in seen:
            bad("Criterion codes must not repeat.")
        seen.append(code)
        weight = entry.get("weight_pct")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            bad("Criterion weight_pct must be a number.")
        if weight < 0:
            bad("Criterion weight_pct must not be negative.")
        total += Decimal(str(weight))
        normalised.append({"code": code, "weight_pct": weight})
    if total != Decimal("100"):
        bad("Criterion weight_pct values must sum to exactly 100.")
    return normalised


def req_tier_bands(data, field="tier_bands"):
    """At least one band, the first with min_participants exactly 1, and
    min_participants strictly increasing across the array."""
    if not present(data, field):
        bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % field)
    if len(value) < 1:
        bad("Field '%s' must carry at least one band." % field)
    bands = []
    previous = None
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            bad("Each tier band must be an object.")
        raw_min = entry.get("min_participants")
        if raw_min is None:
            bad("Each tier band requires min_participants.")
        min_participants = _coerce_int("min_participants", raw_min)
        discount = entry.get("discount_pct")
        if discount is None:
            bad("Each tier band requires discount_pct.")
        if isinstance(discount, bool) or not isinstance(discount, (int, float)):
            bad("Tier band discount_pct must be a number.")
        if discount < 0 or discount > 100:
            bad("Tier band discount_pct must be between 0 and 100.")
        if index == 0 and min_participants != 1:
            bad("The first tier band must have min_participants of exactly 1.")
        if previous is not None and min_participants <= previous:
            bad("Tier band min_participants must be strictly increasing.")
        previous = min_participants
        bands.append({"min_participants": min_participants, "discount_pct": discount})
    return bands
