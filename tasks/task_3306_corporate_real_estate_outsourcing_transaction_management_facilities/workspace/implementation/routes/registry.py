"""Blueprint, route decorator and request-body helpers."""
from functools import wraps

from flask import Blueprint, request

from core import auth
from core.db import DB, paginate
from core.errors import ApiError
from core.response import ok

bp = Blueprint("api", __name__)

ENDPOINT_CODES = {}


def route(method, rule, name, allowed, code=200):
    def deco(fn):
        auth.ENDPOINT_ROLES[name] = list(allowed)
        ENDPOINT_CODES[name] = code

        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth.enforce(name)
            return fn(*args, **kwargs)

        bp.add_url_rule(rule, endpoint=name, view_func=wrapper, methods=[method])
        return wrapper
    return deco


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST",
                       "The request body must be a JSON object.")
    return data


def vt(name):
    return (request.view_args or {}).get(name)


def int_arg(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def pag_args():
    limit = int_arg("limit", 10)
    offset = int_arg("offset", 0)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginated_ok(items, status=200):
    limit, offset = pag_args()
    page, meta = paginate(items, limit, offset)
    from core.db import serialize
    return ok(serialize(page), status, meta)


def listed(rows):
    from core.db import serialize
    return ok(serialize(rows))


# ---------------------------------------------------------------------------
# Body field validation (raises ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def validate(body_data, spec):
    """spec: list of (field, kind, required) where kind is one of
    str, int, num, bool, enum, list, any."""
    for field, kind, required in spec:
        present = field in body_data and body_data.get(field) is not None
        if not present:
            if required:
                raise ApiError("ERR_INVALID_REQUEST",
                               "The field '%s' is required." % field)
            continue
        value = body_data.get(field)
        if kind == "any":
            continue
        if kind == "str":
            if not isinstance(value, str):
                raise ApiError("ERR_INVALID_REQUEST",
                               "The field '%s' must be a string." % field)
        elif kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ApiError("ERR_INVALID_REQUEST",
                               "The field '%s' must be an integer." % field)
        elif kind == "num":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ApiError("ERR_INVALID_REQUEST",
                               "The field '%s' must be a number." % field)
        elif kind == "bool":
            if not isinstance(value, bool):
                raise ApiError("ERR_INVALID_REQUEST",
                               "The field '%s' must be a boolean." % field)
        elif kind == "list":
            if not isinstance(value, list):
                raise ApiError("ERR_INVALID_REQUEST",
                               "The field '%s' must be an array." % field)
        elif kind == "enum":
            if not isinstance(value, str):
                raise ApiError("ERR_INVALID_REQUEST",
                               "The field '%s' must be a string enum value." % field)
    return body_data


def req(field):
    return (field, "any", True)


def opt(field, kind="any"):
    return (field, kind, False)


def enum(body_data, field, allowed, default=None):
    value = body_data.get(field, default)
    if value is None:
        return default
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def lookup(kind, oid, label="resource"):
    row = DB.get(kind, oid) if oid else None
    if row is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND",
                       "No %s matches the supplied identifier." % label)
    return row


def as_int(value, field):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST",
                       "The field '%s' must be an integer." % field)