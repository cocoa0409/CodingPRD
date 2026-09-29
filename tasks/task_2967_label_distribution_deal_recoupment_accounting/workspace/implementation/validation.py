"""Rank 5 payload-shape validation (PRD sections 2.6 and 2.8).

Money is carried as integer cents; percentages are decimal fractions with four
decimal places.  Values that arrive as JSON strings are accepted only when the
string is an exact literal of the declared form -- for percentages that means
exactly four decimal places, so "0.15" is never a substitute for "0.1500".
"""

import re
from decimal import Decimal, InvalidOperation

from errors import ApiError

_INT_RE = re.compile(r"^[+-]?[0-9]+$")
_PCT_RE = re.compile(r"^[+-]?[0-9]+\.[0-9]{4}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UPC_RE = re.compile(r"^[0-9]{12,14}$")
_DSP_RE = re.compile(r"^[A-Z_]{2,24}$")
_TERRITORY_RE = re.compile(r"^[A-Z]{2}$")

_MISSING = object()


def bad(field, reason):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, reason))


def present(body, field):
    return field in body and body[field] is not None


def _raw(body, field, required):
    if field not in body or body[field] is None:
        if required:
            bad(field, "is required.")
        return _MISSING
    return body[field]


def opt_missing(value):
    return value is _MISSING


def integer(body, field, required=True, minimum=None, maximum=None, default=None):
    value = _raw(body, field, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool):
        bad(field, "must be an integer.")
    if isinstance(value, int):
        number = value
    elif isinstance(value, Decimal):
        if value != value.to_integral_value():
            bad(field, "must be an integer number of cents.")
        number = int(value)
    elif isinstance(value, str) and _INT_RE.match(value.strip()):
        number = int(value.strip())
    else:
        bad(field, "must be an integer.")
    if minimum is not None and number < minimum:
        bad(field, "must be at least %d." % minimum)
    if maximum is not None and number > maximum:
        bad(field, "must be at most %d." % maximum)
    return number


def percentage(body, field, required=True, minimum=None, maximum=None, default=None):
    value = _raw(body, field, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool):
        bad(field, "must be a decimal fraction with four decimal places.")
    if isinstance(value, str):
        text = value.strip()
        if not _PCT_RE.match(text):
            bad(field, "must be a decimal fraction with exactly four decimal places.")
        number = Decimal(text)
    elif isinstance(value, Decimal):
        # PRD 2.6: "A value of 0.15 is not an acceptable substitute for 0.1500:
        # the request-validation rank rejects a percentage that is not written
        # with four decimals" - so the scale must be exactly four, not merely
        # no finer than four.
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int) or exponent != -4:
            bad(field, "must be a decimal fraction with exactly four decimal places.")
        number = value
    elif isinstance(value, int):
        # A bare integer carries no decimals at all.
        bad(field, "must be a decimal fraction with exactly four decimal places.")
    else:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            bad(field, "must be a decimal fraction.")
    if minimum is not None and number < minimum:
        bad(field, "must be at least %s." % minimum)
    if maximum is not None and number > maximum:
        bad(field, "must be at most %s." % maximum)
    return number.quantize(Decimal("0.0001"))


def text(body, field, required=True, min_len=1, max_len=None, default=None):
    value = _raw(body, field, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad(field, "must be a string.")
    if min_len is not None and min_len >= 1 and value.strip() == "":
        bad(field, "must not be blank.")
    length = len(value)
    if min_len is not None and length < min_len:
        bad(field, "must be at least %d characters." % min_len)
    if max_len is not None and length > max_len:
        bad(field, "must be at most %d characters." % max_len)
    return value


def identifier(body, field, required=True, default=None):
    value = _raw(body, field, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value.strip() == "":
        bad(field, "must be a non-blank identifier.")
    return value.strip()


def enum(body, field, allowed, required=True, default=None):
    value = _raw(body, field, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        bad(field, "must be one of %s." % ", ".join(sorted(allowed)))
    return value


def boolean(body, field, required=True, default=None):
    value = _raw(body, field, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    bad(field, "must be a boolean.")


def date_field(body, field, required=True, default=None):
    import db

    value = _raw(body, field, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad(field, "must be an ISO 8601 date.")
    parsed = db.parse_date(value)
    if parsed is None:
        bad(field, "must be an ISO 8601 date (YYYY-MM-DD).")
    return parsed


def instant_field(body, field, required=True, default=None):
    import db

    value = _raw(body, field, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad(field, "must be an ISO 8601 instant.")
    parsed = db.parse_instant(value)
    if parsed is None:
        bad(field, "must be an ISO 8601 instant.")
    return parsed


def email(body, field, required=True):
    value = text(body, field, required=required, min_len=1, max_len=254)
    if value is None:
        return None
    if not _EMAIL_RE.match(value.strip()):
        bad(field, "must be a well-formed email address.")
    return value.strip()


def upc(body, field, required=True):
    value = _raw(body, field, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str) or not _UPC_RE.match(value.strip()):
        bad(field, "must be 12 to 14 ASCII digits.")
    return value.strip()


def dsp_code(body, field, required=True):
    value = _raw(body, field, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str) or not _DSP_RE.match(value.strip()):
        bad(field, "must be 2 to 24 uppercase letters or underscores.")
    return value.strip()


def territory(body, field, required=True):
    value = _raw(body, field, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str) or not _TERRITORY_RE.match(value.strip()):
        bad(field, "must be an ISO 3166-1 alpha-2 code.")
    return value.strip()


def territory_list(body, field, required=True):
    value = _raw(body, field, required)
    if value is _MISSING:
        return None
    if not isinstance(value, list) or len(value) == 0:
        bad(field, "must be a non-empty array of ISO 3166-1 alpha-2 codes.")
    seen = []
    for item in value:
        if not isinstance(item, str) or not _TERRITORY_RE.match(item.strip()):
            bad(field, "must contain only ISO 3166-1 alpha-2 codes.")
        code = item.strip()
        if code in seen:
            bad(field, "must contain distinct codes.")
        seen.append(code)
    return seen


def enum_list(body, field, allowed, required=True):
    value = _raw(body, field, required)
    if value is _MISSING:
        return None
    if not isinstance(value, list) or len(value) == 0:
        bad(field, "must be a non-empty array.")
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad(field, "must contain only %s." % ", ".join(sorted(allowed)))
        if item in seen:
            bad(field, "must contain distinct values.")
        seen.append(item)
    return seen


def must_be_null(body, field):
    if field in body and body[field] is not None:
        bad(field, "must be null for this deal type.")
