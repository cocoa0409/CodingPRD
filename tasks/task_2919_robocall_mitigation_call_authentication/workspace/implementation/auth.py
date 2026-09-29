"""Authentication, role authorisation and ownership (PRD 2.1, 2.8 steps 1/2/8)."""
from functools import wraps

from flask import g, request

import errors
from store import db

REGULATOR = "Regulator"
POLICY_ADMINISTRATOR = "PolicyAdministrator"
COMPLIANCE_OFFICER = "ComplianceOfficer"
KYC_ANALYST = "KycAnalyst"
FRAUD_ANALYST = "FraudAnalyst"
PROVIDER_ADMIN = "ProviderAdmin"
CALLER = "Caller"

ALL_ROLES = (
    REGULATOR, POLICY_ADMINISTRATOR, COMPLIANCE_OFFICER, KYC_ANALYST,
    FRAUD_ANALYST, PROVIDER_ADMIN, CALLER,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or not user_id.strip():
        errors.fail(errors.ERR_UNAUTHENTICATED, "X-User-ID header is required")
    if role is None or not role.strip():
        errors.fail(errors.ERR_UNAUTHENTICATED, "X-User-Role header is required")
    if role not in ALL_ROLES:
        errors.fail(errors.ERR_UNAUTHENTICATED, "X-User-Role is not a declared role")
    return user_id, role


def require(*roles):
    """Step 1 authentication then step 2 role authorisation."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            g.user_id = user_id
            g.role = role
            if role not in roles:
                errors.fail(errors.ERR_UNAUTHORIZED,
                            "Role %s may not call this operation" % role)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def acting_id():
    return g.user_id


def acting_role():
    return g.role


def own_provider(provider_id):
    """Step 8: a ProviderAdmin may only act on its own provider's rows."""
    if g.role == PROVIDER_ADMIN and provider_id != g.user_id:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER,
                    "The acting provider does not own this resource")


def own_customer(customer_id):
    """Step 8: a Caller may only act on its own customer's rows."""
    if g.role == CALLER and customer_id != g.user_id:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER,
                    "The acting caller does not own this resource")


def own(provider_id=None, customer_id=None):
    if g.role == PROVIDER_ADMIN:
        if provider_id is None:
            errors.fail(errors.ERR_NOT_RESOURCE_OWNER,
                        "The acting provider does not own this resource")
        own_provider(provider_id)
    elif g.role == CALLER:
        if customer_id is None:
            errors.fail(errors.ERR_NOT_RESOURCE_OWNER,
                        "The acting caller does not own this resource")
        own_customer(customer_id)


def dispute_provider_id(dispute):
    event = db.blocking_events.get(dispute.get("blocking_event_id"))
    return event["provider_id"] if event else None


def scope_rows(rows, provider_of=None, customer_of=None):
    """Read scoping for the two entity-backed roles (PRD 2.1)."""
    if g.role == PROVIDER_ADMIN and provider_of is not None:
        return [r for r in rows if provider_of(r) == g.user_id]
    if g.role == CALLER and customer_of is not None:
        return [r for r in rows if customer_of(r) == g.user_id]
    return list(rows)
