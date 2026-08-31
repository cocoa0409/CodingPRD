"""Rejection-ladder ranks 1 and 2: authentication and role authorisation."""
from functools import wraps

from flask import request

from errors import fail
from store import lock

ROLES = (
    "DeskAdmin",
    "Merchandiser",
    "FuturesTrader",
    "RiskOfficer",
    "GrainInspector",
    "FreightCoordinator",
)

ALL_ROLES = list(ROLES)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return {"user_id": user_id, "role": role}


def endpoint(roles):
    """Ladder 1 (401) then ladder 2 (403), then the handler under the store lock."""
    allowed = tuple(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            actor = authenticate()
            if actor["role"] not in allowed:
                fail("ERR_UNAUTHORIZED")
            with lock:
                return fn(actor, *args, **kwargs)
        return wrapper
    return decorator
