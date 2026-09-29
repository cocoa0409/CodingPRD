"""Authentication, RBAC and the entity-backed CommitteeChair identity binding.

PRD sec 2.1 / validations priority 1, 2 and 6.
"""
import functools

from flask import g, request

from errors import ApiError
from store import ROLES, db


def _authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    role = role.strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a recognised role." % role)
    g.user_id = str(user_id).strip()
    g.role = role


def endpoint(roles):
    """Priority 1 then priority 2, applied before anything else on the route."""
    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            _authenticate()
            if g.role not in allowed:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "Role %s may not invoke this endpoint." % g.role,
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.user_id


def actor_role():
    return g.role


def member_status(member):
    """CommitteeMember.status is clock-derived: EXPIRED once the clock date reaches
    term_end_on (PRD sec 3.3)."""
    from store import clock_date, parse_date

    end = parse_date(member["term_end_on"])
    if end is not None and clock_date() >= end:
        return "EXPIRED"
    return "ACTIVE"


def active_chair_of(committee_id):
    for member in db.members.values():
        if member["committee_id"] != committee_id:
            continue
        if not member["is_chair"]:
            continue
        if member_status(member) != "ACTIVE":
            continue
        return member
    return None


def require_chair_binding(committee_id):
    """Validation priority 6 — only for the two chair-only operations."""
    if g.role != "CommitteeChair":
        return
    for member in db.members.values():
        if member["id"] != g.user_id:
            continue
        if member["committee_id"] != committee_id:
            continue
        if not member["is_chair"]:
            continue
        if member_status(member) != "ACTIVE":
            continue
        return
    raise ApiError(
        "ERR_UNAUTHORIZED",
        "X-User-ID is not the active chair of the target advisory committee.",
    )
