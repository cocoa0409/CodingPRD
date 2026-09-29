"""Request-shape validation (PRD validation band ERR_INVALID_REQUEST, HTTP 400)."""
from flask import request

import clock
from errors import ERR_INVALID_REQUEST, fail

MISSING = object()


class Field(object):
    def __init__(
        self,
        name,
        kind,
        required=False,
        default=MISSING,
        values=None,
        minimum=None,
        maximum=None,
        gt=None,
        min_len=None,
        max_len=None,
        item_values=None,
        non_empty=False,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.values = values
        self.minimum = minimum
        self.maximum = maximum
        self.gt = gt
        self.min_len = min_len
        self.max_len = max_len
        self.item_values = item_values
        self.non_empty = non_empty


def raw_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        fail(ERR_INVALID_REQUEST, "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check(field, value):
    name = field.name
    kind = field.kind
    if kind == "string":
        if not isinstance(value, str):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be a string." % name)
        if field.min_len is not None and len(value) < field.min_len:
            fail(ERR_INVALID_REQUEST, "Field '%s' is too short." % name)
        if field.max_len is not None and len(value) > field.max_len:
            fail(ERR_INVALID_REQUEST, "Field '%s' is too long." % name)
        return value
    if kind == "int":
        if not _is_int(value):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)
        if field.minimum is not None and value < field.minimum:
            fail(ERR_INVALID_REQUEST, "Field '%s' is below its minimum." % name)
        if field.maximum is not None and value > field.maximum:
            fail(ERR_INVALID_REQUEST, "Field '%s' is above its maximum." % name)
        return value
    if kind == "number":
        if not _is_number(value):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be a number." % name)
        if field.gt is not None and not value > field.gt:
            fail(ERR_INVALID_REQUEST, "Field '%s' must be greater than %s." % (name, field.gt))
        if field.minimum is not None and value < field.minimum:
            fail(ERR_INVALID_REQUEST, "Field '%s' is below its minimum." % name)
        if field.maximum is not None and value > field.maximum:
            fail(ERR_INVALID_REQUEST, "Field '%s' is above its maximum." % name)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in field.values:
            fail(ERR_INVALID_REQUEST, "Field '%s' is not a permitted value." % name)
        return value
    if kind == "array_enum":
        if not isinstance(value, list):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be an array." % name)
        if field.non_empty and len(value) == 0:
            fail(ERR_INVALID_REQUEST, "Field '%s' must not be empty." % name)
        for item in value:
            if not isinstance(item, str) or item not in field.item_values:
                fail(ERR_INVALID_REQUEST, "Field '%s' holds an unpermitted value." % name)
        return value
    if kind == "date":
        if clock.parse_date(value) is None:
            fail(ERR_INVALID_REQUEST, "Field '%s' must be a YYYY-MM-DD date." % name)
        return value.strip()
    if kind == "instant":
        if clock.parse_instant(value) is None:
            fail(ERR_INVALID_REQUEST, "Field '%s' must be an ISO-8601 UTC instant." % name)
        return value.strip()
    if kind == "any":
        return value
    fail(ERR_INVALID_REQUEST, "Field '%s' could not be validated." % name)


def parse_body(schema):
    """Validate the JSON body against `schema`.

    Returns (values, provided) where `provided` names the keys the client
    actually supplied with a non-null value.
    """
    body = raw_body()
    values = {}
    provided = set()
    for field in schema:
        name = field.name
        if name not in body or body[name] is None:
            if field.required:
                fail(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
            values[name] = None if field.default is MISSING else field.default
            continue
        provided.add(name)
        values[name] = _check(field, body[name])
    return values, provided


# ---------------------------------------------------------------------------
# Query string helpers
# ---------------------------------------------------------------------------

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _int_param("limit", raw_limit)
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail(ERR_INVALID_REQUEST, "Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _int_param("offset", raw_offset)
        if offset < 0:
            fail(ERR_INVALID_REQUEST, "Query parameter 'offset' must not be negative.")
    return limit, offset


def _int_param(name, raw):
    text = raw.strip()
    if text == "":
        fail(ERR_INVALID_REQUEST, "Query parameter '%s' must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        fail(ERR_INVALID_REQUEST, "Query parameter '%s' must be an integer." % name)
    return int(text)


def qs_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def qs_enum(name, values):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in values:
        fail(ERR_INVALID_REQUEST, "Query parameter '%s' is not a permitted value." % name)
    return value


def qs_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail(ERR_INVALID_REQUEST, "Query parameter '%s' must be a boolean." % name)


def qs_date(name):
    value = request.args.get(name)
    if value is None:
        return None
    if clock.parse_date(value) is None:
        fail(ERR_INVALID_REQUEST, "Query parameter '%s' must be a YYYY-MM-DD date." % name)
    return value.strip()
