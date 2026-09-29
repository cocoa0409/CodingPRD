"""Pre-built authentication headers for every role the API recognises."""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ADMIN_USER_ID = "admin-1"
DIRECTOR_USER_ID = "gad-1"
COMPLIANCE_USER_ID = "co-1"
COMPLIANCE_USER_ID_2 = "co-2"
TRUSTEE_USER_ID = "bt-1"
TRUSTEE_USER_ID_2 = "bt-2"
# One operator identifier used under two different roles, so that the identity
# comparison behind segregation of duties is observable.
DUAL_HAT_USER_ID = "dual-hat-1"
UNKNOWN_ROLE_USER_ID = "aud-1"
UNKNOWN_ROLE = "Auditor"

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque identities: the shared constant is the canonical form.
    "admin_headers": build_user_headers(ADMIN_USER_ID, "AssociationAdmin"),
    "director_headers": build_user_headers(DIRECTOR_USER_ID, "GovAffairsDirector"),
    "compliance_headers": build_user_headers(COMPLIANCE_USER_ID, "ComplianceOfficer"),
    "compliance_headers_2": build_user_headers(COMPLIANCE_USER_ID_2, "ComplianceOfficer"),
    "trustee_headers": build_user_headers(TRUSTEE_USER_ID, "BoardTrustee"),
    "trustee_headers_2": build_user_headers(TRUSTEE_USER_ID_2, "BoardTrustee"),
    # The same operator identifier acting as a director and as a trustee.
    "dual_hat_director_headers": build_user_headers(DUAL_HAT_USER_ID, "GovAffairsDirector"),
    "dual_hat_trustee_headers": build_user_headers(DUAL_HAT_USER_ID, "BoardTrustee"),
    # A role string the system does not recognise.
    "unknown_role_headers": build_user_headers(UNKNOWN_ROLE_USER_ID, UNKNOWN_ROLE),
    # A member delegate whose X-User-ID is not any member's id: only for calls
    # whose outcome does not depend on the caller owning the subject resource.
    "member_delegate_headers": build_user_headers(
        "00000000-0000-0000-0000-000000000000", "MemberDelegate"
    ),
}


def make_member_delegate_headers(member_id: str) -> Dict[str, str]:
    """Headers for a MemberDelegate acting for itself.

    X-User-ID is the id of the acting Member, so pass the real member id
    whenever the call is ownership-gated.
    """
    return build_user_headers(member_id, "MemberDelegate")


def make_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "AssociationAdmin")


def make_director_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "GovAffairsDirector")


def make_compliance_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_trustee_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "BoardTrustee")


def headers_without_user_id(role: str = "AssociationAdmin") -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = "AssociationAdmin") -> Dict[str, str]:
    """Headers whose X-User-ID is the empty string."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers whose X-User-Role is the empty string."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = UNKNOWN_ROLE_USER_ID) -> Dict[str, str]:
    """Headers naming a role the system does not recognise."""
    return build_user_headers(user_id, UNKNOWN_ROLE)


NO_HEADERS: Dict[str, str] = {}
