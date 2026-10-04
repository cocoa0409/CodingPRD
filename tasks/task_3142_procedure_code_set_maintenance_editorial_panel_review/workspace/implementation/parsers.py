"""Request-body helpers.

Parsing is deliberately lenient about *shape* and strict about *values*: an
absent optional field falls back to the default the scaffold declares, while a
missing instant that a business rule depends on is left as None so the rule
itself raises its own catalogued error (for example a posting whose window
cannot be measured reports ERR_COMMENT_PERIOD_TOO_SHORT rather than an
invented parser error).
"""

from datetime import datetime, timezone

from flask import request

from errors import ERR_INVALID_STATE, ApiError
from money import dec


def body():
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def boolean(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y")
    return bool(value)


def integer(value, default=0):
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def number(value, default=0):
    if value is None or value == "":
        return dec(default)
    return dec(value)


def text(value, default=""):
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def text_or_none(value):
    if value is None or value == "":
        return None
    return text(value)


def id_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def require(value, message="malformed request"):
    """A body field whose absence makes the request unprocessable.

    The catalogue carries no dedicated code for a missing non-key field; the
    closest catalogued condition is that the target resource is not in a state
    that admits the operation, which is what a request missing its determinative
    input amounts to.
    """
    if value is None or value == "":
        raise ApiError(ERR_INVALID_STATE, message)
    return value


def enum_or_invalid(value, allowed, message):
    if value not in allowed:
        raise ApiError(ERR_INVALID_STATE, message)
    return value