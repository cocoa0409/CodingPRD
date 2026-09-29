"""Request-body shape validation. Every failure here is ERR_INVALID_REQUEST."""
from decimal import Decimal

import db as store
from errors import bad_request
from services.nums import dec, is_int_like, rhu

MISSING = object()


def present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, min_len=1, max_len=None):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        raise bad_request("Field '%s' is required." % name)
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % name)
    text = value.strip()
    if len(text) < min_len:
        raise bad_request("Field '%s' must not be empty." % name)
    if max_len is not None and len(text) > max_len:
        raise bad_request("Field '%s' is longer than %d characters."
                          % (name, max_len))
    return text


def opt_str(body, name, default=None, max_len=None):
    if not present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % name)
    if max_len is not None and len(value.strip()) > max_len:
        raise bad_request("Field '%s' is too long." % name)
    return value


def req_enum(body, name, allowed):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        raise bad_request("Field '%s' is required." % name)
    if not isinstance(value, str) or value not in allowed:
        raise bad_request(
            "Field '%s' must be one of: %s." % (name, ", ".join(sorted(allowed)))
        )
    return value


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_int(body, name, minimum=None, maximum=None):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        raise bad_request("Field '%s' is required." % name)
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            raise bad_request("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be at most %s." % (name, maximum))
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not present(body, name):
        return default
    return req_int(body, name, minimum, maximum)


def req_number(body, name, places, minimum=None, maximum=None,
               exclusive_min=None):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        raise bad_request("Field '%s' is required." % name)
    if isinstance(value, bool):
        raise bad_request("Field '%s' must be a number." % name)
    if not isinstance(value, (int, float, str, Decimal)):
        raise bad_request("Field '%s' must be a number." % name)
    number = dec(value)
    if number is None:
        raise bad_request("Field '%s' must be a number." % name)
    if minimum is not None and number < minimum:
        raise bad_request("Field '%s' must be at least %s." % (name, minimum))
    if exclusive_min is not None and number <= exclusive_min:
        raise bad_request("Field '%s' must be greater than %s."
                          % (name, exclusive_min))
    if maximum is not None and number > maximum:
        raise bad_request("Field '%s' must be at most %s." % (name, maximum))
    if places is None:
        return number
    return rhu(number, places)


def opt_number(body, name, places, default=None, minimum=None, maximum=None,
               exclusive_min=None):
    if not present(body, name):
        return default
    return req_number(body, name, places, minimum, maximum, exclusive_min)


def req_bool(body, name):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        raise bad_request("Field '%s' is required." % name)
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    if not present(body, name):
        return default
    return req_bool(body, name)


def req_instant(body, name):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        raise bad_request("Field '%s' is required." % name)
    parsed = store.parse_instant(value)
    if parsed is None:
        raise bad_request(
            "Field '%s' must be an ISO 8601 UTC instant." % name)
    return parsed


def opt_instant(body, name, default=None):
    if not present(body, name):
        return default
    return req_instant(body, name)


def req_expected_version(body, name):
    """Mandatory optimistic-concurrency token (PRD 2.9)."""
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        raise bad_request(
            "Field '%s' is required for this operation." % name)
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            return int(value)
        raise bad_request("Field '%s' must be an integer." % name)
    return value


def req_id(body, name):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        raise bad_request("Field '%s' is required." % name)
    if not isinstance(value, str) or value.strip() == "":
        raise bad_request("Field '%s' must be a non-empty identifier." % name)
    return value.strip()


def opt_id(body, name):
    if not present(body, name):
        return None
    return req_id(body, name)


def raw_id(body, name):
    """Read an id for pre-resolution ownership checks without shape errors."""
    value = body.get(name, None)
    if isinstance(value, str) and value.strip() != "":
        return value.strip()
    return None
