"""Shared route plumbing: role guard, body extraction, envelope helpers."""

from functools import wraps

from flask import request

from errors import ApiError
from middleware import ROLE_TABLE, get_caller, require_role
from response import paginate, resolve_pagination, success_array, success_object


def endpoint(method, path):
    """Wrap a handler with the role table's guard for (method, path)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            caller = get_caller()
            require_role(caller, ROLE_TABLE[(method, path)])
            body = {}
            if method in ("POST", "PUT", "PATCH"):
                raw = request.get_json(silent=True)
                if raw is None:
                    raw = {}
                if not isinstance(raw, dict):
                    raise ApiError("ERR_INVALID_REQUEST",
                                   "The request body must be a JSON object.")
                body = raw
            return fn(caller, body, *args, **kwargs)

        return wrapper

    return decorator


def ok(serializer, row):
    return success_object(serializer(row))


def listing(serializer, rows):
    limit, offset = resolve_pagination(request.args)
    window, total = paginate(rows, limit, offset)
    return success_array([serializer(row) for row in window], total, limit, offset)


def query(name, default=None):
    value = request.args.get(name)
    if value is None or value == "":
        return default
    return value