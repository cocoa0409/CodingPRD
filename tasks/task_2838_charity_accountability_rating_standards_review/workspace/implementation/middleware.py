"""Request admission ladder (PRD section 2.8) and the route registry.

Checks 1 through 7 of the ladder are generic and live here:

  1 authentication            X-User-ID / X-User-Role both present
  2 role admission           per-endpoint role list
  3 path existence           left to right, entity specific 404
  4 organisation ownership   four declared operations only
  5 body well-formedness     unknown fields silently ignored
  6 pagination shape         limit 1..100, offset >= 0
  7 body foreign keys        entity specific 404

Checks 8 and beyond are endpoint specific and live in the route handlers.
"""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from db import (
    ROLES,
    d,
    lookup,
    parse_iso,
    quant,
)
from errors import ApiError, NOT_FOUND_FOR_ENTITY

ROUTES = []

_INT_RE = re.compile(r"^[+-]?\d+$")


class Ctx(object):
    __slots__ = ("user_id", "role", "path", "raw", "body", "limit", "offset", "fk")

    def __init__(self):
        self.path = {}
        self.raw = {}
        self.body = {}
        self.fk = {}
        self.limit = None
        self.offset = None


# ---------------------------------------------------------------- coercion


def _bad(field, what):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, what))


def coerce_int(name, value):
    if isinstance(value, bool):
        _bad(name, "must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            _bad(name, "must be an integer")
        return int(value)
    if isinstance(value, str) and _INT_RE.match(value.strip()):
        return int(value.strip())
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
    _bad(name, "must be an integer")


def coerce_number(name, value):
    if isinstance(value, bool):
        _bad(name, "must be a number")
    if isinstance(value, (int, float, Decimal)):
        return d(value)
    if isinstance(value, str):
        try:
            return d(value.strip())
        except (InvalidOperation, ValueError, ArithmeticError):
            _bad(name, "must be a number")
    _bad(name, "must be a number")


def coerce_bool(name, value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    _bad(name, "must be a boolean")


def coerce_string(name, value, spec):
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if spec.get("strip"):
        value = value.strip()
    if spec.get("non_blank") and not value.strip():
        _bad(name, "must not be blank")
    lo = spec.get("min_len")
    hi = spec.get("max_len")
    if lo is not None and len(value) < lo:
        _bad(name, "is shorter than %d characters" % lo)
    if hi is not None and len(value) > hi:
        _bad(name, "is longer than %d characters" % hi)
    pattern = spec.get("pattern")
    if pattern is not None and not re.match(pattern, value):
        _bad(name, "does not match the required format")
    if spec.get("contains") and spec["contains"] not in value:
        _bad(name, "must contain '%s'" % spec["contains"])
    return value


def validate_field(name, value, spec):
    kind = spec.get("type", "string")
    if kind == "string":
        return coerce_string(name, value, spec)
    if kind == "enum":
        if not isinstance(value, str) or value not in spec["values"]:
            _bad(name, "must be one of %s" % ", ".join(spec["values"]))
        return value
    if kind == "int":
        out = coerce_int(name, value)
        if not spec.get("defer_range"):
            if spec.get("min") is not None and out < spec["min"]:
                _bad(name, "is below the permitted minimum")
            if spec.get("max") is not None and out > spec["max"]:
                _bad(name, "is above the permitted maximum")
        return out
    if kind == "number":
        out = coerce_number(name, value)
        if not spec.get("defer_range"):
            if spec.get("min") is not None and out < d(spec["min"]):
                _bad(name, "is below the permitted minimum")
            if spec.get("max") is not None and out > d(spec["max"]):
                _bad(name, "is above the permitted maximum")
        if spec.get("scale") is not None:
            out = quant(out, spec["scale"])
        return out
    if kind == "bool":
        return coerce_bool(name, value)
    if kind == "datetime":
        parsed = parse_iso(value)
        if parsed is None:
            _bad(name, "must be an ISO 8601 timestamp")
        return parsed
    if kind == "array":
        if not isinstance(value, list):
            _bad(name, "must be an array")
        if spec.get("non_empty") and not value:
            _bad(name, "must not be empty")
        item = spec.get("item")
        if item is None:
            return list(value)
        return [validate_field(name + "[]", v, item) for v in value]
    if kind == "object_array":
        if not isinstance(value, list):
            _bad(name, "must be an array")
        if spec.get("non_empty") and not value:
            _bad(name, "must not be empty")
        out = []
        for entry in value:
            if not isinstance(entry, dict):
                _bad(name, "must be an array of objects")
            built = {}
            for sub, subspec in spec["fields"].items():
                if sub not in entry or entry[sub] is None:
                    if subspec.get("required"):
                        _bad(name + "." + sub, "is required")
                    if "default" in subspec:
                        built[sub] = subspec["default"]
                    continue
                built[sub] = validate_field(name + "." + sub, entry[sub], subspec)
            out.append(built)
        return out
    return value


def read_raw_body():
    if request.method in ("GET", "DELETE", "HEAD"):
        return {}
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return raw


def validate_body(schema, raw):
    out = {}
    for name, spec in schema.items():
        present = name in raw and raw[name] is not None
        if not present:
            if spec.get("required"):
                _bad(name, "is required")
            if "default" in spec:
                out[name] = spec["default"]
            else:
                out[name] = None
            continue
        out[name] = validate_field(name, raw[name], spec)
    return out


def parse_pagination():
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        if not _INT_RE.match(raw_limit.strip() or "x"):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer.")
        limit = int(raw_limit.strip())
    if raw_offset is None:
        offset = 0
    else:
        if not _INT_RE.match(raw_offset.strip() or "x"):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer.")
        offset = int(raw_offset.strip())
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", "offset must not be negative.")
    return limit, offset


def resolve_fks(schema, body):
    found = {}
    for name, spec in schema.items():
        entity = spec.get("fk")
        if not entity:
            continue
        value = body.get(name)
        if value is None:
            continue
        row = lookup(entity, value)
        if row is None:
            raise ApiError(NOT_FOUND_FOR_ENTITY[entity])
        found[name] = row
    return found


# ---------------------------------------------------------------- ownership


def owner_from_path(param):
    def check(ctx):
        if ctx.role != "OrganizationRep":
            return
        org = ctx.path[param]
        if org["id"] != ctx.user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")

    return check


def owner_from_body_cycle(ctx):
    if ctx.role != "OrganizationRep":
        return
    cycle_id = ctx.raw.get("rating_cycle_id")
    if not isinstance(cycle_id, str):
        return
    cycle = lookup("RatingCycle", cycle_id)
    if cycle is None:
        return
    if cycle["organization_id"] != ctx.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


# ---------------------------------------------------------------- registry


def route(rule, method, roles, path_params=(), body=None, paginated=False, owner=None):
    """Register an endpoint and wrap it in ladder checks 1 through 7."""

    def decorator(handler):
        def wrapper(**path_kwargs):
            ctx = Ctx()
            # 1 - authentication
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not user_id.strip() or not role or not role.strip():
                raise ApiError("ERR_UNAUTHENTICATED")
            ctx.user_id = user_id
            ctx.role = role
            # 2 - role admission
            if role not in ROLES or role not in roles:
                raise ApiError("ERR_ROLE_NOT_PERMITTED")
            # 3 - path existence, left to right
            for param, entity in path_params:
                row = lookup(entity, path_kwargs.get(param))
                if row is None:
                    raise ApiError(NOT_FOUND_FOR_ENTITY[entity])
                ctx.path[param] = row
            ctx.raw = read_raw_body()
            # 4 - organisation ownership
            if owner is not None:
                owner(ctx)
            # 5 - body well-formedness
            if body:
                ctx.body = validate_body(body, ctx.raw)
            # 6 - pagination shape
            if paginated:
                ctx.limit, ctx.offset = parse_pagination()
            # 7 - body foreign keys
            if body:
                ctx.fk = resolve_fks(body, ctx.body)
            return handler(ctx)

        wrapper.__name__ = handler.__name__
        ROUTES.append((rule, method, wrapper, handler.__name__))
        return handler

    return decorator


def attach(app):
    for rule, method, view, name in ROUTES:
        app.add_url_rule(rule, endpoint=name, view_func=view, methods=[method])
