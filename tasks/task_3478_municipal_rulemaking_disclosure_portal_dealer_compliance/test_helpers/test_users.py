"""Caller identities and header builders for the eleven roles (PRD section 2.1).

Two roles are entity-backed: an ``IssuerRep`` or ``DealerRep`` request is
authenticated by an ``X-User-ID`` that IS the acting Organization's ``id``.
Headers for those roles can therefore only be built once the backing
organization exists - always via ``make_issuer_rep_headers(org["id"])`` /
``make_dealer_rep_headers(org["id"])``; the shared ``TEST_USERS`` fallbacks for
these two roles are for tests that never exercise ownership.

The other nine roles are opaque: any stable identifier serves. Segregation-of-
duties rules (PRD sections 2.5, 3.1, 3.8) compare user identifiers within the
Regulator and ComplianceOfficer roles, so those cohorts carry two identities
each, and builders are provided for arbitrary extra identities.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole


# --- Opaque identities ---------------------------------------------------------

OFFICER_1_ID = "officer-1"
OFFICER_2_ID = "officer-2"
REGULATOR_1_ID = "regulator-1"
REGULATOR_2_ID = "regulator-2"
PORTAL_OPERATOR_1_ID = "portal-operator-1"
COMPLIANCE_OFFICER_1_ID = "co-1"
COMPLIANCE_OFFICER_2_ID = "co-2"
EXAM_ADMIN_1_ID = "exam-admin-1"
LICENSING_OFFICER_1_ID = "licensing-officer-1"
SYSTEM_ADMIN_1_ID = "system-admin-1"
PUBLIC_READER_1_ID = "public-reader-1"
MARKET_DATA_SUBSCRIBER_1_ID = "sub-1"


# Shared header sets. Safe for every opaque role; for the two entity-backed
# roles these are fallbacks for tests that do not exercise ownership only.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "system_admin_headers": build_user_headers(SYSTEM_ADMIN_1_ID, UserRole.SYSTEM_ADMIN.value),
    "rulemaking_officer_headers": build_user_headers(OFFICER_1_ID, UserRole.RULEMAKING_OFFICER.value),
    "rulemaking_officer_alt_headers": build_user_headers(OFFICER_2_ID, UserRole.RULEMAKING_OFFICER.value),
    "regulator_headers": build_user_headers(REGULATOR_1_ID, UserRole.REGULATOR.value),
    "regulator_alt_headers": build_user_headers(REGULATOR_2_ID, UserRole.REGULATOR.value),
    "portal_operator_headers": build_user_headers(PORTAL_OPERATOR_1_ID, UserRole.PORTAL_OPERATOR.value),
    "compliance_officer_headers": build_user_headers(COMPLIANCE_OFFICER_1_ID, UserRole.COMPLIANCE_OFFICER.value),
    "compliance_officer_alt_headers": build_user_headers(COMPLIANCE_OFFICER_2_ID, UserRole.COMPLIANCE_OFFICER.value),
    "exam_admin_headers": build_user_headers(EXAM_ADMIN_1_ID, UserRole.EXAM_ADMIN.value),
    "licensing_officer_headers": build_user_headers(LICENSING_OFFICER_1_ID, UserRole.LICENSING_OFFICER.value),
    "public_reader_headers": build_user_headers(PUBLIC_READER_1_ID, UserRole.PUBLIC_READER.value),
    "market_data_subscriber_headers": build_user_headers(
        MARKET_DATA_SUBSCRIBER_1_ID, UserRole.MARKET_DATA_SUBSCRIBER.value
    ),
    # Entity-backed fallbacks: non-ownership tests only. The identifier below
    # never equals a real Organization.id, so any ownership-gated call made
    # with these headers is rejected by the contract's ownership comparison.
    "issuer_rep_headers": build_user_headers("issuer-rep-unbound-1", UserRole.ISSUER_REP.value),
    "dealer_rep_headers": build_user_headers("dealer-rep-unbound-1", UserRole.DEALER_REP.value),
}


# --- Per-instance builders ------------------------------------------------------

def make_issuer_rep_headers(org_id: str) -> Dict[str, str]:
    """IssuerRep headers whose X-User-ID is the filing Organization.id.

    Mandatory for every ownership-gated call (filing a disclosure, scoped
    submission reads): the contract requires X-User-ID == issuer_org_id.
    """
    return build_user_headers(org_id, UserRole.ISSUER_REP.value)


def make_dealer_rep_headers(org_id: str) -> Dict[str, str]:
    """DealerRep headers whose X-User-ID is the firm Organization.id.

    Mandatory for every ownership-gated call (trade reporting and cancel,
    solicitation logging, scoped trade/solicitation reads).
    """
    return build_user_headers(org_id, UserRole.DEALER_REP.value)


def make_rulemaking_officer_headers(user_id: str = OFFICER_1_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.RULEMAKING_OFFICER.value)


def make_regulator_headers(user_id: str = REGULATOR_1_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.REGULATOR.value)


def make_compliance_officer_headers(user_id: str = COMPLIANCE_OFFICER_1_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_portal_operator_headers(user_id: str = PORTAL_OPERATOR_1_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PORTAL_OPERATOR.value)


def make_exam_admin_headers(user_id: str = EXAM_ADMIN_1_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.EXAM_ADMIN.value)


def make_licensing_officer_headers(user_id: str = LICENSING_OFFICER_1_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.LICENSING_OFFICER.value)


def make_system_admin_headers(user_id: str = SYSTEM_ADMIN_1_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.SYSTEM_ADMIN.value)


def make_public_reader_headers(user_id: str = PUBLIC_READER_1_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PUBLIC_READER.value)


def make_market_data_subscriber_headers(subscriber_principal: str) -> Dict[str, str]:
    """MarketDataSubscriber headers; X-User-ID must equal an ACTIVE
    subscription's subscriber_principal for the requested product."""
    return build_user_headers(subscriber_principal, UserRole.MARKET_DATA_SUBSCRIBER.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary (identifier, role) pair."""
    return build_user_headers(user_id, role)


# --- Malformed credentials (PRD sections 2.1, 2.5 step 1) ------------------------

def headers_without_user_id(role: str = UserRole.PUBLIC_READER.value) -> Dict[str, str]:
    """Omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = "some-user-1") -> Dict[str, str]:
    """Omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_blank_user_id(role: str = UserRole.PUBLIC_READER.value) -> Dict[str, str]:
    """Send a blank X-User-ID."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_blank_role(user_id: str = "some-user-1") -> Dict[str, str]:
    """Send a blank X-User-Role."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_without_credentials() -> Dict[str, str]:
    """Send neither credential header."""
    return {"Content-Type": "application/json"}
