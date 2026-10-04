"""Auth header extraction, role checking and ownership decisions."""
from flask import request

import domain
import store
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def actor():
    """Return (role, user_id). Raises ERR_UNAUTHENTICATED when absent/invalid."""
    role = request.headers.get(USER_ROLE_HEADER)
    user_id = request.headers.get(USER_ID_HEADER)
    if not role or not user_id or role not in domain.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return role, user_id


def require_role(roles):
    role, user_id = actor()
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return role, user_id


def require_owner(role, user_id, table, row, owner_field):
    """Entity-backed roles must own the addressed row."""
    if role == "PlatformAdmin":
        return
    role_table = {"Employer": "employers", "CoveredWorker": "covered_workers", "Verifier": "verifiers"}
    if role not in role_table or role_table[role] != table:
        return
    if row.get(owner_field) != user_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")


def require_self(role, user_id, target_id, role_table_name, table):
    if role == "PlatformAdmin":
        return
    role_table = {"Employer": "employers", "CoveredWorker": "covered_workers", "Verifier": "verifiers"}
    if role not in role_table or role_table[role] != table:
        return
    if target_id != user_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")


def pagination_args():
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(rows, limit, offset, sort_key=None):
    if sort_key is not None:
        rows = sorted(rows, key=sort_key)
    else:
        rows = sorted(rows, key=lambda r: (r.get("created_at"), r["id"]))
    total = len(rows)
    return rows[offset:offset + limit], total


def require_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    return data