"""Response envelope helpers and input validation utilities.

Envelope per scaffold/PRD:
  success: { meta: {api_request_id, api_request_timestamp, [limit, offset,
             total_count, has_more]}, response_type: object|array, data: ... }
  error:   { meta: {api_request_id, api_request_timestamp},
             response_type: "error", data: {error_id, message} }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import (
    ApiError, validation as err_validation,
)

ROLES = {
    "FleetAdmin", "ContractorManager", "JobsiteSupervisor",
    "ServiceCoordinator", "ClaimsAdjuster", "FieldEngineer",
}


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta(pag=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": _ts()}
    if pag:
        m.update(pag)
    return m


def success(obj, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": obj}
    return jsonify(body), code


def success_list(items, total_count, limit, offset):
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pag), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field):
    if not isinstance(value, str):
        raise err_validation("%s must be an ISO 8601 string" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_validation("%s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object")
    return data


def req_field(data, field):
    v = data.get(field)
    if v is None:
        raise err_validation("Missing required field: %s" % field)
    return v


def opt_field(data, field, default=None):
    return data.get(field, default)


def check_str(v, field):
    if not isinstance(v, str) or not v:
        raise err_validation("%s must be a non-empty string" % field)
    return v


def check_int(v, field, minimum=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation("%s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err_validation("%s must be >= %d" % (field, minimum))
    return v


def check_bool(v, field):
    if not isinstance(v, bool):
        raise err_validation("%s must be a boolean" % field)
    return v


def check_enum(v, field, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise err_validation("%s must be one of %s" % (field, ", ".join(sorted(allowed))))
    return v


def check_list(v, field):
    if not isinstance(v, list):
        raise err_validation("%s must be an array" % field)
    return v


def pagination_params():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        limit, offset = 10, 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
