"""Payload shape screening (validation ladder rung 6, PRD 2.7).

Every breach raises ERR_INVALID_REQUEST (HTTP 400).
"""

from flask import request

import errors
import util

_MISSING = object()


def _bad(message):
    raise errors.ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Request body as a dict; a body-less request is an empty payload."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        _bad("Request body is not valid JSON.")
    if not isinstance(payload, dict):
        _bad("Request body must be a JSON object.")
    return payload


def _raw(payload, name, default):
    if name not in payload:
        return _MISSING if default is _MISSING else default
    value = payload[name]
    if value is None and default is not _MISSING:
        return default
    return value


def get_string(payload, name, required=True, default=_MISSING, min_len=None, max_len=None):
    value = _raw(payload, name, default)
    if value is _MISSING:
        if required:
            _bad("%s is required." % name)
        return None
    if value is None:
        if required:
            _bad("%s is required." % name)
        return None
    if not isinstance(value, str):
        _bad("%s must be a string." % name)
    if min_len is not None and len(value) < min_len:
        _bad("%s is shorter than %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("%s is longer than %d characters." % (name, max_len))
    return value


def get_int(payload, name, required=True, default=_MISSING, minimum=None, maximum=None):
    value = _raw(payload, name, default)
    if value is _MISSING or value is None:
        if required:
            _bad("%s is required." % name)
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        _bad("%s must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("%s must be <= %d." % (name, maximum))
    return value


def get_enum(payload, name, allowed, required=True, default=_MISSING):
    value = _raw(payload, name, default)
    if value is _MISSING or value is None:
        if required:
            _bad("%s is required." % name)
        return None
    if not isinstance(value, str) or value not in allowed:
        _bad("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def get_instant(payload, name, required=True, default=_MISSING):
    value = _raw(payload, name, default)
    if value is _MISSING or value is None:
        if required:
            _bad("%s is required." % name)
        return None
    parsed = util.parse_instant(value)
    if parsed is None:
        _bad("%s must be an ISO 8601 UTC instant." % name)
    return parsed


def get_bool(payload, name, required=False, default=_MISSING):
    value = _raw(payload, name, default)
    if value is _MISSING or value is None:
        if required:
            _bad("%s is required." % name)
        return None
    if not isinstance(value, bool):
        _bad("%s must be a boolean." % name)
    return value


def get_string_array(payload, name, required=True, default=_MISSING, allowed=None):
    value = _raw(payload, name, default)
    if value is _MISSING or value is None:
        if required:
            _bad("%s is required." % name)
        return None
    if not isinstance(value, list):
        _bad("%s must be an array." % name)
    for item in value:
        if not isinstance(item, str):
            _bad("%s must be an array of strings." % name)
        if allowed is not None and item not in allowed:
            _bad("%s contains an undeclared member." % name)
    return list(value)


def get_tier_schedule(payload, name="tier_schedule"):
    """Ordered stair-step tiers, strictly ascending in tier_index and threshold_bps."""
    value = _raw(payload, name, [])
    if value is None:
        return []
    if not isinstance(value, list):
        _bad("tier_schedule must be an array.")
    tiers = []
    for element in value:
        if not isinstance(element, dict):
            _bad("tier_schedule elements must be objects.")
        tier_index = get_int(element, "tier_index", required=True, minimum=1)
        threshold_bps = get_int(element, "threshold_bps", required=True, minimum=0)
        bonus = get_int(element, "per_unit_bonus_cents", required=True, minimum=0)
        tiers.append(
            {
                "tier_index": tier_index,
                "threshold_bps": threshold_bps,
                "per_unit_bonus_cents": bonus,
            }
        )
    for previous, current in zip(tiers, tiers[1:]):
        if current["tier_index"] <= previous["tier_index"]:
            _bad("tier_schedule must be strictly ascending in tier_index.")
        if current["threshold_bps"] <= previous["threshold_bps"]:
            _bad("tier_schedule must be strictly ascending in threshold_bps.")
    return tiers


def get_month(payload, name="period_month", required=True):
    value = _raw(payload, name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            _bad("%s is required." % name)
        return None
    if not util.is_month_string(value):
        _bad("%s must be in YYYY-MM form." % name)
    return value


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        _bad("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    _bad("%s must be a boolean." % name)


def query_string(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
