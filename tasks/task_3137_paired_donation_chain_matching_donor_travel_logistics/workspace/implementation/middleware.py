"""Auth middleware: header extraction, role validation, RBAC, body/pagination helpers."""

from flask import request

from db import store
from errors import (
    ApiError,
    err_not_found,
    err_unauthenticated,
    err_unauthorized,
    err_invalid_request,
    err_center_mismatch,
)

ROLES = ("RegistryAdmin", "MatchOperator", "CenterCoordinator", "LogisticsCoordinator")
ALL_ROLES = list(ROLES)

# RBAC per (method, resource, action); None action = collection CRUD/read.
# Values: list of allowed roles.
RBAC = {
    ("POST", "_clock", "set_current_utc"): ["RegistryAdmin", "MatchOperator"],

    ("POST", "centers", None): ["RegistryAdmin"],
    ("GET", "centers", None): ALL_ROLES,
    ("GET", "centers", "get"): ALL_ROLES,
    ("POST", "centers", "probate"): ["RegistryAdmin"],
    ("POST", "centers", "suspend"): ["RegistryAdmin"],
    ("POST", "centers", "reinstate"): ["RegistryAdmin"],

    ("POST", "donors", None): ["CenterCoordinator"],
    ("GET", "donors", None): ALL_ROLES,
    ("GET", "donors", "get"): ALL_ROLES,
    ("POST", "donors", "medical-hold"): ["CenterCoordinator"],
    ("POST", "donors", "medical-release"): ["CenterCoordinator"],
    ("POST", "donors", "withdraw"): ["CenterCoordinator"],
    ("POST", "donors", "deceased"): ["CenterCoordinator"],
    ("POST", "donors", "complete-nephrectomy"): ["CenterCoordinator"],
    ("POST", "donors", "fail-preop"): ["CenterCoordinator"],
    ("POST", "donors", "claims"): ["CenterCoordinator"],

    ("POST", "recipients", None): ["CenterCoordinator"],
    ("GET", "recipients", None): ALL_ROLES,
    ("GET", "recipients", "get"): ALL_ROLES,
    ("POST", "recipients", "medical-hold"): ["CenterCoordinator"],
    ("POST", "recipients", "medical-release"): ["CenterCoordinator"],
    ("POST", "recipients", "withdraw"): ["CenterCoordinator"],
    ("POST", "recipients", "deceased"): ["CenterCoordinator"],
    ("POST", "recipients", "complete-transplant"): ["CenterCoordinator"],

    ("POST", "pairs", None): ["CenterCoordinator"],
    ("GET", "pairs", None): ["RegistryAdmin", "MatchOperator", "CenterCoordinator"],
    ("GET", "pairs", "get"): ["RegistryAdmin", "MatchOperator", "CenterCoordinator"],
    ("POST", "pairs", "verify"): ["CenterCoordinator"],
    ("POST", "pairs", "enter-pool"): ["CenterCoordinator"],
    ("POST", "pairs", "dissolve"): ["CenterCoordinator"],

    ("POST", "chain-runs", None): ["MatchOperator"],
    ("GET", "chain-runs", None): ["RegistryAdmin", "MatchOperator"],
    ("GET", "chain-runs", "get"): ["RegistryAdmin", "MatchOperator"],
    ("POST", "chain-runs", "execute"): ["MatchOperator"],
    ("POST", "chain-runs", "publish"): ["MatchOperator"],
    ("POST", "chain-runs", "supersede"): ["MatchOperator"],

    ("GET", "chains", None): ALL_ROLES,
    ("GET", "chains", "get"): ALL_ROLES,
    ("POST", "chains", "lock"): ["MatchOperator"],
    ("POST", "chains", "schedule"): ["MatchOperator"],
    ("POST", "chains", "start-execution"): ["MatchOperator"],

    ("GET", "match-offers", None): ALL_ROLES,
    ("GET", "match-offers", "get"): ALL_ROLES,
    ("POST", "match-offers", "crossmatch-review"): ["CenterCoordinator"],
    ("POST", "match-offers", "center-accept"): ["CenterCoordinator"],
    ("POST", "match-offers", "center-decline"): ["CenterCoordinator"],

    ("GET", "crossmatch-reviews", None): ["RegistryAdmin", "MatchOperator", "CenterCoordinator"],
    ("GET", "crossmatch-reviews", "get"): ["RegistryAdmin", "MatchOperator", "CenterCoordinator"],

    ("POST", "slots", None): ["CenterCoordinator"],
    ("GET", "slots", None): ALL_ROLES,
    ("GET", "slots", "get"): ALL_ROLES,
    ("POST", "slots", "release"): ["MatchOperator"],

    ("POST", "shipments", None): ["LogisticsCoordinator"],
    ("GET", "shipments", None): ALL_ROLES,
    ("GET", "shipments", "get"): ALL_ROLES,
    ("POST", "shipments", "depart"): ["LogisticsCoordinator"],
    ("POST", "shipments", "delay"): ["LogisticsCoordinator"],
    ("POST", "shipments", "reroute"): ["LogisticsCoordinator"],
    ("POST", "shipments", "deliver"): ["LogisticsCoordinator"],
    ("POST", "shipments", "cancel"): ["LogisticsCoordinator"],

    ("POST", "itineraries", None): ["LogisticsCoordinator"],
    ("GET", "itineraries", None): ALL_ROLES,
    ("GET", "itineraries", "get"): ALL_ROLES,
    ("POST", "itineraries", "confirm"): ["LogisticsCoordinator"],
    ("POST", "itineraries", "cancel"): ["LogisticsCoordinator"],
    ("POST", "itineraries", "reimburse"): ["RegistryAdmin"],

    ("GET", "policies", None): ["RegistryAdmin", "MatchOperator", "CenterCoordinator"],
    ("GET", "policies", "get"): ["RegistryAdmin", "MatchOperator", "CenterCoordinator"],

    ("GET", "claims", None): ["RegistryAdmin", "CenterCoordinator"],
    ("GET", "claims", "get"): ["RegistryAdmin", "CenterCoordinator"],
    ("POST", "claims", "start-review"): ["RegistryAdmin"],
    ("POST", "claims", "approve"): ["RegistryAdmin"],
    ("POST", "claims", "partial-approve"): ["RegistryAdmin"],
    ("POST", "claims", "deny"): ["RegistryAdmin"],
    ("POST", "claims", "pay"): ["RegistryAdmin"],

    ("POST", "outcomes", None): ["CenterCoordinator"],
    ("GET", "outcomes", None): ["RegistryAdmin", "MatchOperator", "CenterCoordinator"],
    ("GET", "outcomes", "get"): ["RegistryAdmin", "MatchOperator", "CenterCoordinator"],
    ("POST", "outcomes", "attribute"): ["RegistryAdmin"],
    ("POST", "outcomes", "appeal"): ["CenterCoordinator"],
    ("POST", "outcomes", "resolve-appeal"): ["RegistryAdmin"],
    ("POST", "outcomes", "finalize"): ["RegistryAdmin"],

    ("GET", "chain-breaks", None): ["RegistryAdmin", "MatchOperator", "CenterCoordinator"],
    ("GET", "chain-breaks", "get"): ["RegistryAdmin", "MatchOperator", "CenterCoordinator"],
    ("POST", "chain-breaks", "reconstruct"): ["MatchOperator"],
}


