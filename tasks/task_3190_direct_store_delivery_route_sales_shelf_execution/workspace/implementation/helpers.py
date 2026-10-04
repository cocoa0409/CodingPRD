"""Shared helpers: auth context, validation primitives, record lifecycle,
pagination, timestamps, role enforcement (validation priorities 1-3)."""

import math
import re
import uuid
from datetime import date, datetime, timezone

from flask import request

import db as store
from errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_MISSING_AUTH_CONTEXT,
    ERR_VALIDATION,
    err,
)

ROLES = ("PlatformAdmin", "RouteSupervisor", "RouteSalesRep", "StoreManager")

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

RESOURCE_ERRORS = {
    "reps": "ERR_REP_NOT_FOUND",
    "stores": "ERR_STORE_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "routes": "ERR_ROUTE_NOT_FOUND",
    "assignments": "ERR_ASSIGNMENT_NOT_FOUND",
    "route_days": "ERR_ROUTE_DAY_NOT_FOUND",
    "lots": "ERR_LOT_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "order_lines": "ERR_ORDER_NOT_FOUND",
    "shelf_executions": "ERR_SHELF_EXECUTION_NOT_FOUND",
    "stale_credits": "ERR_STALE_CREDIT_NOT_FOUND",
    "promo_agreements": "ERR_PROMO_AGREEMENT_NOT_FOUND",
    "promo_executions": "ERR_PROMO_EXECUTION_NOT_FOUND",
    "settlements": "ERR_SETTLEMENT_NOT_FOUND",
    "snapshots": "ERR_SNAPSHOT_NOT_FOUND",
}


# ---------------------------------------------------------------------------
# auth (validation priority 1-2)
# ---------------------------------------------------------------------------

def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err(ERR_MISSING_AUTH_CONTEXT, "Missing or unrecognized auth context")
    return uid, role


def require_role(role, *allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role %s not permitted for this endpoint" % role)


# ---------------------------------------------------------------------------
# lookup helpers (validation priority 3)
# ---------------------------------------------------------------------------

def get(collection, rid, error_id=None):
    rec = store.db[collection].get(rid)
    if rec is None:
        error_id = error_id or RESOURCE_ERRORS[collection]
        raise err(error_id, "%s not found: %s" % (collection, rid))
    return rec


def find_by(collection, field, value):
    for rec in store.db[collection].values():
        if rec.get(field) == value:
            return rec
    return None


# ---------------------------------------------------------------------------
# request body primitives
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_VALIDATION, "Request body must be a JSON object")
    return data


def _missing(name):
    raise err(ERR_VALIDATION, "Missing required field: %s" % name)


def req_field(data, name):
    if name not in data or data[name] is None:
        _missing(name)
    return data[name]


def opt_field(data, name, default=None):
    value = data.get(name, default)
    return default if value is None else value


def req_str(data, name):
    value = req_field(data, name)
    if not isinstance(value, str) or not value.strip():
        raise err(ERR_VALIDATION, "Field %s must be a non-empty string" % name)
    return value


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_str(data, name)


def req_int(data, name):
    value = req_field(data, name)
    return _as_int(value, name)


def opt_int(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return _as_int(data[name], name)


def _as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_VALIDATION, "Field %s must be an integer" % name)
    return value


def req_bool(data, name):
    value = req_field(data, name)
    if not isinstance(value, bool):
        raise err(ERR_VALIDATION, "Field %s must be a boolean" % name)
    return value


def opt_bool(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_bool(data, name)


def req_enum(data, name, choices):
    value = req_str(data, name)
    if value not in choices:
        raise err(ERR_VALIDATION, "Field %s must be one of %s" % (name, list(choices)))
    return value


def opt_enum(data, name, choices, default=None):
    if name not in data or data[name] is None:
        return default
    return req_enum(data, name, choices)


def req_number(data, name):
    value = req_field(data, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err(ERR_VALIDATION, "Field %s must be a number" % name)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise err(ERR_VALIDATION, "Field %s must be a finite number" % name)
    return value


def opt_number(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_number(data, name)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def req_date(data, name):
    value = req_str(data, name)
    if not _DATE_RE.match(value):
        raise err(ERR_VALIDATION, "Field %s must be an ISO date YYYY-MM-DD" % name)
    try:
        date.fromisoformat(value)
    except ValueError:
        raise err(ERR_VALIDATION, "Field %s must be a valid ISO date" % name)
    return value


def opt_date(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_date(data, name)


# ---------------------------------------------------------------------------
# record lifecycle
# ---------------------------------------------------------------------------

def now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_record(common=True):
    rec = {"id": str(uuid.uuid4()), "created_at": now_iso()}
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_VALIDATION, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def filter_sort_page(collection, filters):
    limit, offset = parse_pagination()
    items = []
    for rec in store.db[collection].values():
        ok = True
        for field, value in filters.items():
            if value is not None and rec.get(field) != value:
                ok = False
                break
        if ok:
            items.append(rec)
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


def clock_now_iso():
    return store.clock.iso()
