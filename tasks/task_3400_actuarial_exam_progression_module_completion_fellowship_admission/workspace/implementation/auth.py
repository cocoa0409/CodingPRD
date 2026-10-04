"""Auth header extraction and role/ownership gates (PRD §2.1, §2.8 priorities 1-2-5).

Headers: X-User-Role (always, must be a declared role) and X-User-ID (required
for every role except Anonymous).
"""

from flask import request

import constants as C
from errors import ApiError
from store import db


def auth():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in C.ROLES:
        raise ApiError("ERR_MISSING_HEADERS", 401,
                       "X-User-Role header missing or not a declared role")
    if role != "Anonymous" and (uid is None or uid == ""):
        raise ApiError("ERR_MISSING_HEADERS", 401,
                       "X-User-ID header is required for this role")
    return role, uid


def require(*roles):
    role, uid = auth()
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "role %s is not authorized for this endpoint" % role)
    return role, uid


def caller_candidate(uid):
    """Resolve the acting Candidate from X-User-ID (existence, 404)."""
    cand = db.candidates.get(uid)
    if cand is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404,
                       "acting candidate does not exist")
    return cand


def check_owner(cond):
    if not cond:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403,
                       "resource belongs to another candidate")
