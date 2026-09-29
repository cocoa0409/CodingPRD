"""Request plumbing: auth (rung 1-2), payload shape (rung 3), envelope, pagination."""
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import request, Response

from core import (
    ApiError, base_meta, dumps, invalid, parse_date, parse_instant, public,
    sorted_rows, store,
)

ROLES = ("Homeowner", "ServicingAgent", "CreditUnderwriter", "TitleAgent",
         "FieldOpsCoordinator", "PortfolioAdmin")

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def _resp(payload, status):
    return Response(dumps(payload), status=status, mimetype="application/json")


def ok(data, status=200):
    return _resp({"meta": base_meta(), "response_type": "object",
                  "data": data if data is not None else {}}, status)


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(rows) < total_count
    return _resp({"meta": meta, "response_type": "array", "data": rows}, 200)


def error_response(err):
    return _resp({"meta": base_meta(), "response_type": "error",
                  "data": {"error_id": err.error_id, "message": err.message}},
                 err.http_status)


# ---------------------------------------------------------------------------
# Rungs 1 and 2
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and X-User-Role headers are required.")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %r is not authorised for this endpoint." % role)
    return user_id, role


# ---------------------------------------------------------------------------
# Rung 3 — body parsing and field validation
# ---------------------------------------------------------------------------
def raw_body():
    data = request.get_data(cache=True)
    if data is None or len(data.strip()) == 0:
        return {}
    try:
        parsed = json.loads(data.decode("utf-8"), parse_float=Decimal)
    except Exception:
        raise invalid("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise invalid("Request body must be a JSON object.")
    return parsed


def _decimal_places(value):
    exp = value.as_tuple().exponent
    return -exp if isinstance(exp, int) and exp < 0 else 0


def _check_field(spec, value):
    name = spec["name"]
    kind = spec["kind"]
    if kind == "bool":
        if not isinstance(value, bool):
            raise invalid("Field %r must be a boolean." % name)
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise invalid("Field %r must be an integer." % name)
    elif kind == "num":
        if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
            raise invalid("Field %r must be a number." % name)
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise invalid("Field %r must be a finite number." % name)
            dp = spec.get("dp")
            if dp is not None and _decimal_places(value) > dp:
                raise invalid("Field %r accepts at most %d decimal places."
                              % (name, dp))
    elif kind in ("str", "enum", "date", "instant", "id"):
        if not isinstance(value, str):
            raise invalid("Field %r must be a string." % name)
    if kind in ("int", "num"):
        lo, hi = spec.get("min"), spec.get("max")
        if lo is not None and Decimal(value) < Decimal(lo):
            raise invalid("Field %r is below its minimum." % name)
        if hi is not None and Decimal(value) > Decimal(hi):
            raise invalid("Field %r is above its maximum." % name)
        allowed = spec.get("one_of")
        if allowed is not None and value not in allowed:
            raise invalid("Field %r must be one of %s." % (name, list(allowed)))
    if kind == "str":
        minlen = spec.get("minlen")
        maxlen = spec.get("maxlen")
        if minlen is not None and len(value) < minlen:
            raise invalid("Field %r is shorter than %d characters." % (name, minlen))
        if maxlen is not None and len(value) > maxlen:
            raise invalid("Field %r is longer than %d characters." % (name, maxlen))
        if spec.get("nonblank") and value.strip() == "":
            raise invalid("Field %r may not be blank." % name)
        pattern = spec.get("pattern")
        if pattern is not None and not pattern(value):
            raise invalid("Field %r has an invalid format." % name)
    if kind == "enum":
        if value not in spec["values"]:
            raise invalid("Field %r must be one of %s."
                          % (name, list(spec["values"])))
    if kind == "date":
        if parse_date(value) is None:
            raise invalid("Field %r must be a valid ISO 8601 date." % name)
    if kind == "instant":
        if parse_instant(value) is None:
            raise invalid("Field %r must be a valid ISO 8601 instant." % name)
    if kind == "id":
        if value == "":
            raise invalid("Field %r may not be empty." % name)
    return value


def validate_body(specs, body=None):
    """Validate a request body against an ordered field spec list."""
    if body is None:
        body = raw_body()
    known = set(s["name"] for s in specs)
    for key in body.keys():
        if key not in known:
            raise invalid("Unknown field %r." % key)
    out = {}
    for spec in specs:
        name = spec["name"]
        present = name in body and body[name] is not None
        if not present:
            if spec.get("required"):
                raise invalid("Field %r is required." % name)
            if "default" in spec:
                out[name] = spec["default"]
            continue
        out[name] = _check_field(spec, body[name])
    return out


# ---------------------------------------------------------------------------
# Rung 3 — query parameters
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise invalid("limit must be an integer.")
        if str(raw).strip() != str(limit):
            raise invalid("limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise invalid("limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise invalid("offset must be an integer.")
        if str(raw).strip() != str(offset):
            raise invalid("offset must be an integer.")
        if offset < 0:
            raise invalid("offset may not be negative.")
    return limit, offset


def filters(specs):
    """specs: list of (name, kind, values_or_None). Unknown params are ignored."""
    out = {}
    args = request.args
    for name, kind, values in specs:
        if name not in args:
            continue
        raw = args.get(name)
        if kind == "int":
            try:
                out[name] = int(raw)
            except (TypeError, ValueError):
                raise invalid("Filter %r must be an integer." % name)
        elif kind == "bool":
            if raw == "true":
                out[name] = True
            elif raw == "false":
                out[name] = False
            else:
                raise invalid("Filter %r must be true or false." % name)
        elif kind == "enum":
            if raw not in values:
                raise invalid("Filter %r must be one of %s." % (name, list(values)))
            out[name] = raw
        else:
            out[name] = raw
    return out


def apply_filters(rows, flt, aliases=None):
    aliases = aliases or {}
    out = []
    for row in rows:
        keep = True
        for key, want in flt.items():
            field = aliases.get(key, key)
            if row.get(field) != want:
                keep = False
                break
        if keep:
            out.append(row)
    return out


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
