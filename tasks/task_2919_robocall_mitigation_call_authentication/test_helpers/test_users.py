"""Test identities and header builders.

Every request carries ``X-User-ID`` and ``X-User-Role``.  Two roles are
entity-backed: a ``ProviderAdmin`` presents the provider's own identifier as
``X-User-ID`` and a ``Caller`` presents the customer's own identifier, so those
two header bundles can only be built once the owning row exists.  Use the
``make_*`` builders for them and never a shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CALLER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FRAUD_ANALYST,
    ROLE_KYC_ANALYST,
    ROLE_POLICY_ADMINISTRATOR,
    ROLE_PROVIDER_ADMIN,
    ROLE_REGULATOR,
)
from .types import Headers

# Non-entity-backed identities.  Two distinct identities exist for each role
# that participates in a segregation-of-duties pair.
REGULATOR_1 = "reg-1"
REGULATOR_2 = "reg-2"
POLICY_ADMIN_1 = "pa-1"
POLICY_ADMIN_2 = "pa-2"
OFFICER_1 = "officer-1"
OFFICER_2 = "officer-2"
OFFICER_7 = "officer-7"
CO_1 = "co-1"
CO_2 = "co-2"
KYC_1 = "kyc-1"
KYC_2 = "kyc-2"
FRAUD_1 = "fraud-1"
FRAUD_2 = "fraud-2"

TEST_USERS = {
    "regulator": {"user_id": REGULATOR_1, "role": ROLE_REGULATOR},
    "regulator_2": {"user_id": REGULATOR_2, "role": ROLE_REGULATOR},
    "policy_admin": {"user_id": POLICY_ADMIN_1, "role": ROLE_POLICY_ADMINISTRATOR},
    "policy_admin_2": {"user_id": POLICY_ADMIN_2, "role": ROLE_POLICY_ADMINISTRATOR},
    "officer_1": {"user_id": OFFICER_1, "role": ROLE_COMPLIANCE_OFFICER},
    "officer_2": {"user_id": OFFICER_2, "role": ROLE_COMPLIANCE_OFFICER},
    "officer_7": {"user_id": OFFICER_7, "role": ROLE_COMPLIANCE_OFFICER},
    "co_1": {"user_id": CO_1, "role": ROLE_COMPLIANCE_OFFICER},
    "co_2": {"user_id": CO_2, "role": ROLE_COMPLIANCE_OFFICER},
    "kyc_1": {"user_id": KYC_1, "role": ROLE_KYC_ANALYST},
    "kyc_2": {"user_id": KYC_2, "role": ROLE_KYC_ANALYST},
    "fraud_1": {"user_id": FRAUD_1, "role": ROLE_FRAUD_ANALYST},
    "fraud_2": {"user_id": FRAUD_2, "role": ROLE_FRAUD_ANALYST},
    # Entity-backed roles have no fixed identifier; see the builders below.
    "provider_admin": {"user_id": None, "role": ROLE_PROVIDER_ADMIN},
    "caller": {"user_id": None, "role": ROLE_CALLER},
}


def headers_for(alias: str) -> Headers:
    """Build headers for one of the fixed identities in ``TEST_USERS``."""
    entry = TEST_USERS[alias]
    if entry["user_id"] is None:
        raise ValueError(
            f"{alias!r} is entity-backed; use make_provider_admin_headers or "
            "make_caller_headers with the owning row's identifier"
        )
    return build_user_headers(entry["user_id"], entry["role"])


# --- Fixed-identity builders ------------------------------------------------


def make_regulator_headers(user_id: str = REGULATOR_1) -> Headers:
    return build_user_headers(user_id, ROLE_REGULATOR)


def make_policy_admin_headers(user_id: str = POLICY_ADMIN_1) -> Headers:
    return build_user_headers(user_id, ROLE_POLICY_ADMINISTRATOR)


def make_compliance_officer_headers(user_id: str = OFFICER_1) -> Headers:
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_kyc_analyst_headers(user_id: str = KYC_1) -> Headers:
    return build_user_headers(user_id, ROLE_KYC_ANALYST)


def make_fraud_analyst_headers(user_id: str = FRAUD_1) -> Headers:
    return build_user_headers(user_id, ROLE_FRAUD_ANALYST)


# --- Entity-backed builders -------------------------------------------------


def make_provider_admin_headers(provider_id: str) -> Headers:
    """Headers for the administrator of ``provider_id`` itself."""
    return build_user_headers(provider_id, ROLE_PROVIDER_ADMIN)


def make_caller_headers(customer_id: str) -> Headers:
    """Headers for the calling customer identified by ``customer_id``."""
    return build_user_headers(customer_id, ROLE_CALLER)


# --- Malformed header bundles for authentication tests ----------------------


def headers_with_blank_role(user_id: str = REGULATOR_1) -> Headers:
    """A present but empty role header."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_with_blank_user_id(role: str = ROLE_REGULATOR) -> Headers:
    """A present but empty user identifier header."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = "aud-1", role: str = "Auditor") -> Headers:
    """A syntactically valid header pair naming a role outside the seven."""
    return build_user_headers(user_id, role)
