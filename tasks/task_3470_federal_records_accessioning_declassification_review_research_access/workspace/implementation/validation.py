"""Shared adjudication-rung helpers (PRD §2.6 ladder).

This module hosts the rungs that are identical for every endpoint:
  rung 1  — authentication context (X-User-ID / X-User-Role present + declared)
  rung 2  — role admission for the endpoint
plus the request-shape validators used at later rungs, entity-backed
ownership (rung 5), and pagination parsing (PRD §2.3).

The remaining rungs (3 path existence, 4 body-FK existence, 6 cross-FK,
7 OCC, 8 from-state, 9 researcher-active, 10 posture, 11 segregation of
duties, 12 uniqueness, 13 temporal, 14 method/metadata, 15 shape,
16 reservation, 17 fiscal) are invoked in fixed order by each route.
"""
from flask import request

from constants import ROLES
from errors import err
from store import parse_dt


# --- rung 1: authentication context -----------------------------------------
def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and X-User-Role "
            "must be a declared role",
        )
    return uid, role


# --- rung 2: role admission --------------------------------------------------
def require_role(role, allowed):
    if role not in allowed:
        raise err(
            "ERR_FORBIDDEN_ROLE",
            "role %s is not admitted to this endpoint" % role,
        )


# --- rung 5: entity-backed ownership ----------------------------------------
def require_ownership(uid, owner_id):
    if uid != owner_id:
        raise err(
            "ERR_OWNERSHIP_MISMATCH",
            "caller X-User-ID does not match the owning entity reference",
        )


# --- body access -------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


# --- shape validators (rung 15 family; also used where a rung needs the
# --- field parsed before it can be evaluated) --------------------------------
def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err(
            "ERR_INVALID_REQUEST",
            "%s is required and must be a non-empty string" % name,
        )
    return v


def opt_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string" % name)
    return v


def req_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "%s is required and must be an integer" % name)
    return v


def req_bool(body, name, default=False):
    v = body.get(name, default)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return v


def req_enum(body, name, values):
    v = body.get(name)
    if v not in values:
        raise err(
            "ERR_INVALID_REQUEST",
            "%s must be one of %s" % (name, ", ".join(values)),
        )
    return v


def opt_enum(body, name, values):
    v = body.get(name)
    if v is None:
        return None
    if v not in values:
        raise err(
            "ERR_INVALID_REQUEST",
            "%s must be one of %s" % (name, ", ".join(values)),
        )
    return v


def req_dt(body, name):
    """Required ISO 8601 UTC datetime field; returns an aware datetime."""
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err(
            "ERR_INVALID_REQUEST",
            "%s is required and must be an ISO 8601 UTC timestamp" % name,
        )
    try:
        return parse_dt(v)
    except Exception:
        raise err(
            "ERR_INVALID_REQUEST",
            "%s must be an ISO 8601 UTC timestamp" % name,
        )


def req_list_str(body, name, nonempty=False):
    v = body.get(name)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise err(
            "ERR_INVALID_REQUEST",
            "%s is required and must be an array of strings" % name,
        )
    if nonempty and len(v) == 0:
        raise err("ERR_INVALID_REQUEST", "%s must be a non-empty array" % name)
    return v


def body_fk(body, name):
    """Rung-4 precursor: a body foreign-key field must be a non-empty string
    before its existence can be checked."""
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "%s is required" % name)
    return v


# --- pagination (PRD §2.3) ---------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    def _parse(raw, default):
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "invalid pagination parameter")

    limit = _parse(limit_raw, 10)
    offset = _parse(offset_raw, 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


# --- list plumbing: filter + sort + page -------------------------------------
def list_page(items, filters):
    """Apply exact-match filters, sort by created_at ascending (stable, so
    equal timestamps keep insertion order), then apply limit/offset."""
    out = [e for e in items if all(e.get(k) == v for k, v in filters.items())]
    out.sort(key=lambda e: e["created_at"])
    total = len(out)
    limit, offset = parse_pagination()
    return out[offset:offset + limit], total, limit, offset
