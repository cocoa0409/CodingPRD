"""Caller identities and header builders.

PRD §2.1: every request carries `X-User-Role` and `X-User-ID`. For a `Seller`
caller the `X-User-ID` must be the id of the acting seller row, so seller
headers are always built from a registered seller id rather than taken from a
fixed constant. Operator identities are opaque strings; two distinct users are
provided for each operator role because the segregation-of-duties rules of §2.7
compare user identifiers.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Operator identities. Two per role so that segregation-of-duties conflicts can
# be both provoked (same user) and avoided (different user).
INVESTIGATOR_USER_ID = "inv-1"
INVESTIGATOR_ALT_USER_ID = "inv-2"
APPEAL_REVIEWER_USER_ID = "ar-1"
APPEAL_REVIEWER_ALT_USER_ID = "ar-2"
COMPLIANCE_OFFICER_USER_ID = "co-1"
COMPLIANCE_OFFICER_ALT_USER_ID = "co-2"

# An identifier that is syntactically a caller but owns nothing.
ANONYMOUS_USER_ID = "anon-1"


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    return build_user_headers(user_id, role)


def make_seller_headers(seller_id: str) -> Dict[str, str]:
    """Seller caller headers; X-User-ID must be the acting seller's id."""
    return build_user_headers(seller_id, Role.SELLER.value)


def make_investigator_headers(user_id: str = INVESTIGATOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.POLICY_INVESTIGATOR.value)


def make_appeal_reviewer_headers(user_id: str = APPEAL_REVIEWER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.APPEAL_REVIEWER.value)


def make_compliance_officer_headers(
    user_id: str = COMPLIANCE_OFFICER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.COMPLIANCE_OFFICER.value)


def make_anonymous_headers() -> Dict[str, str]:
    """PRD §2.1: the Anonymous role is the only one that may omit X-User-ID."""
    return {"X-User-Role": Role.ANONYMOUS.value, "Content-Type": "application/json"}


TEST_USERS: Dict[str, Dict[str, str]] = {
    "investigator_headers": make_investigator_headers(),
    "investigator_alt_headers": make_investigator_headers(INVESTIGATOR_ALT_USER_ID),
    "appeal_reviewer_headers": make_appeal_reviewer_headers(),
    "appeal_reviewer_alt_headers": make_appeal_reviewer_headers(APPEAL_REVIEWER_ALT_USER_ID),
    "compliance_officer_headers": make_compliance_officer_headers(),
    "compliance_officer_alt_headers": make_compliance_officer_headers(
        COMPLIANCE_OFFICER_ALT_USER_ID
    ),
    "anonymous_headers": make_anonymous_headers(),
}

# Convenience aliases used throughout the helpers.
INVESTIGATOR = TEST_USERS["investigator_headers"]
INVESTIGATOR_ALT = TEST_USERS["investigator_alt_headers"]
REVIEWER = TEST_USERS["appeal_reviewer_headers"]
REVIEWER_ALT = TEST_USERS["appeal_reviewer_alt_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
OFFICER_ALT = TEST_USERS["compliance_officer_alt_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]
