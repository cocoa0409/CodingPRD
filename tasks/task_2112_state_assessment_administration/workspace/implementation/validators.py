"""Check 5 — body well-formedness. Every failure is ERR_INVALID_REQUEST (400)."""

import re

from errors import api_error
from timeutil import parse_iso

_MISSING = object()


def _fail(message):
    raise api_error("ERR_INVALID_REQUEST", message)


def _present(body, field):
    value = body.get(field, _MISSING)
    if value is _MISSING or value is None:
        return _MISSING
    return value


def string_field(body, field, required=True, min_length=None, max_length=None, pattern=None, default=None):
    value = _present(body, field)
    if value is _MISSING:
        if required:
            _fail("%s is required." % field)
        return default
    if not isinstance(value, str):
        _fail("%s must be a string." % field)
    if min_length is not None and len(value) < min_length:
        _fail("%s must be at least %d characters." % (field, min_length))
    if max_length is not None and len(value) > max_length:
        _fail("%s must be at most %d characters." % (field, max_length))
    if pattern is not None and re.fullmatch(pattern, value) is None:
        _fail("%s does not match its declared pattern." % field)
    return value


def enum_field(body, field, allowed, required=True, default=None):
    value = _present(body, field)
    if value is _MISSING:
        if required:
            _fail("%s is required." % field)
        return default
    if not isinstance(value, str) or value not in allowed:
        _fail("%s must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value


def integer_field(body, field, required=True, minimum=None, maximum=None, default=None):
    value = _present(body, field)
    if value is _MISSING:
        if required:
            _fail("%s is required." % field)
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("%s must be an integer." % field)
    if minimum is not None and value < minimum:
        _fail("%s must be at least %d." % (field, minimum))
    if maximum is not None and value > maximum:
        _fail("%s must be at most %d." % (field, maximum))
    return value


def number_field(body, field, required=True, minimum=None, maximum=None, default=None):
    value = _present(body, field)
    if value is _MISSING:
        if required:
            _fail("%s is required." % field)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("%s must be a number." % field)
    number = float(value)
    if minimum is not None and number < minimum:
        _fail("%s must be at least %s." % (field, minimum))
    if maximum is not None and number > maximum:
        _fail("%s must be at most %s." % (field, maximum))
    return number


def datetime_field(body, field, required=True, default=None):
    value = _present(body, field)
    if value is _MISSING:
        if required:
            _fail("%s is required." % field)
        return default
    parsed = parse_iso(value)
    if parsed is None:
        _fail("%s must be a parseable ISO 8601 UTC instant." % field)
    return parsed


def identifier_field(body, field, required=True, default=None):
    value = _present(body, field)
    if value is _MISSING:
        if required:
            _fail("%s is required." % field)
        return default
    if not isinstance(value, str) or not value.strip():
        _fail("%s must be a non-empty string." % field)
    return value


def string_list_field(body, field, allowed, max_entries=None, required=True):
    value = _present(body, field)
    if value is _MISSING:
        if required:
            _fail("%s is required." % field)
        return []
    if not isinstance(value, list):
        _fail("%s must be a list." % field)
    if max_entries is not None and len(value) > max_entries:
        _fail("%s may hold at most %d entries." % (field, max_entries))
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            _fail("%s contains an uncatalogued entry." % field)
        if item in seen:
            _fail("%s may not repeat an entry." % field)
        seen.add(item)
    return list(value)


def optional_text(body, field, max_length=None):
    value = _present(body, field)
    if value is _MISSING:
        return None
    if not isinstance(value, str):
        _fail("%s must be a string." % field)
    if max_length is not None and len(value) > max_length:
        _fail("%s must be at most %d characters." % (field, max_length))
    return value


def nullable_identifier(body, field):
    """An optional foreign key: absent or explicit null both read as None."""
    if field not in body or body.get(field) is None:
        return None
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        _fail("%s must be a non-empty string when supplied." % field)
    return value


def nullable_string(body, field, max_length=None):
    """An optional free-text field that may legitimately be sent as null."""
    if field not in body or body.get(field) is None:
        return None
    value = body.get(field)
    if not isinstance(value, str):
        _fail("%s must be a string when supplied." % field)
    if max_length is not None and len(value) > max_length:
        _fail("%s must be at most %d characters." % (field, max_length))
    return value
