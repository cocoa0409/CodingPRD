"""Request-body shape validation (ladder rule 4 -> ERR_INVALID_REQUEST)."""
import re

import util
from errors import invalid

UPPER_ALNUM_RE = re.compile(r"^[A-Z0-9]+$")
DIGITS_RE = re.compile(r"^[0-9]+$")
UPPER_ALPHA_RE = re.compile(r"^[A-Z]+$")
HEX_UPPER_RE = re.compile(r"^[0-9A-F]+$")
E164_PORTED_RE = re.compile(r"^\+1[0-9]{10}$")
E164_DEST_RE = re.compile(r"^\+[0-9]{7,15}$")
COUNTRY_CODE_RE = re.compile(r"^[0-9]{1,3}$")


def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, min_len=None, max_len=None, pattern=None, exact_len=None):
    if not _present(body, name):
        raise invalid(name)
    value = body[name]
    if not isinstance(value, str):
        raise invalid(name)
    return _check_str(name, value, min_len, max_len, pattern, exact_len)


def opt_str(body, name, min_len=None, max_len=None, pattern=None, exact_len=None,
            default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        raise invalid(name)
    return _check_str(name, value, min_len, max_len, pattern, exact_len)


def _check_str(name, value, min_len, max_len, pattern, exact_len):
    if exact_len is not None and len(value) != exact_len:
        raise invalid(name)
    if min_len is not None and len(value) < min_len:
        raise invalid(name)
    if max_len is not None and len(value) > max_len:
        raise invalid(name)
    if pattern is not None and not pattern.match(value):
        raise invalid(name)
    return value


def req_free_text(body, name):
    if not _present(body, name):
        raise invalid(name)
    value = body[name]
    if not isinstance(value, str):
        raise invalid(name)
    return value


def opt_free_text(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        raise invalid(name)
    return value


def req_enum(body, name, allowed):
    if not _present(body, name):
        raise invalid(name)
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise invalid(name)
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise invalid(name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        raise invalid(name)
    return _check_int(name, body[name], minimum, maximum)


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if not _present(body, name):
        return default
    return _check_int(name, body[name], minimum, maximum)


def _check_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid(name)
    if minimum is not None and value < minimum:
        raise invalid(name)
    if maximum is not None and value > maximum:
        raise invalid(name)
    return value


def req_bool(body, name):
    if not _present(body, name):
        raise invalid(name)
    value = body[name]
    if not isinstance(value, bool):
        raise invalid(name)
    return value


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise invalid(name)
    return value


def req_instant(body, name):
    if not _present(body, name):
        raise invalid(name)
    parsed = util.parse_instant(body[name])
    if parsed is None:
        raise invalid(name)
    return parsed


def req_period(body, name):
    if not _present(body, name):
        raise invalid(name)
    value = body[name]
    parsed = util.parse_period(value) if isinstance(value, str) else None
    if parsed is None:
        raise invalid(name)
    return value


def req_id(body, name):
    """A reference to another resource: a non-empty string."""
    if not _present(body, name):
        raise invalid(name)
    value = body[name]
    if not isinstance(value, str) or value == "":
        raise invalid(name)
    return value


def opt_id(body, name):
    if not _present(body, name):
        return None
    value = body[name]
    if not isinstance(value, str) or value == "":
        raise invalid(name)
    return value


def req_ported_numbers(body, name):
    if not _present(body, name):
        raise invalid(name)
    value = body[name]
    if not isinstance(value, list) or len(value) < 1 or len(value) > 5:
        raise invalid(name)
    seen = set()
    for item in value:
        if not isinstance(item, str) or not E164_PORTED_RE.match(item):
            raise invalid(name)
        if item in seen:
            raise invalid(name)
        seen.add(item)
    return list(value)


def peek_str(body, name):
    """Read a body field for the pre-body ownership comparison without validating it."""
    if not isinstance(body, dict):
        return None
    value = body.get(name)
    return value if isinstance(value, str) and value != "" else None
