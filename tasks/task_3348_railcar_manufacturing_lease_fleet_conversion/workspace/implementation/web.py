"""HTTP plumbing: envelope, auth, RBAC, pagination and request-shape helpers.

Envelope field names are taken verbatim from SCAFFOLD.yaml `response_envelope`
(meta / response_type / data, pagination limit/offset/total_count/has_more).
Auth headers and role names are taken from PRD section 2.1.
"""

import random
import re
import string

from flask import request, jsonify

from store import store, now_iso
from errors import ApiError, unauthenticated, forbidden, not_found, invalid_request

# PRD section 2.1: exactly seven roles, spelled as follows.
ROLES = (
    "PlatformAdmin",
    "SupplyChainCoordinator",
    "ProductionPlanner",
    "LeaseAdministrator",
    "PortfolioManager",
    "RegulatoryRetrofitist",
    "Lessee",
)
ALL_ROLES = ROLES

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def new_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(18))


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, response_type="object", status=200, meta_extra=None):
    return jsonify({
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }), status


def created(data, response_type="object"):
    return ok(data, response_type=response_type, status=201)


def error_response(err):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }), err.http_status


# --- auth / RBAC -------------------------------------------------------------
def current_identity():
    """Validate X-User-ID / X-User-Role (PRD section 2.1, validation priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise unauthenticated()
    if role not in ROLES:
        raise unauthenticated("The role named in X-User-Role is not a declared role.")
    return user_id, role


def require_role(role, allowed):
    """Validation priority 2: declared but not permitted -> ERR_FORBIDDEN."""
    if role not in allowed:
        raise forbidden("The acting role %s is not permitted for this operation." % role)


def flask_rule(rule):
    """Scaffold paths use {param}; Flask/Werkzeug wants <param>."""
    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", r"<\1>", rule)


def route(app, rule, method, roles):
    """Register one endpoint, running checks 1 and 2 (auth, RBAC) first."""
    def deco(fn):
        def view(**kwargs):
            user_id, role = current_identity()
            require_role(role, roles)
            return fn(user_id, role, **kwargs)
        endpoint = "%s_%s" % (method.lower(), rule.strip("/").replace("/", "_")
                              .replace("{", "").replace("}", "")
                              .replace("-", "_").replace(".", "_"))
        view.__name__ = endpoint
        app.add_url_rule(flask_rule(rule), view_func=view, methods=[method],
                         endpoint=endpoint)
        return view
    return deco


# --- pagination --------------------------------------------------------------
def parse_pagination(args):
    """limit defaults to 10, min 1, max 100; offset defaults to 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer between 1 and 100.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise invalid_request("limit must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be a non-negative integer.")
        if offset < 0:
            raise invalid_request("offset must be a non-negative integer.")
    return limit, offset


def page_rows(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    has_more = (offset + len(page)) < total
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta_extra


def list_response(rows, limit, offset, view):
    page, meta_extra = page_rows(rows, limit, offset)
    return ok([view(r) for r in page], response_type="array", meta_extra=meta_extra)


def filtered(rows, args, mapping):
    """Apply documented equality filters before pagination."""
    out = rows
    for param, field in mapping.items():
        value = args.get(param)
        if value is not None and value != "":
            out = [r for r in out if str(r.get(field)) == str(value)]
    return out


# --- path / body helpers -----------------------------------------------------
def must_get(collection, row_id, label):
    """Validation priority 3: templated path ids resolve left to right."""
    row = store.get(collection, row_id)
    if row is None:
        raise not_found(label)
    return row


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("The request body must be a JSON object.")
    return data


def body_get(body, field, default=None):
    value = body.get(field, default)
    return value


def require_str(body, field):
    value = body.get(field)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        raise invalid_request("%s is required." % field)
    return value


def require_int(body, field, minimum=None, maximum=None):
    value = body.get(field)
    if value is None or isinstance(value, bool):
        raise invalid_request("%s is required and must be an integer." % field)
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        raise invalid_request("%s must be an integer." % field)
    if isinstance(value, float) and value != ivalue:
        raise invalid_request("%s must be an integer." % field)
    if minimum is not None and ivalue < minimum:
        raise invalid_request("%s must be >= %d." % (field, minimum))
    if maximum is not None and ivalue > maximum:
        raise invalid_request("%s must be <= %d." % (field, maximum))
    return ivalue


def require_enum(body, field, allowed):
    value = body.get(field)
    if value not in allowed:
        raise invalid_request("%s must be one of %s." % (field, " | ".join(allowed)))
    return value


def optional_int(body, field, default=None, minimum=None):
    value = body.get(field, None)
    if value is None:
        return default
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        raise invalid_request("%s must be an integer." % field)
    if minimum is not None and ivalue < minimum:
        raise invalid_request("%s must be >= %d." % (field, minimum))
    return ivalue


def require_date(body, field):
    from store import to_date
    value = body.get(field)
    if value is None or value == "":
        raise invalid_request("%s is required." % field)
    try:
        return to_date(value).isoformat()
    except (ValueError, TypeError):
        raise invalid_request("%s must be an ISO 8601 date." % field)


def optional_date(body, field, default=None):
    from store import to_date
    value = body.get(field)
    if value is None or value == "":
        return default
    try:
        return to_date(value).isoformat()
    except (ValueError, TypeError):
        raise invalid_request("%s must be an ISO 8601 date." % field)


def optional_bool(body, field, default=False):
    value = body.get(field, None)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def fk(body, field, collection, label, required=True):
    """Validation priority 4: body foreign keys resolve to persisted rows."""
    from errors import fk_not_found
    value = body.get(field)
    if value is None or value == "":
        if required:
            raise invalid_request("%s is required." % field)
        return None
    row = store.get(collection, value)
    if row is None:
        raise fk_not_found(label)
    return row
