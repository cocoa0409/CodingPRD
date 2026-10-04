"""Request-shape validation helpers (validation stage 5: ERR_VALIDATION 400)."""
import re
from flask import request

from errors import raise_err, ERR_VALIDATION
from store import INDUSTRIES, SIZE_CLASSES, parse_instant

QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
PROGRAM_CODE_RE = re.compile(r"^[A-Z0-9]+$")


def get_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise_err(ERR_VALIDATION, "request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise_err(ERR_VALIDATION, f"missing required field '{name}'")
    return data[name]


def req_str(data, name):
    value = req_field(data, name)
    if not isinstance(value, str) or not value.strip():
        raise_err(ERR_VALIDATION, f"field '{name}' must be a non-empty string")
    return value


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def req_int(data, name, minimum=None, maximum=None):
    value = req_field(data, name)
    if not is_int(value):
        raise_err(ERR_VALIDATION, f"field '{name}' must be an integer")
    if minimum is not None and value < minimum:
        raise_err(ERR_VALIDATION, f"field '{name}' must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise_err(ERR_VALIDATION, f"field '{name}' must be <= {maximum}")
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        return default
    return req_int(data, name, minimum=minimum, maximum=maximum)


def req_enum(data, name, allowed):
    value = req_field(data, name)
    if value not in allowed:
        raise_err(
            ERR_VALIDATION,
            f"field '{name}' must be one of {', '.join(allowed)}",
        )
    return value


def req_industry(data, name="industry_code"):
    return req_enum(data, name, INDUSTRIES)


def req_size(data, name="size_class"):
    return req_enum(data, name, SIZE_CLASSES)


def parse_quarter(value):
    """'YYYY-Qn' -> (year, n); invalid -> ERR_VALIDATION."""
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, "reference_quarter must be a string 'YYYY-Qn'")
    m = QUARTER_RE.match(value.strip())
    if not m:
        raise_err(ERR_VALIDATION, "reference_quarter must have format YYYY-Qn")
    return int(m.group(1)), int(m.group(2))


def parse_month_field(data, name):
    """'YYYY-MM' -> (year, month); invalid -> ERR_VALIDATION."""
    value = req_field(data, name)
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, f"field '{name}' must be a string 'YYYY-MM'")
    m = MONTH_RE.match(value.strip())
    if not m:
        raise_err(ERR_VALIDATION, f"field '{name}' must have format YYYY-MM")
    year, month = int(m.group(1)), int(m.group(2))
    if month < 1 or month > 12:
        raise_err(ERR_VALIDATION, f"field '{name}' month must be in 01..12")
    return year, month


def req_instant(data, name):
    value = req_field(data, name)
    dt = parse_instant(value)
    if dt is None:
        raise_err(ERR_VALIDATION, f"field '{name}' must be an ISO 8601 instant")
    return dt


def quarter_next(q):
    year, n = q
    return (year + 1, 1) if n == 4 else (year, n + 1)


def month_prev(mref):
    year, month = mref
    return (year - 1, 12) if month == 1 else (year, month - 1)


def month_str(mref):
    return f"{mref[0]:04d}-{mref[1]:02d}"
