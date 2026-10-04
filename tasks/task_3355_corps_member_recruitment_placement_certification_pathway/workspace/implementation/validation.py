"""Tier-3 request-body validation: required fields, enum members, numeric ranges.

Every breach of this tier is ERR_INVALID_REQUEST (HTTP 400).
"""

import re

from errors import ApiError

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")

SUBJECT_AREAS = ("MATH", "SCIENCE", "ENGLISH", "HISTORY", "SPED", "BILINGUAL")
GRADE_BANDS = ("ELEMENTARY", "MIDDLE", "HIGH")
CAMPUS_TIERS = ("PRIORITY", "STANDARD", "DEVELOPING")
CERTIFICATION_TRACKS = ("STANDARD", "ALTERNATIVE_EMERGENCY", "PROVISIONAL")
MILESTONE_TYPES = ("COURSEWORK", "PRACTICUM", "EXAM", "ORIENTATION")
RECORD_TYPES = ("COACHING", "EVALUATION")
VERIFY_OUTCOMES = ("VERIFY", "REJECT")
DECISIONS = ("SELECT", "REJECT")
AGREEMENT_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def has(body, name):
    return name in body and body[name] is not None


def require(body, *names):
    for name in names:
        if not has(body, name):
            bad("Field '%s' is required." % name)


def enum(body, name, allowed, required=True):
    if not has(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return None
    value = body[name]
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def integer(body, name, minimum=None, maximum=None, required=True):
    if not has(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return None
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        else:
            bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    return value


def number(body, name, minimum=None, maximum=None, required=True):
    if not has(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return None
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    value = float(value)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    return value


def boolean(body, name, required=True):
    if not has(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return None
    value = body[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def string(body, name, required=True, allow_empty=False):
    if not has(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return None
    value = body[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if not allow_empty and not value.strip():
        bad("Field '%s' must not be empty." % name)
    return value


def state_code(body, name):
    value = string(body, name)
    if not STATE_CODE_RE.match(value):
        bad("Field '%s' must be exactly two uppercase letters." % name)
    return value


def subject_needs(body, name):
    if not has(body, name):
        bad("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, list) or not value:
        bad("Field '%s' must be a non-empty selection of subject areas." % name)
    for item in value:
        if item not in SUBJECT_AREAS:
            bad("Field '%s' contains an undeclared subject area." % name)
    return list(value)


def timestamp(body, name, required=True):
    from util import parse_dt

    if not has(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return None
    try:
        return parse_dt(body[name])
    except ValueError:
        bad("Field '%s' must be an ISO 8601 timestamp." % name)
