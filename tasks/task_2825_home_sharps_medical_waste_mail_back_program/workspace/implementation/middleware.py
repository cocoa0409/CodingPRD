"""Authentication, role checking and transactional request handling.

PRD section 2.1: every request carries X-User-ID and X-User-Role. Header
validity is the very first check performed on any request, ahead of payload
parsing and ahead of any lookup.
"""
from functools import wraps

from flask import g, request

import db
from constants import ROLES
from errors import ERR_ROLE_NOT_PERMITTED, ERR_UNAUTHENTICATED, ApiError, fail


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role not in ROLES:
        fail(ERR_UNAUTHENTICATED)
    g.user_id = user_id
    g.role = role


def user_id():
    return g.user_id


def role():
    return g.role


def endpoint(roles, mutating=True):
    """Wrap a view: authenticate, check role membership, run atomically.

    A mutating request takes a whole-store snapshot up front and restores it if
    anything raises, so an aborted request leaves no partial writes behind
    (PRD section 2.8 cascades and section 3.9 auto-ship run aborts).
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in roles:
                fail(ERR_ROLE_NOT_PERMITTED)
            if not mutating:
                return fn(*args, **kwargs)
            snap = db.snapshot()
            try:
                return fn(*args, **kwargs)
            except ApiError:
                db.restore(snap)
                raise
            except Exception:
                db.restore(snap)
                raise

        return wrapper

    return decorator
