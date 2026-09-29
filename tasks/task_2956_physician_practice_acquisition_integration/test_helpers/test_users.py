"""Auth header identities for the Practice Acquisition Integration API.

Five of the six roles are opaque identities: any stable string works as the
`X-User-ID`, so each gets a shared pre-built header dict. `PracticePhysician`
is entity-backed — its `X-User-ID` must be the id of an actual Physician row —
so it has no shared constant and must always be built per instance with
`make_practice_physician_headers(physician_id)`.

Distinct owners always get distinct user ids: `va-1` / `va-2` for the two
valuation analysts and `co-1` / `co-2` for the two compliance officers, so the
segregation-of-duties rules can be exercised without aliasing two people onto
one identity.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPENSATION_DESIGNER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DEAL_LEAD,
    ROLE_INTEGRATION_MANAGER,
    ROLE_PRACTICE_PHYSICIAN,
    ROLE_VALUATION_ANALYST,
    USER_COMPENSATION_DESIGNER,
    USER_COMPLIANCE_OFFICER,
    USER_COMPLIANCE_OFFICER_ALT,
    USER_DEAL_LEAD,
    USER_INTEGRATION_MANAGER,
    USER_VALUATION_ANALYST,
    USER_VALUATION_ANALYST_ALT,
)

Headers = Dict[str, str]


# --- Per-instance builders --------------------------------------------------


def make_deal_lead_headers(user_id: str = USER_DEAL_LEAD) -> Headers:
    return build_user_headers(user_id, ROLE_DEAL_LEAD)


def make_valuation_analyst_headers(user_id: str = USER_VALUATION_ANALYST) -> Headers:
    return build_user_headers(user_id, ROLE_VALUATION_ANALYST)


def make_compensation_designer_headers(
    user_id: str = USER_COMPENSATION_DESIGNER,
) -> Headers:
    return build_user_headers(user_id, ROLE_COMPENSATION_DESIGNER)


def make_compliance_officer_headers(user_id: str = USER_COMPLIANCE_OFFICER) -> Headers:
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_integration_manager_headers(
    user_id: str = USER_INTEGRATION_MANAGER,
) -> Headers:
    return build_user_headers(user_id, ROLE_INTEGRATION_MANAGER)


def make_practice_physician_headers(physician_id: str) -> Headers:
    """`X-User-ID` for this role is the Physician entity id, never an opaque string."""
    return build_user_headers(physician_id, ROLE_PRACTICE_PHYSICIAN)


def make_headers(user_id: str, role: str) -> Headers:
    """Escape hatch for auth tests that need an arbitrary id/role pairing."""
    return build_user_headers(user_id, role)


# --- Shared identities for the opaque roles --------------------------------

TEST_USERS: Dict[str, object] = {
    "deal_lead_id": USER_DEAL_LEAD,
    "valuation_analyst_id": USER_VALUATION_ANALYST,
    "valuation_analyst_alt_id": USER_VALUATION_ANALYST_ALT,
    "compliance_officer_id": USER_COMPLIANCE_OFFICER,
    "compliance_officer_alt_id": USER_COMPLIANCE_OFFICER_ALT,
    "compensation_designer_id": USER_COMPENSATION_DESIGNER,
    "integration_manager_id": USER_INTEGRATION_MANAGER,
    "deal_lead_headers": make_deal_lead_headers(),
    "valuation_analyst_headers": make_valuation_analyst_headers(),
    "valuation_analyst_alt_headers": make_valuation_analyst_headers(
        USER_VALUATION_ANALYST_ALT
    ),
    "compliance_officer_headers": make_compliance_officer_headers(),
    "compliance_officer_alt_headers": make_compliance_officer_headers(
        USER_COMPLIANCE_OFFICER_ALT
    ),
    "compensation_designer_headers": make_compensation_designer_headers(),
    "integration_manager_headers": make_integration_manager_headers(),
}


# --- Malformed auth headers -------------------------------------------------
# A blank value must be sent as the empty string. A space-only header value is
# rejected by the HTTP client before the request is ever put on the wire, so it
# could never reach the API under test.

NO_USER_ID_HEADERS: Headers = {
    "X-User-Role": ROLE_PRACTICE_PHYSICIAN,
    "Content-Type": "application/json",
}

EMPTY_USER_ID_HEADERS: Headers = {
    "X-User-ID": "",
    "X-User-Role": ROLE_DEAL_LEAD,
    "Content-Type": "application/json",
}

NO_ROLE_HEADERS: Headers = {
    "X-User-ID": USER_DEAL_LEAD,
    "Content-Type": "application/json",
}

EMPTY_ROLE_HEADERS: Headers = {
    "X-User-ID": USER_DEAL_LEAD,
    "X-User-Role": "",
    "Content-Type": "application/json",
}

UNRECOGNISED_ROLE_HEADERS: Headers = {
    "X-User-ID": USER_DEAL_LEAD,
    "X-User-Role": "PracticeAdministrator",
    "Content-Type": "application/json",
}

NO_AUTH_HEADERS: Headers = {"Content-Type": "application/json"}
