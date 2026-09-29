"""Request schema validation (refusal priority 3) and pagination (PRD 2.3)."""

from flask import request

from errors import ApiError, bad_request
from util import parse_iso

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def body():
    """The JSON request body as a dict; an absent body reads as empty."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad_request("Request body must be a JSON object")
    return parsed


def _present(data, name):
    return name in data and data[name] is not None


def missing(name):
    return bad_request("Field '%s' is required" % name)


def wrong_type(name, expected):
    return bad_request("Field '%s' must be %s" % (name, expected))


# --------------------------------------------------------------------------- #
# scalar field readers
# --------------------------------------------------------------------------- #
def req_string(data, name):
    if not _present(data, name):
        raise missing(name)
    value = data[name]
    if not isinstance(value, str):
        raise wrong_type(name, "a string")
    return value


def opt_string(data, name, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        raise wrong_type(name, "a string")
    return value


def req_int(data, name, minimum=None, maximum=None):
    if not _present(data, name):
        raise missing(name)
    return _as_int(data[name], name, minimum, maximum)


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if not _present(data, name):
        return default
    return _as_int(data[name], name, minimum, maximum)


def _as_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise wrong_type(name, "an integer")
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be at most %d" % (name, maximum))
    return value


def req_bool(data, name):
    if not _present(data, name):
        raise missing(name)
    value = data[name]
    if not isinstance(value, bool):
        raise wrong_type(name, "a boolean")
    return value


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, bool):
        raise wrong_type(name, "a boolean")
    return value


def req_enum(data, name, vocabulary):
    value = req_string(data, name)
    if value not in vocabulary:
        raise bad_request("Field '%s' must be one of %s" % (name, ", ".join(vocabulary)))
    return value


def opt_enum(data, name, vocabulary, default=None):
    value = opt_string(data, name, None)
    if value is None:
        return default
    if value not in vocabulary:
        raise bad_request("Field '%s' must be one of %s" % (name, ", ".join(vocabulary)))
    return value


def req_datetime(data, name):
    value = req_string(data, name)
    parsed = parse_iso(value)
    if parsed is None:
        raise bad_request("Field '%s' must be an ISO 8601 instant" % name)
    return parsed


def opt_datetime(data, name, default=None):
    value = opt_string(data, name, None)
    if value is None:
        return default
    parsed = parse_iso(value)
    if parsed is None:
        raise bad_request("Field '%s' must be an ISO 8601 instant" % name)
    return parsed


def req_id(data, name):
    return req_string(data, name)


def opt_id(data, name):
    return opt_string(data, name, None)


def req_enum_list(data, name, vocabulary, allow_empty=True, distinct=True):
    if not _present(data, name):
        raise missing(name)
    return _as_enum_list(data[name], name, vocabulary, allow_empty, distinct)


def opt_enum_list(data, name, vocabulary, allow_empty=True, distinct=True, default=None):
    if not _present(data, name):
        return default
    return _as_enum_list(data[name], name, vocabulary, allow_empty, distinct)


def _as_enum_list(value, name, vocabulary, allow_empty, distinct):
    if not isinstance(value, list):
        raise wrong_type(name, "an array")
    if not allow_empty and len(value) == 0:
        raise bad_request("Field '%s' must not be empty" % name)
    seen = []
    for item in value:
        if not isinstance(item, str):
            raise wrong_type(name, "an array of strings")
        if item not in vocabulary:
            raise bad_request("Field '%s' must draw from %s" % (name, ", ".join(vocabulary)))
        if distinct and item in seen:
            raise bad_request("Field '%s' must not repeat a value" % name)
        seen.append(item)
    return list(value)


# --------------------------------------------------------------------------- #
# query parameters
# --------------------------------------------------------------------------- #
def query_enum(name, vocabulary):
    raw = request.args.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "":
        return None
    if raw not in vocabulary:
        raise bad_request("Query parameter '%s' must be one of %s" % (name, ", ".join(vocabulary)))
    return raw


def query_string(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


def query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        raise bad_request("Query parameter '%s' must be an integer" % name)


def pagination():
    limit = query_int("limit")
    offset = query_int("offset")
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    elif limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise bad_request(
            "Query parameter 'limit' must be between %d and %d"
            % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
        )
    if offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    elif offset < PAGINATION_MIN_OFFSET:
        raise bad_request("Query parameter 'offset' must not be negative")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


def sort_rows(rows, sequence_key=None):
    """PRD 2.3: created_at ascending, sequence_number breaking ties where present.

    Insertion order is preserved for rows without a monotone counter, and record
    identifiers are never used as an ordering key.
    """
    indexed = list(enumerate(rows))
    if sequence_key:
        indexed.sort(key=lambda pair: (pair[1]["created_at"], pair[1].get(sequence_key) or 0, pair[0]))
    else:
        indexed.sort(key=lambda pair: (pair[1]["created_at"], pair[0]))
    return [pair[1] for pair in indexed]
