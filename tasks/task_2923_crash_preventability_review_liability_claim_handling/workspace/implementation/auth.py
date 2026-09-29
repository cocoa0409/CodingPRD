"""Authentication (band 1) and role authorization (band 2)."""

from flask import request

from errors import fail

ROLES = (
    "SafetyAdmin",
    "Dispatcher",
    "Driver",
    "CommitteeMember",
    "SafetyManager",
    "ClaimsAdjuster",
    "ClaimsManager",
    "Auditor",
)

# Convenience role bundles used by the route modules.
SAFETY_READ = (
    "SafetyAdmin", "SafetyManager", "Dispatcher", "CommitteeMember",
    "ClaimsAdjuster", "ClaimsManager", "Auditor",
)
REVIEW_READ = (
    "SafetyAdmin", "SafetyManager", "CommitteeMember", "ClaimsAdjuster",
    "ClaimsManager", "Auditor",
)
TERMINAL_READ = (
    "SafetyAdmin", "SafetyManager", "Dispatcher", "ClaimsAdjuster",
    "ClaimsManager", "Auditor",
)
CLAIM_READ = (
    "ClaimsAdjuster", "ClaimsManager", "SafetyManager", "SafetyAdmin", "Auditor",
)
POLICY_READ = ("ClaimsManager", "ClaimsAdjuster", "SafetyAdmin", "Auditor")
SUBRO_READ = ("ClaimsAdjuster", "ClaimsManager", "SafetyAdmin", "Auditor")
DISCIPLINE_READ = ("SafetyAdmin", "SafetyManager", "Auditor")
VOTE_READ = ("SafetyAdmin", "SafetyManager", "CommitteeMember", "Auditor")


def authenticate():
    """Band 1: both headers present, non-empty, role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or role.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a recognized role" % role)
    return user_id, role


def require(*allowed):
    """Bands 1 and 2. Returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed:
        fail("ERR_UNAUTHORIZED", "Role %s is not authorized for this endpoint" % role)
    return user_id, role
