"""Request-shape validation.  Every failure here is ERR_INVALID_REQUEST 400,
which is priority 4 on the ladder in PRD section 2.5."""

import re

from flask import request

import timeutil
from errors import ApiError

CODE_RE = re.compile(r"^[A-Z0-9-]{1,32}$")
QUARTER_RE = re.compile(r"^20[0-9]{2}Q[1-4]$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

PERSONAS = ("IT_BUYER", "PRACTITIONER", "EXECUTIVE", "DEVELOPER")
FUNNEL_STAGES = ("AWARENESS", "CONSIDERATION", "DECISION", "RETENTION")
SEARCH_INTENTS = ("INFORMATIONAL", "COMMERCIAL", "TRANSACTIONAL", "NAVIGATIONAL")
CHANNELS = ("OWNED", "EMAIL", "SOCIAL")
ASSET_TYPES = ("STOCK", "ORIGINAL", "TALENT")
CLAIM_TYPES = ("PERFORMANCE", "COMPARISON", "REGULATED")
EVIDENCE_SOURCE_TYPES = ("INTERNAL_STUDY", "THIRD_PARTY_TEST", "CUSTOMER_DATA",
                         "REGULATORY_FILING")
TOUCH_POSITIONS = ("FIRST", "MIDDLE", "LAST")
GATE_TYPES = ("SME", "LEGAL", "BRAND", "ACCESSIBILITY")
GATE_DECISIONS = ("APPROVED", "CHANGES_REQUESTED", "WAIVED")
AUDIT_TYPES = ("DECAY", "ACCURACY")
ACCURACY_FINDINGS = ("UNVERIFIED", "VERIFIED", "INACCURATE")
CLAIM_DECISIONS = ("SUBSTANTIATED", "REJECTED")
EXPERT_STATUSES = ("AVAILABLE", "ON_LEAVE")


def fail(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    payload = request.get_json(silent=True, force=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("request body must be a JSON object")
    return payload


def _absent(data, key):
    return key not in data or data[key] is None


def v_str(data, key, required=True, minlen=1, maxlen=None, pattern=None,
          lowercase=False, default=None):
    if _absent(data, key):
        if required:
            fail(key + " is required")
        return default
    value = data[key]
    if not isinstance(value, str):
        fail(key + " must be a string")
    if len(value) < minlen:
        fail(key + " must be at least %d characters" % minlen)
    if maxlen is not None and len(value) > maxlen:
        fail(key + " must be at most %d characters" % maxlen)
    if lowercase and value != value.lower():
        fail(key + " must be lowercase")
    if pattern is not None and not pattern.match(value):
        fail(key + " has an invalid format")
    return value


def v_int(data, key, required=True, minimum=None, maximum=None, default=None):
    if _absent(data, key):
        if required:
            fail(key + " is required")
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail(key + " must be an integer")
    if minimum is not None and value < minimum:
        fail(key + " must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        fail(key + " must be at most %d" % maximum)
    return value


def v_bool(data, key, required=False, default=False):
    if _absent(data, key):
        if required:
            fail(key + " is required")
        return default
    value = data[key]
    if not isinstance(value, bool):
        fail(key + " must be a boolean")
    return value


def v_enum(data, key, allowed, required=True, default=None):
    if _absent(data, key):
        if required:
            fail(key + " is required")
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        fail(key + " must be one of " + ", ".join(allowed))
    return value


def v_instant(data, key, required=True, default=None):
    if _absent(data, key):
        if required:
            fail(key + " is required")
        return default
    value = data[key]
    if not isinstance(value, str):
        fail(key + " must be a string")
    parsed = timeutil.parse_instant(value)
    if parsed is None:
        fail(key + " must be a parseable ISO 8601 UTC instant")
    return parsed


def v_date(data, key, required=True, default=None):
    if _absent(data, key):
        if required:
            fail(key + " is required")
        return default
    value = data[key]
    if not isinstance(value, str):
        fail(key + " must be a string")
    parsed = timeutil.parse_date(value)
    if parsed is None:
        fail(key + " must be a YYYY-MM-DD calendar date")
    return parsed


def v_str_list(data, key, required=True, min_items=0, max_items=None,
               item_min=1, item_max=None, lowercase=False, pattern=None,
               default=None):
    if _absent(data, key):
        if required:
            fail(key + " is required")
        return list(default) if default is not None else default
    value = data[key]
    if not isinstance(value, list):
        fail(key + " must be an array")
    if len(value) < min_items:
        fail(key + " must contain at least %d entries" % min_items)
    if max_items is not None and len(value) > max_items:
        fail(key + " must contain at most %d entries" % max_items)
    for entry in value:
        if not isinstance(entry, str):
            fail(key + " entries must be strings")
        if len(entry) < item_min:
            fail(key + " entries must be at least %d characters" % item_min)
        if item_max is not None and len(entry) > item_max:
            fail(key + " entries must be at most %d characters" % item_max)
        if lowercase and entry != entry.lower():
            fail(key + " entries must be lowercase")
        if pattern is not None and not pattern.match(entry):
            fail(key + " entries have an invalid format")
    return list(value)


def v_enum_list(data, key, allowed, required=True, min_items=1, max_items=None,
                distinct=True, default=None):
    if _absent(data, key):
        if required:
            fail(key + " is required")
        return list(default) if default is not None else default
    value = data[key]
    if not isinstance(value, list):
        fail(key + " must be an array")
    if len(value) < min_items:
        fail(key + " must contain at least %d entries" % min_items)
    if max_items is not None and len(value) > max_items:
        fail(key + " must contain at most %d entries" % max_items)
    for entry in value:
        if not isinstance(entry, str) or entry not in allowed:
            fail(key + " entries must be one of " + ", ".join(allowed))
    if distinct and len(set(value)) != len(value):
        fail(key + " entries must be distinct")
    return list(value)
