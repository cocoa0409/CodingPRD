"""Request-shape validation. Every failure raises ERR_INVALID_REQUEST (PRD 2.6 step 6)."""

import clock
from errors import ApiError, invalid


def _absent(body, name):
    """A field that is missing, or present as null, counts as not supplied."""
    return name not in body or body[name] is None


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def present(body, name):
    return name in body and body[name] is not None


def field_str(body, name, required=True, default=None, min_len=None, max_len=None):
    if _absent(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        raise invalid("Field '%s' is shorter than the permitted minimum." % name)
    if max_len is not None and len(value) > max_len:
        raise invalid("Field '%s' is longer than the permitted maximum." % name)
    return value


def field_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if _absent(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    value = body[name]
    if not is_int(value):
        raise invalid("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' is below the permitted minimum." % name)
    if maximum is not None and value > maximum:
        raise invalid("Field '%s' is above the permitted maximum." % name)
    return value


def field_number(body, name, required=True, default=None, greater_than=None, minimum=None):
    if _absent(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    value = body[name]
    if not is_number(value):
        raise invalid("Field '%s' must be a number." % name)
    if greater_than is not None and not value > greater_than:
        raise invalid("Field '%s' must be greater than %s." % (name, greater_than))
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' is below the permitted minimum." % name)
    return value


def field_enum(body, name, allowed, required=True, default=None):
    if _absent(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise invalid("Field '%s' is not one of the permitted values." % name)
    return value


def field_date(body, name, required=True, default=None):
    if _absent(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    try:
        return clock.parse_date(body[name])
    except ValueError:
        raise invalid("Field '%s' must be a YYYY-MM-DD calendar date." % name)


def field_instant(body, name, required=True, default=None):
    if _absent(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    try:
        return clock.parse_instant(body[name])
    except ValueError:
        raise invalid("Field '%s' must be an ISO 8601 UTC instant." % name)


def field_id(body, name, required=True):
    """A foreign-key reference: must be a string when supplied."""
    if _absent(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return None
    value = body[name]
    if not isinstance(value, str) or value == "":
        raise invalid("Field '%s' must be an identifier string." % name)
    return value


def raw_id(body, name):
    """Read a foreign key for the existence phase without shape enforcement."""
    value = body.get(name)
    if isinstance(value, str) and value != "":
        return value
    return None


def require_order(first, second, message="Date range is inverted."):
    if first is not None and second is not None and second < first:
        raise invalid(message)
