"""Authentication (priority 1), role authorization (priority 2), path and body
existence (priorities 3 and 4) and entity-backed identity scope (priority 5)."""

from flask import g, request

import store
from errors import ApiError

ROLE_CONSORTIUM_ADMIN = "ConsortiumAdmin"
ROLE_MEMBER_LIBRARIAN = "MemberLibrarian"
ROLE_LICENSE_NEGOTIATOR = "LicenseNegotiator"
ROLE_VENDOR_REP = "VendorRep"
ROLE_ACCESS_ENGINEER = "AccessEngineer"

ALL_ROLES = (
    ROLE_CONSORTIUM_ADMIN,
    ROLE_MEMBER_LIBRARIAN,
    ROLE_LICENSE_NEGOTIATOR,
    ROLE_VENDOR_REP,
    ROLE_ACCESS_ENGINEER,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def authenticate():
    """Priority 1. Both headers present and non-empty; role one of the five."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    """Priority 2."""
    if g.get("role") not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")


def user_id():
    return g.get("user_id")


def role():
    return g.get("role")


# --------------------------------------------------------------------------- #
# existence lookups (priority 3 for path segments, priority 4 for body FKs)
# --------------------------------------------------------------------------- #
def _lookup(collection, key, error_id):
    if not isinstance(key, str) or key not in collection:
        raise ApiError(error_id)
    return collection[key]


def get_member(member_id):
    return _lookup(store.members, member_id, "ERR_MEMBER_NOT_FOUND")


def get_vendor(vendor_id):
    return _lookup(store.vendors, vendor_id, "ERR_VENDOR_NOT_FOUND")


def get_product(product_id):
    return _lookup(store.products, product_id, "ERR_PRODUCT_NOT_FOUND")


def get_trial(trial_id):
    return _lookup(store.trials, trial_id, "ERR_TRIAL_NOT_FOUND")


def get_negotiation(negotiation_id):
    return _lookup(store.negotiations, negotiation_id, "ERR_NEGOTIATION_NOT_FOUND")


def get_subscription(subscription_id):
    return _lookup(store.subscriptions, subscription_id, "ERR_SUBSCRIPTION_NOT_FOUND")


def get_commitment(commitment_id):
    return _lookup(store.commitments, commitment_id, "ERR_COMMITMENT_NOT_FOUND")


def get_auth_config(auth_config_id):
    return _lookup(store.auth_configs, auth_config_id, "ERR_AUTH_CONFIG_NOT_FOUND")


def get_incident(incident_id):
    return _lookup(store.access_incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")


def get_usage_report(usage_report_id):
    return _lookup(store.usage_reports, usage_report_id, "ERR_USAGE_REPORT_NOT_FOUND")


def get_renewal_decision(decision_id):
    return _lookup(store.renewal_decisions, decision_id, "ERR_RENEWAL_DECISION_NOT_FOUND")


def get_archival_check(check_id):
    return _lookup(store.archival_checks, check_id, "ERR_ARCHIVAL_CHECK_NOT_FOUND")


# --------------------------------------------------------------------------- #
# priority 5 - entity-backed identity scope
# --------------------------------------------------------------------------- #
def require_member_scope(member_id):
    """A MemberLibrarian's X-User-ID must equal the member the request targets."""
    if role() == ROLE_MEMBER_LIBRARIAN and member_id != user_id():
        raise ApiError("ERR_MEMBER_SCOPE_VIOLATION")


def require_vendor_scope(product):
    """A VendorRep's X-User-ID must equal the vendor_id of the product behind
    the targeted resource."""
    if role() == ROLE_VENDOR_REP and product.get("vendor_id") != user_id():
        raise ApiError("ERR_VENDOR_SCOPE_VIOLATION")
