"""Response envelope, authentication/RBAC, pagination and serialization."""
import functools
import random
import string
from decimal import Decimal
from datetime import datetime

from flask import g, jsonify, request

from errors import ApiError, invalid
from store import db, LOCK, new_id, now_wall
from util import fmt_dt

ROLES = ("TaxManager", "StateAnalyst", "Controller", "Auditor")
ANY_ROLE = ROLES

ALNUM = string.ascii_uppercase + string.digits


# --------------------------------------------------------------------------
# Envelope (PRD 2.2)
# --------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(now_wall()),
    }


def ok(data, status=200):
    flush_dirty()
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total):
    flush_dirty()
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# Versioning / cascade discipline (PRD 2.10)
# --------------------------------------------------------------------------
def bump(record):
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now_wall()


def mark_dirty(record):
    pending = getattr(g, "_dirty", None)
    if pending is None:
        pending = []
        g._dirty = pending
    for existing in pending:
        if existing is record:
            return
    pending.append(record)


def flush_dirty():
    pending = getattr(g, "_dirty", None)
    if not pending:
        return
    g._dirty = []
    for record in pending:
        bump(record)


# --------------------------------------------------------------------------
# Auth (PRD 2.1) + RBAC (bands 1 and 2 of PRD 2.11)
# --------------------------------------------------------------------------
def current_user_id():
    return getattr(g, "user_id", None)


def _authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Valid X-User-ID and X-User-Role headers are required.")
    g.user_id = user_id
    g.user_role = role
    return role


def endpoint(roles):
    allowed = tuple(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with LOCK:
                g._dirty = []
                role = _authenticate()
                if role not in allowed:
                    raise ApiError(
                        "ERR_ROLE_NOT_PERMITTED",
                        "Role %s is not permitted to perform this operation." % role,
                    )
                return fn(*args, **kwargs)

        return wrapper

    return decorator


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid("The request body must be a JSON object.")
    return data


# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise invalid("'limit' must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            raise invalid("'limit' must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise invalid("'offset' must be an integer of at least 0")
        if offset < 0:
            raise invalid("'offset' must be at least 0")
    return limit, offset


def query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise invalid("'%s' must be an integer" % name)


def query_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def paginate(records, serializer):
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def sort_created(records):
    return sorted(records, key=lambda r: r["_seq"])


# --------------------------------------------------------------------------
# Record construction and serialization
# --------------------------------------------------------------------------
def new_record(versioned=True):
    stamp = now_wall()
    record = {
        "id": new_id(),
        "created_at": stamp,
        "_seq": db.next_seq(),
    }
    if versioned:
        record["updated_at"] = stamp
        record["version"] = 1
    return record


def _jval(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_dt(value)
    return value


def serialize(record, fields, versioned=True):
    out = {"id": record["id"], "created_at": fmt_dt(record["created_at"])}
    if versioned:
        out["updated_at"] = fmt_dt(record["updated_at"])
        out["version"] = record["version"]
    for name in fields:
        out[name] = _jval(record.get(name))
    return out
