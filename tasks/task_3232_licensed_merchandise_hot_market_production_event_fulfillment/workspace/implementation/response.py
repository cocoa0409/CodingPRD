"""Response envelope, pagination, authentication and authorization helpers.

Every structural name here is read from the task specification: the envelope
field names come from SCAFFOLD `response_envelope` and PRD section 2.2, the
header names from the auth validation rules (PRD 2.1), the pagination
parameters from `response_envelope.pagination_fields` / `pagination_defaults`.
"""
from flask import jsonify, request

from db import fmt_iso, now, new_id
from errors import (ERR_FORBIDDEN_ROLE, ERR_INVALID_REQUEST, ERR_UNAUTHENTICATED,
                    fail)

# --- Response envelope ----------------------------------------------------

def _meta(extra=None):
    meta = {
        "api_request_id": "req_" + new_id().replace("-", "").upper()[:16],
        "api_request_timestamp": fmt_iso(now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok_object(data, status=200, meta_extra=None):
    return jsonify({"meta": _meta(meta_extra), "response_type": "object", "data": data}), status


def ok_array(items, status=200, meta_extra=None):
    return jsonify({"meta": _meta(meta_extra), "response_type": "array", "data": items}), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --- Pagination -----------------------------------------------------------
# pagination_fields: limit, offset, total_count, has_more
# pagination_defaults: limit 10, min 1, max 100, offset 0

def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, "limit must be an integer")
    if limit < 1 or limit > 100:
        fail(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    offset = 0
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, "offset must be an integer")
    if offset < 0:
        fail(ERR_INVALID_REQUEST, "offset must not be negative")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta_extra


# --- Authentication / authorization ---------------------------------------
# Auth validation rule: "X-User-Role and X-User-ID headers present and
# well-formed" -> ERR_UNAUTHENTICATED (401).

ROLES = (
    "PlatformAdmin",
    "LicensingOps",
    "DesignOps",
    "ProductionPlanner",
    "PrintOperator",
    "FulfillmentCoordinator",
    "EnforcementAgent",
    "AuditOnly",
)


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def is_licensing_ops(self):
        return self.role == "LicensingOps"


def authenticate():
    """Read the mandatory headers; raise ERR_UNAUTHENTICATED when absent or
    malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        fail(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers must be non-empty")
    if role not in ROLES:
        fail(ERR_UNAUTHENTICATED, "X-User-Role is not a recognised role")
    return Caller(user_id, role)


def require_roles(caller, allowed):
    """Role must be permitted for the operation per the role matrix."""
    if caller.role not in allowed:
        fail(ERR_FORBIDDEN_ROLE,
             "role %s is not permitted for this operation" % caller.role)
    return caller


def require_role(caller, role):
    return require_roles(caller, (role,))