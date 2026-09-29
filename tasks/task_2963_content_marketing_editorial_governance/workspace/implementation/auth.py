"""Authentication and role authorisation (PRD section 2.1) -- ladder rules 1
and 2, which run before every other check in that order."""

import functools

from flask import g, request

from errors import ApiError
from store import store

ROLE_MANAGING_EDITOR = "ManagingEditor"
ROLE_SME = "SubjectMatterExpertUser"
ROLE_LEGAL = "LegalReviewer"
ROLE_BRAND = "BrandReviewer"
ROLE_ACCESSIBILITY = "AccessibilityReviewer"
ROLE_ANALYTICS = "AnalyticsService"

KNOWN_ROLES = (
    ROLE_MANAGING_EDITOR, ROLE_SME, ROLE_LEGAL, ROLE_BRAND,
    ROLE_ACCESSIBILITY, ROLE_ANALYTICS,
)

ALL_REVIEWERS = (ROLE_MANAGING_EDITOR, ROLE_LEGAL, ROLE_BRAND, ROLE_ACCESSIBILITY)
ALL_REVIEWERS_AND_SME = ALL_REVIEWERS + (ROLE_SME,)
EVERY_ROLE = ALL_REVIEWERS_AND_SME + (ROLE_ANALYTICS,)

GATE_ROLE = {
    "SME": ROLE_SME,
    "LEGAL": ROLE_LEGAL,
    "BRAND": ROLE_BRAND,
    "ACCESSIBILITY": ROLE_ACCESSIBILITY,
}


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and a known X-User-Role are required")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       role + " may not call this endpoint")
    g.user_id = user_id
    g.role = role


def endpoint(*allowed_roles):
    """Wrap a view: serialise on the store lock, then run ladder rules 1 and 2."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with store.lock:
                g.touched = set()
                authenticate(allowed_roles)
                return fn(*args, **kwargs)
        return wrapper
    return decorator
