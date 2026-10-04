"""Auth context extraction and endpoint-role enforcement (PRD 2.1)."""

from flask import request

from constants import (
    DECLARED_ROLES,
    ROLE_ANY,
    ROLE_BROKER_USER,
    ROLE_CHANNEL_MANAGER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PLATFORM_ADMIN,
    ROLE_QC_ANALYST,
    ROLE_UNDERWRITER,
    BAND_MEETS,
)
from errors import ApiError

ANY_AUTHENTICATED = DECLARED_ROLES


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_broker_user(self):
        return self.role == ROLE_BROKER_USER

    def describe(self):
        return "%s/%s" % (self.role, self.user_id)


def get_caller():
    """Priority 1: both headers must be present and the role must be declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_MISSING_USER_CONTEXT", "The X-User-ID header is required.")
    if not role or not str(role).strip():
        raise ApiError("ERR_MISSING_USER_CONTEXT", "The X-User-Role header is required.")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in DECLARED_ROLES:
        raise ApiError(
            "ERR_MISSING_USER_CONTEXT",
            "X-User-Role names an undeclared role: %s" % role,
        )
    return Caller(user_id, role)


def require_role(caller, allowed):
    """Priority 2: the caller's role must be permitted for the endpoint."""
    if ROLE_ANY in allowed:
        return
    if caller.role in allowed:
        return
    raise ApiError(
        "ERR_INSUFFICIENT_PERMISSIONS",
        "Role %s may not invoke this endpoint." % caller.role,
    )


def require_broker_ownership(caller, broker_id):
    """Priority 31: a BrokerUser may only touch its own brokerage's resources."""
    if caller.role != ROLE_BROKER_USER:
        return
    if caller.user_id != broker_id:
        raise ApiError(
            "ERR_BROKER_RESOURCE_FORBIDDEN",
            "BrokerUser %s may not act for broker %s." % (caller.user_id, broker_id),
        )


# ---------------------------------------------------------------------------
# Endpoint role tables, transcribed from scaffold section 1.5 / 1.7.
# ---------------------------------------------------------------------------
CM = [ROLE_CHANNEL_MANAGER]
ANY = [ROLE_ANY]

ROLE_TABLE = {
    ("POST", "/brokers"): CM,
    ("GET", "/brokers"): ANY,
    ("GET", "/brokers/<broker_id>"): ANY,
    ("GET", "/brokers/<broker_id>/reconciliation"): ANY,
    ("POST", "/brokers/<broker_id>/approve"): CM,
    ("POST", "/brokers/<broker_id>/reinstate"): CM,
    ("POST", "/brokers/<broker_id>/suspend"): CM,
    ("POST", "/brokers/<broker_id>/terminate"): CM,
    ("POST", "/brokers/<broker_id>/licenses"): CM,
    ("GET", "/brokers/<broker_id>/licenses"): ANY,
    ("POST", "/brokers/<broker_id>/licenses/<license_id>/revoke"): [ROLE_COMPLIANCE_OFFICER],
    ("POST", "/brokers/<broker_id>/financial-reviews"): CM,
    ("GET", "/brokers/<broker_id>/financial-reviews"): ANY,
    ("POST", "/financial-reviews/<review_id>/decision"): CM,
    ("POST", "/brokers/<broker_id>/product-eligibilities"): CM,
    ("GET", "/brokers/<broker_id>/product-eligibilities"): ANY,
    ("POST", "/product-eligibilities/<eligibility_id>/decision"): CM,
    ("POST", "/exclusivity-policies"): CM,
    ("GET", "/brokers/<broker_id>/exclusivity-policies"): ANY,
    ("POST", "/exclusivity-policies/<policy_id>/void"): CM,
    ("POST", "/compensation-plans"): CM,
    ("GET", "/brokers/<broker_id>/compensation-plans"): ANY,
    ("GET", "/compensation-plans/<plan_id>"): ANY,
    ("PUT", "/compensation-plans/<plan_id>"): CM,
    ("POST", "/brokers/<broker_id>/rate-sheets"): CM,
    ("GET", "/brokers/<broker_id>/rate-sheets"): ANY,
    ("POST", "/brokers/<broker_id>/rate-sheets/<sheet_id>/retire"): CM,
    ("POST", "/rate-sheets/<sheet_id>/pricing-quotes"): [ROLE_BROKER_USER],
    ("GET", "/rate-sheets/<sheet_id>/pricing-quotes"): ANY,
    ("GET", "/pricing-quotes/<quote_id>"): ANY,
    ("GET", "/pricing-quotes"): ANY,
    ("GET", "/rate-sheets"): ANY,
    ("GET", "/rate-sheets/<sheet_id>"): ANY,
    ("POST", "/loan-submissions"): [ROLE_BROKER_USER],
    ("GET", "/loan-submissions"): ANY,
    ("GET", "/loan-submissions/<loan_id>"): ANY,
    ("POST", "/loan-submissions/<loan_id>/compensation-election"): [ROLE_BROKER_USER],
    ("POST", "/loan-submissions/<loan_id>/underwrite"): [ROLE_UNDERWRITER],
    ("POST", "/loan-submissions/<loan_id>/resubmit"): [ROLE_BROKER_USER],
    ("POST", "/loan-submissions/<loan_id>/withdraw"): [ROLE_BROKER_USER],
    ("POST", "/loan-submissions/<loan_id>/clear-to-close"): [ROLE_UNDERWRITER],
    ("POST", "/loan-submissions/<loan_id>/fund"): [ROLE_UNDERWRITER],
    ("GET", "/closing-pipeline"): ANY,
    ("POST", "/underwriting-decisions"): [ROLE_UNDERWRITER],
    ("GET", "/loan-submissions/<loan_id>/underwriting-decisions"): ANY,
    ("GET", "/brokers/<broker_id>/underwriting-decisions"): ANY,
    ("GET", "/loan-submissions/<loan_id>/turn-time-escalations"): ANY,
    ("GET", "/brokers/<broker_id>/turn-time-escalations"): ANY,
    ("POST", "/turn-time-escalations/<escalation_id>/resolve"): CM,
    ("POST", "/quality-control-reviews"): [ROLE_QC_ANALYST],
    ("GET", "/brokers/<broker_id>/quality-control-reviews"): ANY,
    ("GET", "/loan-submissions/<loan_id>/quality-control-reviews"): ANY,
    ("GET", "/quality-control-reviews"): ANY,
    ("POST", "/quality-control-reviews/<review_id>/resolve"): [ROLE_QC_ANALYST],
    ("POST", "/quality-control-reviews/<review_id>/repurchase"): [ROLE_QC_ANALYST],
    ("POST", "/_clock/set_current_utc"): [ROLE_PLATFORM_ADMIN],
}

MEETS_BAND = BAND_MEETS