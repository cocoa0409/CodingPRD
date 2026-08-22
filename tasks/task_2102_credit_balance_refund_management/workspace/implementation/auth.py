"""Authentication and RBAC (PRD 2.1); ranks 1 and 2 of the ordering in PRD 2.8."""
from functools import wraps

from flask import g, request

from errors import ApiError

CREDIT_ANALYST = "CreditAnalyst"
REFUND_APPROVER = "RefundApprover"
DISBURSEMENT_OFFICER = "DisbursementOfficer"
COMPLIANCE_OFFICER = "ComplianceOfficer"
PAYER_LIAISON = "PayerLiaison"
SYSTEM_ADMIN = "SystemAdmin"

ALL_ROLES = (
    CREDIT_ANALYST,
    REFUND_APPROVER,
    DISBURSEMENT_OFFICER,
    COMPLIANCE_OFFICER,
    PAYER_LIAISON,
    SYSTEM_ADMIN,
)

KNOWN_ROLES = set(ALL_ROLES)


def require(*roles):
    allowed = set(roles) if roles else set(ALL_ROLES)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in KNOWN_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_user_id():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "role", None)
