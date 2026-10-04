"""Auth header extraction and role checking per PRD section 2.1."""
from flask import request

from response import err_unauthenticated, err_forbidden

ROLES = {
    "FranchiseeOwner",
    "BrokerOfRecord",
    "ManagingBroker",
    "Agent",
    "TrustAccountant",
    "ComplianceAuditor",
    "PlatformAdmin",
}

ALL_ROLES = [
    "FranchiseeOwner", "BrokerOfRecord", "ManagingBroker", "Agent",
    "TrustAccountant", "ComplianceAuditor", "PlatformAdmin",
]


def get_identity():
    """Returns (user_id, role) or raises ERR_UNAUTHENTICATED."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    return uid, role


def require_roles(*allowed):
    uid, role = get_identity()
    if role not in allowed:
        raise err_forbidden()
    return uid, role
