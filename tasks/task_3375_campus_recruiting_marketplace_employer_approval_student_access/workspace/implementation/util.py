"""Response envelope, auth context, request-body parsing, pagination, time.

Envelope shape is fixed by PRD section 2.2:
  success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
                     total_count, has_more]}, "response_type": "object"|"array",
            "data": ...}
  error:   {"meta": {api_request_id, api_request_timestamp},
            "response_type": "error",
            "data": {"error_id": ..., "message": ...}}
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from db import now
from errors import fail


ROLES = {"Anonymous", "PlatformAdmin", "CareerCenterAdmin", "EmployerRecruiter", "Student"}


def canonical(dt):
    """ISO 8601 UTC with exactly three fractional digits, Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 string into an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def _meta_base():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": canonical(now()),
    }


def success_object(payload, status=200):
    body = {"meta": _meta_base(), "response_type": "object", "data": payload}
    return jsonify(body), status


def success_list(items, total, limit, offset, status=200):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def get_context():
    """Priority 1 auth check: headers present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
             "X-User-ID and X-User-Role headers are required and the role must be declared")
    return user_id, role


def require_role(role, *allowed):
    """Priority 2 auth check: role permitted for this endpoint."""
    if role not in allowed:
        fail("ERR_UNAUTHORIZED_ROLE",
             "Role %s is not permitted for this endpoint" % role)


def pagination_params():
    """limit default 10 (min 1, max 100), offset default 0."""
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(records, serializer):
    """Sort by creation timestamp ascending and emit a paginated list."""
    records = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    limit, offset = pagination_params()
    page = records[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


class Body:
    """JSON body reader that defers shape failures to the residual bucket.

    Domain validations (priorities 1-10) run first; each uses safe getters
    that simply record a shape problem instead of raising. finalize() is
    called only after every earlier-priority check has passed, so
    ERR_INVALID_REQUEST fires last, per PRD section 2.9 rule 11.
    """

    def __init__(self):
        raw = request.get_json(silent=True)
        self.bad = False
        if raw is None:
            self.d = {}
            self.bad = True
        elif not isinstance(raw, dict):
            self.d = {}
            self.bad = True
        else:
            self.d = raw

    def has(self, name):
        return name in self.d

    def raw(self, name):
        return self.d.get(name)

    def str_f(self, name, required=False, enum=None):
        if name not in self.d:
            if required:
                self.bad = True
            return None
        value = self.d[name]
        if not isinstance(value, str):
            self.bad = True
            return None
        if enum is not None and value not in enum:
            self.bad = True
            return None
        return value

    def int_f(self, name, required=False, minv=None, maxv=None):
        if name not in self.d:
            if required:
                self.bad = True
            return None
        value = self.d[name]
        if isinstance(value, bool) or not isinstance(value, int):
            self.bad = True
            return None
        if minv is not None and value < minv:
            self.bad = True
            return None
        if maxv is not None and value > maxv:
            self.bad = True
            return None
        return value

    def dt_f(self, name, required=False):
        if name not in self.d:
            if required:
                self.bad = True
            return None
        dt = parse_iso(self.d[name])
        if dt is None:
            self.bad = True
        return dt

    def list_f(self, name, required=False, item_enum=None):
        if name not in self.d:
            if required:
                self.bad = True
            return None
        value = self.d[name]
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            self.bad = True
            return None
        if item_enum is not None and any(x not in item_enum for x in value):
            self.bad = True
            return None
        return list(value)

    def finalize(self):
        if self.bad:
            fail("ERR_INVALID_REQUEST", "Malformed request body")
