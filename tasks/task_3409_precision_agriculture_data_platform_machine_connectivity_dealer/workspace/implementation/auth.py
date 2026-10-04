"""Auth context, request-shape validation, existence, and scope-gate helpers.

Implements the priority-ordered validation pipeline of PRD section 2.10:
  1. auth headers            -> caller()
  2. role authorization      -> require_role()
  3. request body shape      -> body_json() + as_* validators
  4. existence               -> get_or_404()
  5. data-access scope       -> scoped_gate() / ownership checks
"""

import json
from datetime import date, datetime
from decimal import Decimal

from flask import request

from constants import ROLE_TO_GRANTEE, ROLES, SCOPES
from db import STORES, now, parse_date, parse_dt
from errors import (
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_INVALID_REQUEST,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ApiError,
    access_denied,
    invalid_request,
    not_found,
)


# ---------------------------------------------------------------------------
# Priority 1-2: authentication context and role authorization
# ---------------------------------------------------------------------------

def caller():
    """Priority 1: X-User-ID and X-User-Role headers present, role declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers are required and must name a declared role",
        )
    return uid, role


def require_role(role, allowed):
    """Priority 2: caller role must be in the endpoint's declared role list."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, 403, "role %s is not permitted" % role)


# ---------------------------------------------------------------------------
# Priority 3: request body shape
# ---------------------------------------------------------------------------

def body_json():
    raw = request.get_data()
    if not raw or not raw.strip():
        return {}
    try:
        b = json.loads(raw)
    except Exception:
        raise invalid_request("request body is not valid JSON")
    if not isinstance(b, dict):
        raise invalid_request("request body must be a JSON object")
    return b


def need(b, name):
    if name not in b or b[name] is None:
        raise invalid_request("missing required field: %s" % name)
    return b[name]


def as_str(v, name):
    if not isinstance(v, str) or v == "":
        raise invalid_request("field %s must be a non-empty string" % name)
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request("field %s must be an integer" % name)
    return v


def as_pos_int(v, name):
    v = as_int(v, name)
    if v <= 0:
        raise invalid_request("field %s must be positive" % name)
    return v


def as_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request("field %s must be a number" % name)
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise invalid_request("field %s must be a boolean" % name)
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise invalid_request("field %s must be one of %s" % (name, sorted(allowed)))
    return v


def as_dt(v, name):
    if not isinstance(v, str):
        raise invalid_request("field %s must be an ISO 8601 timestamp" % name)
    try:
        return parse_dt(v)
    except Exception:
        raise invalid_request("field %s must be an ISO 8601 timestamp" % name)


def as_date(v, name):
    if not isinstance(v, str):
        raise invalid_request("field %s must be an ISO date (YYYY-MM-DD)" % name)
    try:
        return parse_date(v)
    except Exception:
        raise invalid_request("field %s must be an ISO date (YYYY-MM-DD)" % name)


def _two_decimal_places(v, name):
    d = Decimal(str(v))
    if -d.as_tuple().exponent > 2:
        raise invalid_request("field %s must have at most 2 decimal places" % name)
    return d


def as_zones(v):
    if not isinstance(v, list) or len(v) == 0:
        raise invalid_request("field zones must be a non-empty array")
    out = []
    for z in v:
        if not isinstance(z, dict):
            raise invalid_request("each zone must be an object")
        if "zone_id" not in z or z["zone_id"] is None:
            raise invalid_request("each zone requires zone_id")
        if "rate_l_per_ha" not in z or "area_ha" not in z:
            raise invalid_request("each zone requires rate_l_per_ha and area_ha")
        rate = as_num(z["rate_l_per_ha"], "rate_l_per_ha")
        area = as_num(z["area_ha"], "area_ha")
        _two_decimal_places(rate, "rate_l_per_ha")
        _two_decimal_places(area, "area_ha")
        if Decimal(str(rate)) <= 0 or Decimal(str(area)) <= 0:
            raise invalid_request("zone rate_l_per_ha and area_ha must be positive")
        out.append({"zone_id": z["zone_id"], "rate_l_per_ha": rate, "area_ha": area})
    return out


def as_scopes(v):
    if not isinstance(v, list) or len(v) == 0:
        raise invalid_request("field scopes must be a non-empty array")
    for s in v:
        if not isinstance(s, str) or s not in SCOPES:
            raise invalid_request("scopes must be drawn from %s" % sorted(SCOPES))
    # de-duplicate, preserve order
    seen = []
    for s in v:
        if s not in seen:
            seen.append(s)
    return seen


# ---------------------------------------------------------------------------
# Priority 4: existence
# ---------------------------------------------------------------------------

def get_or_404(store, rid, label=None):
    r = STORES[store].get(rid)
    if r is None:
        raise not_found("%s not found" % (label or store))
    return r


# ---------------------------------------------------------------------------
# Priority 5: data-access scope gates (PRD sections 2.10.5 and 3.4)
# ---------------------------------------------------------------------------

def find_active_grant(org_id, role, uid, scope):
    """An ACTIVE grant on org_id whose grantee_type maps to the caller role,
    whose grantee_ref_id equals the caller X-User-ID, whose closed window
    covers now, and whose scopes include the required scope."""
    want_type = ROLE_TO_GRANTEE.get(role)
    if want_type is None:
        return None
    t = now()
    for g in STORES["data_share_grants"].values():
        if g["organization_id"] != org_id:
            continue
        if g["grantee_type"] != want_type:
            continue
        if g["grantee_ref_id"] != uid:
            continue
        if g["status"] != "ACTIVE":
            continue
        if scope not in g["scopes"]:
            continue
        if not (g["valid_from"] <= t <= g["valid_until"]):
            continue
        return g
    return None


def scoped_gate(org_id, role, uid, scope):
    """Priority 5 for scoped single-resource reads: owner grower, admin/system,
    or a valid grant covering the required scope."""
    if role in ("PlatformAdmin", "System"):
        return
    if role == "GrowerManager" and uid == org_id:
        return
    if find_active_grant(org_id, role, uid, scope) is not None:
        return
    raise access_denied("caller neither owns the resource nor holds a valid grant")


def can_see_scope(org_id, role, uid, scope):
    if role in ("PlatformAdmin", "System"):
        return True
    if role == "GrowerManager":
        return uid == org_id
    return find_active_grant(org_id, role, uid, scope) is not None


def owner_gate(org_id, role, uid):
    """GrowerManager ownership check (X-User-ID == organization_id)."""
    if role == "PlatformAdmin":
        return
    if role == "GrowerManager" and uid == org_id:
        return
    raise access_denied("caller does not own the target organization")


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3) and list plumbing
# ---------------------------------------------------------------------------

def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise invalid_request("limit and offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_resources(store, filters, visible):
    """Apply exact-match query filters, restrict to caller-visible records,
    sort by created_at ascending (insertion order breaks ties), paginate."""
    limit, offset = parse_pagination()
    recs = []
    for r in STORES[store].values():
        if not all(r.get(f) == v for f, v in filters):
            continue
        if not visible(r):
            continue
        recs.append(r)
    recs.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(recs)
    page = recs[offset : offset + limit]
    return page, total, limit, offset
