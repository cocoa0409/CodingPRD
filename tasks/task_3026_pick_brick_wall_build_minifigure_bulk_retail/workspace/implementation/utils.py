"""Small helpers shared by the route modules."""

from datetime import datetime

from db import format_iso
from errors import fail


def out(record):
    """Serialise a record: datetimes become ISO 8601 UTC with three fractional digits."""
    if isinstance(record, list):
        return [out(item) for item in record]
    if not isinstance(record, dict):
        return record
    serialised = {}
    for key, value in record.items():
        if key.startswith("_"):
            # private bookkeeping the server keeps beside a record is never
            # part of the declared resource shape
            continue
        if isinstance(value, datetime):
            serialised[key] = format_iso(value)
        elif isinstance(value, dict):
            serialised[key] = out(value)
        else:
            serialised[key] = value
    return serialised


def body():
    from flask import request
    return request.get_json(silent=True) or {}


def require_fields(payload, *names):
    """Required-field enforcement runs at the authentication rung (priority 1)."""
    missing = [n for n in names if payload.get(n) is None or payload.get(n) == ""]
    if missing:
        fail("ERR_CONSTRAINT_VIOLATION",
             "Missing required field(s): %s." % ", ".join(missing))


def require_enum(payload, name, allowed, default=None):
    value = payload.get(name, default)
    if value not in allowed:
        fail("ERR_CONSTRAINT_VIOLATION",
             "Field %s must be one of %s." % (name, ", ".join(allowed)))
    return value


def list_params():
    from flask import request
    return request.args.to_dict()


def paginate_list(items, params):
    from response import paginate
    return paginate(items, params)


def matches(record, params, *fields):
    for field in fields:
        wanted = params.get(field)
        if wanted not in (None, ""):
            if str(record.get(field)) != str(wanted):
                return False
    return True