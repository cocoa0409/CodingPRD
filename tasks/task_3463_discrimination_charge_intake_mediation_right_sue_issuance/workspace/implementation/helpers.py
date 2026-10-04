"""Shared request/response helpers: envelope, auth, pagination, timestamps."""

import uuid
from datetime import datetime, timezone

from flask import jsonify, request

import constants
from errors import (
    ApiError,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_UNAUTHENTICATED,
    ERR_VALIDATION_FAILED,
)
from store import db


# ---------------------------------------------------------------------------
# Time formatting (logical clock only; the wall clock is never read)
# ---------------------------------------------------------------------------
def now():
    """Current logical clock instant (timezone-aware UTC)."""
    return db.clock


def today():
    """Current logical clock date."""
    return db.clock.date()


def iso_ts(value):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if isinstance(value, datetime):
        value = value.astimezone(timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (
            value.microsecond // 1000
        )
    raise TypeError("iso_ts expects datetime")


def iso_dt_flexible(value):
    """Format a datetime as ISO 8601 UTC; no fractional part when zero.

    Used for the clock endpoint echo so a whole-second input round-trips.
    """
    value = value.astimezone(timezone.utc)
    if value.microsecond:
        return iso_ts(value)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_date(value):
    """Format a date at date precision: 'YYYY-MM-DDT00:00:00Z'."""
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%Y-%m-%dT00:00:00Z")


def stamp_now():
    return iso_ts(db.clock)


# ---------------------------------------------------------------------------
# Identity / ids
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def common_fields():
    """System-managed fields for a freshly created primary resource."""
    ts = stamp_now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def bump(entity):
    """Version +1 and updated_at refresh on every mutation (incl. cascades)."""
    entity["version"] += 1
    entity["updated_at"] = stamp_now()


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD section 1.0 / PRD section 2.2)
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": stamp_now(),
    }


def respond_object(data, status=200):
    payload = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(payload), status


def respond_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    payload = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(payload), status


def respond_error(error_id, message, http_status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), http_status


# ---------------------------------------------------------------------------
# Auth (pipeline steps 1 and 2)
# ---------------------------------------------------------------------------
def authenticate():
    """Extract X-User-ID / X-User-Role; both mandatory, role must be known."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in constants.ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "Missing X-User-ID/X-User-Role headers or unrecognized role.",
        )
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            "Role %s is not authorized for this endpoint." % role,
        )


def check_party_ownership(user_id, role, charge):
    """Pipeline step 5 for charge-scoped endpoints.

    ChargingParty acts on its own charges (X-User-ID == complainant_id);
    RespondentRep on charges against its employer (X-User-ID == employer_id);
    StateAgencyOfficer only on FEPA-owned charges.
    """
    if role == constants.ROLE_CHARGING_PARTY:
        if user_id != charge["complainant_id"]:
            raise ApiError(
                ERR_NOT_RESOURCE_OWNER,
                "ChargingParty may only act on its own charges.",
            )
    elif role == constants.ROLE_RESPONDENT_REP:
        if user_id != charge["employer_id"]:
            raise ApiError(
                ERR_NOT_RESOURCE_OWNER,
                "RespondentRep may only act on charges against its own employer.",
            )
    elif role == constants.ROLE_STATE_AGENCY_OFFICER:
        if charge["investigation_owner"] != constants.OWNER_FEPA:
            raise ApiError(
                ERR_NOT_RESOURCE_OWNER,
                "StateAgencyOfficer may only access FEPA-owned charges.",
            )


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3)
# ---------------------------------------------------------------------------
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = constants.PAGE_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION_FAILED, "limit must be an integer.")
        limit = max(constants.PAGE_MIN_LIMIT, min(constants.PAGE_MAX_LIMIT, limit))
    if raw_offset is None:
        offset = constants.PAGE_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION_FAILED, "offset must be an integer.")
        offset = max(constants.PAGE_DEFAULT_OFFSET, offset)
    return limit, offset


def paginate_and_respond(rows, serializer):
    """Sort by creation ascending (insertion order breaks timestamp ties),
    slice per limit/offset, and emit the list envelope."""
    limit, offset = pagination_params()
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return respond_list([serializer(r) for r in page], total, limit, offset)


def request_body(required=True):
    """Parse the JSON body. Endpoints with no declared input tolerate an
    absent body; endpoints with input require a JSON object."""
    raw = request.get_json(silent=True)
    if raw is None:
        if required:
            raise ApiError(
                ERR_VALIDATION_FAILED, "Request body must be a JSON object."
            )
        return {}
    if not isinstance(raw, dict):
        raise ApiError(
            ERR_VALIDATION_FAILED, "Request body must be a JSON object."
        )
    return raw
