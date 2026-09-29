"""Authentication / authorisation helpers (PRD 2.1, evaluation band 2)."""

from flask import request

import config
from errors import fail


def role():
    value = request.headers.get(config.HDR_USER_ROLE, None)
    if value is None:
        return None
    value = value.strip()
    return value or None


def user_id():
    value = request.headers.get(config.HDR_USER_ID, None)
    if value is None:
        return None
    value = value.strip()
    return value or None


def require_role(*allowed):
    """Missing role, or a role not authorised for this operation -> 403."""
    current = role()
    if current is None or current not in allowed:
        fail("ERR_UNAUTHORIZED", "Role is missing or not authorised for this operation.")
    return current


def require_user_id():
    """The four operator-stamping operations demand a non-empty X-User-ID."""
    current = user_id()
    if current is None:
        fail("ERR_USER_ID_REQUIRED", "X-User-ID is required for this operation.")
    return current


def require_distributor_scope(expected_distributor_id):
    """A Distributor may only address rows carrying its own id."""
    if role() != config.ROLE_DISTRIBUTOR:
        return
    if user_id() != expected_distributor_id:
        fail("ERR_DISTRIBUTOR_SCOPE", "This resource belongs to another distributor.")


def require_facility_scope(expected_facility_id):
    """A FacilityManager may only address rows carrying its own facility id."""
    if role() != config.ROLE_FACILITY_MANAGER:
        return
    if user_id() != expected_facility_id:
        fail("ERR_FACILITY_SCOPE", "This resource belongs to another facility.")
