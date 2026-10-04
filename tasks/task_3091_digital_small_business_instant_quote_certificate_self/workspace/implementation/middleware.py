"""Auth middleware: X-User-ID / X-User-Role extraction and role checking."""
from flask import request

import errors

ROLES = {
    "Policyholder",
    "Agent",
    "PartnerPlatform",
    "Underwriter",
    "ClaimsAdjuster",
    "FinanceOfficer",
    "ComplianceOfficer",
    "PlatformAdmin",
}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_actor():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return Actor(user_id, role)


def require_role(actor, *roles):
    if actor.role not in roles:
        raise errors.forbidden_role()
    return actor
