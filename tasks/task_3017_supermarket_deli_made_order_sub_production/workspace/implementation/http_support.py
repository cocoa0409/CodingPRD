"""Request plumbing shared by every route module.

Keeps body validation, pagination parsing and the error-envelope shim out of
the route bodies so each handler reads as the spec it implements.
"""
from flask import request

from errors import ApiError, fail, invalid
from response import PAGINATION_DEFAULTS, error_body, ok_array, ok_object
from auth import authorize, derive_actor
from util import to_dec

MISSING = object()


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        invalid("The request body must be a JSON object.")
    return payload


def query(name, default=None):
    value = request.args.get(name)
    if value is None or value == "":
        return default
    return value


def path_param(name):
    return request.view_args.get(name)


def pagination():
    """limit/offset with the scaffold's defaults and 1..100 range."""
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    limit = PAGINATION_DEFAULTS["limit"]
    offset = PAGINATION_DEFAULTS["offset"]
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("limit must be an integer.")
        if limit < PAGINATION_DEFAULTS["min"] or limit > PAGINATION_DEFAULTS["max"]:
            invalid("limit must be between 1 and 100 inclusive.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("offset must be an integer.")
        if offset < 0:
            invalid("offset must not be negative.")
    return limit, offset


def envelope_array(runner, rows, render, sort_key=None):
    limit, offset = pagination()
    ordered = list(rows)
    if sort_key is not None:
        ordered.sort(key=sort_key)
    window, total = _window(ordered, limit, offset)
    return ok_array(runner, [render(r) for r in window], limit, offset, total)


def _window(items, limit, offset):
    return items[offset:offset + limit], len(items)


# ---------------------------------------------------------- body field reads --
def req(payload, name, cast=None, allow_none=False):
    if name not in payload:
        if allow_none:
            return None
        invalid("%s is required." % name)
    value = payload[name]
    if value is None:
        if allow_none:
            return None
        invalid("%s must not be null." % name)
    if cast is not None:
        try:
            return cast(value)
        except (TypeError, ValueError):
            invalid("%s has an invalid value." % name)
    return value


def opt(payload, name, cast=None, default=None):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if cast is not None:
        try:
            return cast(value)
        except (TypeError, ValueError):
            invalid("%s has an invalid value." % name)
    return value


def as_string(value, field):
    if not isinstance(value, str) or not value.strip():
        invalid("%s must be a non-empty string." % field)
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                pass
        invalid("%s must be an integer." % field)
    return value


def as_number(value, field):
    try:
        return to_dec(value)
    except (TypeError, ValueError):
        invalid("%s must be a number." % field)


def as_bool(value, field):
    if not isinstance(value, bool):
        invalid("%s must be a boolean." % field)
    return value


def as_enum(value, allowed, field):
    if value not in allowed:
        invalid("%s must be one of %s." % (field, ", ".join(allowed)))
    return value


def as_list(value, field):
    if not isinstance(value, list):
        invalid("%s must be an array." % field)
    return value


class Endpoint(object):
    """Declarative wrapper: auth -> role check -> permission check -> handler."""

    def __init__(self, app, method, rule, roles, handler):
        self.method = method
        self.rule = rule
        self.roles = roles
        self.handler = handler
        app.add_url_rule(rule, endpoint="%s:%s" % (method, rule),
                         view_func=self.dispatch, methods=[method])
        ROUTES.append(self)

    def dispatch(self, **view_args):
        from db import get
        store = get()
        actor = derive_actor(request.headers.get, store)
        authorize(actor, self.roles, store.role_permissions, self.rule)
        return self.handler(store, actor, view_args)


ROUTES = []