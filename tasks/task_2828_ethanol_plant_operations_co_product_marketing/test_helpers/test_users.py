"""
The eight opaque operating identities of PRD section 2.1.

`X-User-ID` is an opaque operator identifier that is never compared with any
entity id, so each role simply gets a stable, distinct identifier string.  Two
segregations of duty need *two* identities to be distinguishable, so the scale
house and grain accounting identifiers are deliberately different, as are the
compliance officer's and the plant manager's.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_GRAIN_ACCOUNTANT,
    ROLE_GRAIN_BUYER,
    ROLE_LOGISTICS_COORDINATOR,
    ROLE_PLANT_MANAGER,
    ROLE_PROCESS_OPERATOR,
    ROLE_RISK_MANAGER,
    ROLE_SCALE_OPERATOR,
)

USER_PLANT_MANAGER = "pm-01"
USER_GRAIN_BUYER = "gb-01"
USER_SCALE_OPERATOR = "scale-01"
USER_SCALE_OPERATOR_ALT = "scale-02"
USER_GRAIN_ACCOUNTANT = "acct-01"
USER_PROCESS_OPERATOR = "op-01"
USER_LOGISTICS_COORDINATOR = "log-01"
USER_COMPLIANCE_OFFICER = "co-01"
USER_RISK_MANAGER = "risk-01"

PLANT_MANAGER = build_user_headers(USER_PLANT_MANAGER, ROLE_PLANT_MANAGER)
GRAIN_BUYER = build_user_headers(USER_GRAIN_BUYER, ROLE_GRAIN_BUYER)
SCALE_OPERATOR = build_user_headers(USER_SCALE_OPERATOR, ROLE_SCALE_OPERATOR)
SCALE_OPERATOR_ALT = build_user_headers(USER_SCALE_OPERATOR_ALT, ROLE_SCALE_OPERATOR)
GRAIN_ACCOUNTANT = build_user_headers(USER_GRAIN_ACCOUNTANT, ROLE_GRAIN_ACCOUNTANT)
PROCESS_OPERATOR = build_user_headers(USER_PROCESS_OPERATOR, ROLE_PROCESS_OPERATOR)
LOGISTICS_COORDINATOR = build_user_headers(
    USER_LOGISTICS_COORDINATOR, ROLE_LOGISTICS_COORDINATOR
)
COMPLIANCE_OFFICER = build_user_headers(USER_COMPLIANCE_OFFICER, ROLE_COMPLIANCE_OFFICER)
RISK_MANAGER = build_user_headers(USER_RISK_MANAGER, ROLE_RISK_MANAGER)

# A GrainAccountant whose X-User-ID collides with the scale house identity that
# graded the load — used to exercise the settlement segregation of duties.
GRAIN_ACCOUNTANT_AS_GRADER = build_user_headers(
    USER_SCALE_OPERATOR, ROLE_GRAIN_ACCOUNTANT
)

TEST_USERS = {
    ROLE_PLANT_MANAGER: PLANT_MANAGER,
    ROLE_GRAIN_BUYER: GRAIN_BUYER,
    ROLE_SCALE_OPERATOR: SCALE_OPERATOR,
    ROLE_GRAIN_ACCOUNTANT: GRAIN_ACCOUNTANT,
    ROLE_PROCESS_OPERATOR: PROCESS_OPERATOR,
    ROLE_LOGISTICS_COORDINATOR: LOGISTICS_COORDINATOR,
    ROLE_COMPLIANCE_OFFICER: COMPLIANCE_OFFICER,
    ROLE_RISK_MANAGER: RISK_MANAGER,
}

NO_HEADERS = {"Content-Type": "application/json"}
ROLE_ONLY_HEADERS = {
    "X-User-Role": ROLE_PLANT_MANAGER,
    "Content-Type": "application/json",
}


def headers_for(role: str) -> dict:
    """Return the standard header dict for one of the eight roles."""
    return TEST_USERS[role]


def headers_with_unknown_role(role: str) -> dict:
    """Header dict carrying a syntactically valid but unrecognised role string."""
    return build_user_headers(USER_PLANT_MANAGER, role)
