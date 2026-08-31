"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID, ANALYST_USER_ID, FUNDER_USER_ID, COMPLIANCE_USER_ID,
)

# Shared constants. The four opaque roles never have their X-User-ID compared
# to any entity id, so a shared constant is the canonical form for them.
# The DealerPrincipal entry is a fallback for calls that never reach an
# ownership check (bad payloads, unknown paths); ownership-gated calls must
# use make_dealer_principal_headers() with the real dealership id.
TEST_USERS = {
    "portfolio_admin_headers": build_user_headers(ADMIN_USER_ID, "PortfolioAdmin"),
    "credit_analyst_headers": build_user_headers(ANALYST_USER_ID, "CreditAnalyst"),
    "funding_specialist_headers": build_user_headers(FUNDER_USER_ID, "FundingSpecialist"),
    "compliance_officer_headers": build_user_headers(COMPLIANCE_USER_ID, "ComplianceOfficer"),
    "dealer_principal_headers": build_user_headers("dp-unbound", "DealerPrincipal"),
}


def make_dealer_principal_headers(dealer_id: str) -> dict:
    """For DealerPrincipal, whose X-User-ID is the id of the acting Dealer.

    Pass the actual dealership id whenever the call is ownership-gated.
    """
    return build_user_headers(dealer_id, "DealerPrincipal")


def make_credit_analyst_headers(user_id: str = ANALYST_USER_ID) -> dict:
    return build_user_headers(user_id, "CreditAnalyst")


def make_funding_specialist_headers(user_id: str = FUNDER_USER_ID) -> dict:
    return build_user_headers(user_id, "FundingSpecialist")


def make_portfolio_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PortfolioAdmin")


def make_compliance_officer_headers(user_id: str = COMPLIANCE_USER_ID) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


ADMIN = TEST_USERS["portfolio_admin_headers"]
ANALYST = TEST_USERS["credit_analyst_headers"]
FUNDER = TEST_USERS["funding_specialist_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
