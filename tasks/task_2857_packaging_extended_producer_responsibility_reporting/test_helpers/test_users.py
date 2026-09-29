"""Role headers (PRD 2.1).

`ProgramRegulator` and `IndependentVerifier` carry an opaque `X-User-ID`, so
shared constants are enough for them. `ProducerComplianceOfficer` must carry the
`Producer.id` it acts for and `ProAdministrator` must carry the `Pro.id`, so
those two roles are always built per resource owner.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

REGULATOR_USER_ID = "regulator-001"
REGULATOR_USER_ID_ALT = "regulator-002"
VERIFIER_USER_ID = "verifier-001"
VERIFIER_USER_ID_ALT = "verifier-002"
VERIFIER_USER_ID_THIRD = "verifier-003"

REGULATOR_HEADERS: Dict[str, str] = build_user_headers(
    REGULATOR_USER_ID, UserRole.PROGRAM_REGULATOR
)
REGULATOR_ALT_HEADERS: Dict[str, str] = build_user_headers(
    REGULATOR_USER_ID_ALT, UserRole.PROGRAM_REGULATOR
)
VERIFIER_HEADERS: Dict[str, str] = build_user_headers(
    VERIFIER_USER_ID, UserRole.INDEPENDENT_VERIFIER
)
VERIFIER_ALT_HEADERS: Dict[str, str] = build_user_headers(
    VERIFIER_USER_ID_ALT, UserRole.INDEPENDENT_VERIFIER
)
VERIFIER_THIRD_HEADERS: Dict[str, str] = build_user_headers(
    VERIFIER_USER_ID_THIRD, UserRole.INDEPENDENT_VERIFIER
)


def make_regulator_headers(user_id: str = REGULATOR_USER_ID) -> Dict[str, str]:
    """Headers for a ProgramRegulator; the identifier is opaque."""
    return build_user_headers(user_id, UserRole.PROGRAM_REGULATOR)


def make_producer_compliance_officer_headers(producer_id: str) -> Dict[str, str]:
    """Headers for the officer of one producer; X-User-ID is the Producer.id."""
    return build_user_headers(producer_id, UserRole.PRODUCER_COMPLIANCE_OFFICER)


def make_pro_administrator_headers(pro_id: str) -> Dict[str, str]:
    """Headers for the administrator of one organisation; X-User-ID is the Pro.id."""
    return build_user_headers(pro_id, UserRole.PRO_ADMINISTRATOR)


def make_verifier_headers(verifier_user_id: str = VERIFIER_USER_ID) -> Dict[str, str]:
    """Headers for an IndependentVerifier; the identifier is opaque."""
    return build_user_headers(verifier_user_id, UserRole.INDEPENDENT_VERIFIER)


def headers_without_role(user_id: str = REGULATOR_USER_ID) -> Dict[str, str]:
    """A request that omits X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = UserRole.PROGRAM_REGULATOR) -> Dict[str, str]:
    """A request that omits X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = REGULATOR_USER_ID) -> Dict[str, str]:
    """A request naming a role that is not one of the four declared roles."""
    return build_user_headers(user_id, "Auditor")
