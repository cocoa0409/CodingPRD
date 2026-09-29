"""Request-shape validation (PRD 2.5 step 3) -- every failure is ERR_INVALID_REQUEST."""
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PRODUCT_CATEGORIES = ["BEVERAGE", "FOOD_DRY", "HOUSEHOLD_CHEM", "MEDICAL_DEVICE", "PERSONAL_CARE"]
MATERIAL_TYPES = ["PLASTIC", "PAPER", "GLASS", "METAL"]
RECYCLABILITY_CLASSES = ["READILY_RECYCLABLE", "LIMITED", "NOT_RECYCLABLE"]
OBLIGATION_BASES = ["ENTITY_LEVEL", "GROUP_LEVEL"]
ECO_MOD_POLICIES = ["BONUS_MALUS", "DISCOUNT_ONLY"]
FEE_ROUNDING_ORDERS = ["PER_LINE_THEN_SUM", "SUM_THEN_ROUND"]
PRODUCER_STATUSES = ["DRAFT", "OBLIGATION_DETERMINED"]
OBLIGATED_PARTY_ROLES = ["UNDETERMINED", "BRAND_OWNER", "IMPORTER", "DOMESTIC_LICENSOR", "NOT_OBLIGATED"]
SKU_STATUSES = ["DRAFT", "ACTIVE"]
FEE_SCHEDULE_STATUSES = ["DRAFT", "PUBLISHED", "SUPERSEDED"]
REGISTRATION_STATUSES = ["DRAFT", "SUBMITTED", "ACTIVE", "SUSPENDED", "REJECTED", "WITHDRAWN"]
EXEMPTION_STATUSES = ["UNDETERMINED", "OBLIGATED", "EXEMPT_SMALL_PRODUCER", "EXEMPT_CATEGORY"]
COMPLIANCE_POSTURES = ["UNDETERMINED", "COMPLIANT", "AT_RISK", "DELINQUENT"]
MEMBERSHIP_STATUSES = ["PENDING", "ACTIVE", "PROBATION", "REJECTED", "TERMINATED"]
PAYMENT_STATUSES = ["OUTSTANDING", "PAID"]
SUBMISSION_STATUSES = [
    "DRAFT", "BLOCKED", "SUBMITTED", "UNDER_VERIFICATION", "VERIFIED",
    "CORRECTION_REQUIRED", "FINALIZED", "REJECTED",
]
FEE_STATUSES = ["UNASSESSED", "PROVISIONAL", "FINAL", "INVOICED", "VOIDED"]
ENGAGEMENT_STATUSES = ["ASSIGNED", "IN_PROGRESS", "OPINION_ISSUED"]
OPINIONS = ["UNQUALIFIED", "QUALIFIED", "ADVERSE"]
INVOICE_STATUSES = ["ISSUED", "VOID"]
UNITS_BASES = ["BASELINE_UNITS", "PROJECTED_UNITS"]


def body(required=True):
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            fail("ERR_INVALID_REQUEST", "A JSON request body is required.")
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None or not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return parsed


def _present(data, name):
    if name not in data or data[name] is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)


def req_str(data, name, allow_empty=False):
    _present(data, name)
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % name)
    return value


def opt_str(data, name, allow_empty=True, default=None):
    if name not in data or data[name] is None:
        return default
    return req_str(data, name, allow_empty=allow_empty)


def req_bool(data, name):
    _present(data, name)
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def req_int(data, name, minimum=None, maximum=None):
    _present(data, name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, maximum))
    return value


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if name not in data or data[name] is None:
        return default
    return req_int(data, name, minimum, maximum)


def req_decimal(data, name, places, minimum=None, exclusive_min=None):
    _present(data, name)
    return _to_decimal(data[name], name, places, minimum, exclusive_min)


def opt_decimal(data, name, places, minimum=None, exclusive_min=None, default=None):
    if name not in data or data[name] is None:
        return default
    return _to_decimal(data[name], name, places, minimum, exclusive_min)


def _to_decimal(value, name, places, minimum=None, exclusive_min=None):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    if not dec.is_finite():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a finite number." % name)
    exponent = dec.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -places:
        fail(
            "ERR_INVALID_REQUEST",
            "Field '%s' carries more than %d decimal places." % (name, places),
        )
    if minimum is not None and dec < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be > %s." % (name, exclusive_min))
    return dec


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    return req_enum(data, name, allowed)


def req_date(data, name):
    value = req_str(data, name)
    return parse_date(value, name)


def opt_date(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_date(data, name)


def parse_date(value, name):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD date." % name)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a valid calendar date." % name)


def req_instant(data, name):
    value = req_str(data, name)
    return parse_instant(value, name)


def parse_instant(value, name):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a parseable ISO 8601 instant." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_list(data, name, allow_empty=True):
    _present(data, name)
    value = data[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
    if not allow_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % name)
    return value