def actor(resource, action):
    """Validate auth headers + RBAC. Returns (user_id, role)."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise err_unauthenticated()
    user_id = request.headers.get("X-User-ID") or ""
    allowed = RBAC.get((request.method, resource, action))
    if allowed is None:
        raise err_not_found("Endpoint not defined")
    if role not in allowed:
        raise err_unauthorized()
    return user_id, role


def coordinator_center_id(user_id, role):
    """For CenterCoordinator, X-User-ID is the acting center's id (§2.1)."""
    if role != "CenterCoordinator":
        return None
    return user_id


def require_center_match(user_id, role, expected_center_id):
    if role == "CenterCoordinator" and user_id != expected_center_id:
        raise err_center_mismatch()


def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        if not request.data:
            return {}
        try:
            body = request.get_json(force=True)
        except Exception:
            raise err_invalid_request("Body must be valid JSON")
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise err_invalid_request("Body must be a JSON object")
        return body
    return {}


def req_field(body, name, types):
    if name not in body or body[name] is None:
        raise err_invalid_request("Missing required field: %s" % name)
    v = body[name]
    if not isinstance(v, types) or isinstance(v, bool) and bool not in types:
        raise err_invalid_request("Invalid type for field: %s" % name)
    return v


def opt_field(body, name, types, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, types) or isinstance(v, bool) and bool not in types:
        raise err_invalid_request("Invalid type for field: %s" % name)
    return v


def req_enum(body, name, choices):
    v = req_field(body, name, str)
    if v not in choices:
        raise err_invalid_request("Invalid value for field: %s" % name)
    return v


def opt_enum(body, name, choices, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str) or v not in choices:
        raise err_invalid_request("Invalid value for field: %s" % name)
    return v


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except ValueError:
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except ValueError:
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(rows):
    """Sort by created_at asc and slice; returns (page, pagination-meta)."""
    limit, offset = pagination_params()
    rows = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(rows)
    page = rows[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def get_or_404(table, rid):
    rec = table.get(rid)
    if rec is None:
        raise err_not_found("Resource not found: %s" % rid)
    return rec
