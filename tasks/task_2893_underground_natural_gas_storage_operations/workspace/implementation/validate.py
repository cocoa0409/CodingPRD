"""Schema validation (rung 3), pagination bounds, filters, and existence rungs 4 and 5."""
from decimal import Decimal, InvalidOperation

from flask import request

import config
import store
from errors import ApiError, bad_request, not_found
from utils import D, parse_date_string, parse_instant

_MISSING = object()


# ---------------------------------------------------------------- body access
def json_body(required=True):
    """Parse the request body as a JSON object; malformed bodies are rung-3 failures."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            return {}
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object.")
    return body


def reject_unknown(body, allowed):
    # Extra keys are tolerated; only declared keys are read.
    return body


# ---------------------------------------------------------------- scalar readers
def _present(body, key):
    return key in body and body[key] is not None


def field_str(body, key, required=True, min_len=None, max_len=None, default=None,
              allow_empty=True):
    if not _present(body, key):
        if required:
            raise bad_request("Field %s is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        raise bad_request("Field %s must be a string." % key)
    if not allow_empty and value == "":
        raise bad_request("Field %s must be non-empty." % key)
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field %s must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field %s must be at most %d characters." % (key, max_len))
    return value


def field_enum(body, key, allowed, required=True, default=None):
    if not _present(body, key):
        if required:
            raise bad_request("Field %s is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("Field %s must be one of %s." % (key, ", ".join(allowed)))
    return value


def field_int(body, key, required=True, default=None, minimum=None, maximum=None,
              exclusive_minimum=None):
    if not _present(body, key):
        if required:
            raise bad_request("Field %s is required." % key)
        return default
    value = body[key]
    if isinstance(value, bool):
        raise bad_request("Field %s must be an integer." % key)
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and float(value).is_integer():
        number = int(value)
    else:
        raise bad_request("Field %s must be an integer." % key)
    _range_check(key, D(number), minimum, maximum, exclusive_minimum)
    return number


def field_number(body, key, required=True, default=None, minimum=None, maximum=None,
                 exclusive_minimum=None):
    if not _present(body, key):
        if required:
            raise bad_request("Field %s is required." % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field %s must be a number." % key)
    try:
        number = D(value)
    except (InvalidOperation, ValueError):
        raise bad_request("Field %s must be a number." % key)
    if not number.is_finite():
        raise bad_request("Field %s must be a finite number." % key)
    _range_check(key, number, minimum, maximum, exclusive_minimum)
    return number


def _range_check(key, number, minimum, maximum, exclusive_minimum):
    if exclusive_minimum is not None and number <= D(exclusive_minimum):
        raise bad_request("Field %s must be greater than %s." % (key, exclusive_minimum))
    if minimum is not None and number < D(minimum):
        raise bad_request("Field %s must be at least %s." % (key, minimum))
    if maximum is not None and number > D(maximum):
        raise bad_request("Field %s must be at most %s." % (key, maximum))


def field_date(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            raise bad_request("Field %s is required." % key)
        return default
    try:
        return parse_date_string(body[key])
    except ValueError:
        raise bad_request("Field %s must be a YYYY-MM-DD date." % key)


def field_instant(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            raise bad_request("Field %s is required." % key)
        return default
    try:
        return parse_instant(body[key])
    except ValueError:
        raise bad_request("Field %s must be an ISO-8601 UTC instant." % key)


def field_id(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            raise bad_request("Field %s is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value == "":
        raise bad_request("Field %s must be a non-empty string identifier." % key)
    return value


# ---------------------------------------------------------------- pagination
def pagination():
    """limit defaults to 10 within [1, 100]; offset defaults to 0 (PRD 2.3)."""
    limit = _query_int("limit", config.LIMIT_DEFAULT)
    offset = _query_int("offset", config.OFFSET_DEFAULT)
    if limit < config.LIMIT_MIN or limit > config.LIMIT_MAX:
        raise bad_request("limit must be between %d and %d." % (config.LIMIT_MIN, config.LIMIT_MAX))
    if offset < 0:
        raise bad_request("offset must not be negative.")
    return limit, offset


def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        if raw.strip() != raw:
            raise ValueError
        return int(raw)
    except (TypeError, ValueError):
        raise bad_request("%s must be an integer." % name)


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise bad_request("%s must be one of %s." % (name, ", ".join(allowed)))
    return raw


def query_date(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        parse_date_string(raw)
    except ValueError:
        raise bad_request("%s must be a YYYY-MM-DD date." % name)
    return raw


def query_id(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def paginate(rows, limit, offset):
    """created_at ascending, then limit/offset (PRD 2.3)."""
    ordered = store.sorted_rows(rows)
    total = len(ordered)
    return ordered[offset:offset + limit], total


# ---------------------------------------------------------------- existence rungs
def resolve_path(collection_name, record_id):
    """Rung 4: a path identifier resolves, or the resource's own 404 code is raised."""
    record = store.COLLECTIONS[collection_name].get(record_id)
    if record is None:
        raise not_found(collection_name)
    return record


def resolve_body_fk(collection_name, record_id):
    """Rung 5: a body foreign key resolves, or the resource's own 404 code is raised."""
    record = store.COLLECTIONS[collection_name].get(record_id)
    if record is None:
        raise not_found(collection_name)
    return record
