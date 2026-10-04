"""Auth header extraction and role checking (PRD S2.1, scaffold validations 1-2).

Every request carries X-User-ID and X-User-Role. A missing header or an unknown
role is ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400); a known role that is
not permitted for the operation is ERR_INSUFFICIENT_PERMISSIONS (403).
"""

from errors import ApiError

ROLE_NETWORK_ADMIN = "NetworkAdmin"
ROLE_PRACTICE_ADMIN = "PracticeAdmin"
ROLE_REVENUE_CYCLE = "RevenueCycleManager"
ROLE_PAYER_ADJUDICATOR = "PayerAdjudicator"
ROLE_NETWORK_ANALYST = "NetworkAnalyst"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

KNOWN_ROLES = {
    ROLE_NETWORK_ADMIN,
    ROLE_PRACTICE_ADMIN,
    ROLE_REVENUE_CYCLE,
    ROLE_PAYER_ADJUDICATOR,
    ROLE_NETWORK_ANALYST,
    ROLE_PLATFORM_ADMIN,
}

# Roles whose X-User-ID names an opaque operator rather than a persisted entity.
OPAQUE_ROLES = KNOWN_ROLES - {ROLE_PRACTICE_ADMIN}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_practice(self):
        return self.role == ROLE_PRACTICE_ADMIN and self.user_id not in OPAQUE_ROLES


def extract_user(headers):
    user_id = headers.get("X-User-ID")
    role = headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    return Principal(user_id, role)


def check_role(principal, allowed):
    """allowed is None for an operation every authenticated role may perform."""
    if allowed is None:
        return
    if principal.role not in allowed:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS")