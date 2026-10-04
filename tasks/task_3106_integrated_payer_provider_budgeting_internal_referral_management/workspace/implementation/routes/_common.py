"""Shared helpers for the route blueprints."""

from flask import jsonify, request

from constants import (
    ALL_ROLES,
    ROLE_ACCESS_SCHEDULER,
    ROLE_BUDGET_APPROPRIATIONS_COMMITTEE,
    ROLE_CARE_TEAM_MEMBER,
    ROLE_PLATFORM_ADMIN,
    ROLE_PROVIDER,
    ROLE_QUALITY_REVIEW_BOARD,
    ROLE_REGIONAL_FINANCE_OFFICER,
    ROLE_UTILIZATION_REVIEWER,
)
from errors import ApiError
from middleware import principal_from_headers, require_role
from response import error_body, parse_pagination, paginate, success, success_list

READERS = ALL_ROLES

RFO = ROLE_REGIONAL_FINANCE_OFFICER
UR = ROLE_UTILIZATION_REVIEWER
AS = ROLE_ACCESS_SCHEDULER
QRB = ROLE_QUALITY_REVIEW_BOARD
BAC = ROLE_BUDGET_APPROPRIATIONS_COMMITTEE
CTM = ROLE_CARE_TEAM_MEMBER
PROV = ROLE_PROVIDER
ADMIN = ROLE_PLATFORM_ADMIN

CLAIM_READERS = (ADMIN, RFO, UR, BAC)
BUDGET_READERS = (ADMIN, RFO, BAC)
QUALITY_READERS = (ADMIN, RFO, QRB, BAC)
CAPACITY_READERS = (ADMIN, RFO, AS, BAC)
TRANSFER_READERS = (ADMIN, RFO, BAC)


def principal(allowed=READERS):
    actor = principal_from_headers(request.headers)
    require_role(actor, allowed)
    return actor


def payload():
    """The JSON request body, or an empty mapping when none was supplied."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        return {}
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_MISSING_REQUIRED_FIELD",
                       "The field '%s' is required." % name, 422)
    return body[name]


def optional_field(body, name, default=None):
    value = body.get(name)
    return default if value is None else value


def list_response(table, rows, order_key=None):
    """Sort by creation timestamp ascending, paginate, and envelope."""
    if order_key is None:
        order_key = lambda row: (row.get("created_at", ""), row.get("id", ""))
    ordered = sorted(rows, key=order_key)
    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(ordered, limit, offset)
    from projections import view
    return jsonify(success(
        [view(table, row) for row in page], "array", pagination))


def single_response(table, row, status=200):
    from projections import view
    return jsonify(success(view(table, row))), status


def empty_response(status=200):
    return jsonify(success({})), status


def error_response(error):
    return jsonify(error_body(error.error_id, error.message)), error.http_status


def arg(name):
    return request.args.get(name)


def filter_rows(rows, **criteria):
    out = []
    for row in rows:
        keep = True
        for key, value in criteria.items():
            if value is None:
                continue
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return out


def truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "t")


def bool_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    return truthy(value)


def success_list_all(rows):
    return jsonify(success_list(rows, {
        "limit": len(rows),
        "offset": 0,
        "total_count": len(rows),
        "has_more": False,
    }))