"""Request-shape validation and reference resolution.

Ladder steps implemented here (PRD 2.9):
  5. required inputs present and every supplied value matches its declared type
     -> ERR_INVALID_REQUEST (400)
  8. every body foreign key resolves to an existing row -> ERR_REFERENCE_NOT_FOUND (404)
  9. every body foreign key belongs to the same campaign/unit scope
     -> ERR_REFERENCE_SCOPE_MISMATCH (409)
"""
from flask import request

from . import clock, store
from .errors import ApiError

STRING = "string"
INTEGER = "integer"
NUMBER = "number"
BOOLEAN = "boolean"
DATETIME = "datetime"
ENUM = "enum"


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def _bad(name, expected):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a valid %s." % (name, expected))


def _check(name, value, type_name, enum=None):
    if type_name == INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(name, "integer")
        return value
    if type_name == NUMBER:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad(name, "number")
        return value
    if type_name == BOOLEAN:
        if not isinstance(value, bool):
            _bad(name, "boolean")
        return value
    if type_name == STRING:
        if not isinstance(value, str):
            _bad(name, "string")
        return value
    if type_name == ENUM:
        if not isinstance(value, str) or value not in (enum or ()):
            _bad(name, "enum value")
        return value
    if type_name == DATETIME:
        parsed = clock.parse(value)
        if parsed is None:
            _bad(name, "ISO 8601 datetime")
        return parsed
    _bad(name, "value")
    return None


def shape(fields):
    """Validate the request body against a field spec list.

    Each spec: {"name": str, "type": str, "required": bool, "enum": tuple}
    Returns a dict of the supplied values (datetimes parsed, ISO strings kept
    for datetime fields under the "<name>_iso" key is NOT produced; callers
    receive the parsed datetime under the plain name).
    """
    data = body()
    out = {}
    for spec in fields:
        name = spec["name"]
        required = spec.get("required", False)
        present = name in data and data[name] is not None
        if not present:
            if required:
                raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
            continue
        value = data[name]
        if spec["type"] == STRING and isinstance(value, str) and value == "" and spec.get("allow_blank", True) is False:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must not be blank." % name)
        out[name] = _check(name, value, spec["type"], spec.get("enum"))
    return out


def f(name, type_name, required=False, enum=None):
    return {"name": name, "type": type_name, "required": required, "enum": enum}


def optional_version(spec_name):
    return f(spec_name, INTEGER, False)


def reference(table, row_id, label):
    """Ladder step 8: a body foreign key must resolve to an existing row."""
    row = store.find(table, row_id)
    if row is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "The referenced %s does not exist." % label)
    return row


def path_row(table, row_id, label):
    """Ladder step 6: the resource addressed by the path id must exist."""
    row = store.find(table, row_id)
    if row is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "The %s addressed by the path does not exist." % label)
    return row


def scope_mismatch(message):
    raise ApiError("ERR_REFERENCE_SCOPE_MISMATCH", message)


def stale(message=None):
    raise ApiError("ERR_STALE_VERSION", message)


def expect_version(record, supplied, field_name):
    """Optimistic concurrency: compare the client's token to the current version."""
    if supplied is None:
        return
    if isinstance(supplied, bool) or not isinstance(supplied, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field_name)
    if int(supplied) != int(record.get("version", 1)):
        raise ApiError(
            "ERR_STALE_VERSION",
            "Field '%s' does not match the current version of the parent resource." % field_name,
        )
