"""Identity headers for the six roles of PRD §2.1."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque-identity user ids. The award/execute pair and the two panelists are
# deliberately distinct principals because segregation of duties is enforced on
# X-User-ID equality (PRD §3.4) and the panel requires two distinct panelists
# (PRD §3.3).
ADMIN_USER_ID = "admin-01"
SPECIALIST_USER_ID = "specialist-01"
OFFICER_AWARD_USER_ID = "officer-award-01"
OFFICER_EXEC_USER_ID = "officer-exec-02"
OFFICER_THIRD_USER_ID = "officer-third-03"
PANELIST_ONE_USER_ID = "panelist-01"
PANELIST_TWO_USER_ID = "panelist-02"
PANELIST_THREE_USER_ID = "panelist-03"
AUDITOR_USER_ID = "auditor-01"


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, role)


def admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    return headers_for(UserRole.PROGRAM_ADMINISTRATOR, user_id)


def specialist_headers(user_id: str = SPECIALIST_USER_ID) -> Dict[str, str]:
    return headers_for(UserRole.CONCESSION_SPECIALIST, user_id)


def officer_headers(user_id: str = OFFICER_AWARD_USER_ID) -> Dict[str, str]:
    return headers_for(UserRole.CONTRACTING_OFFICER, user_id)


def award_officer_headers() -> Dict[str, str]:
    return headers_for(UserRole.CONTRACTING_OFFICER, OFFICER_AWARD_USER_ID)


def exec_officer_headers() -> Dict[str, str]:
    return headers_for(UserRole.CONTRACTING_OFFICER, OFFICER_EXEC_USER_ID)


def panelist_headers(user_id: str = PANELIST_ONE_USER_ID) -> Dict[str, str]:
    return headers_for(UserRole.EVALUATION_PANELIST, user_id)


def auditor_headers(user_id: str = AUDITOR_USER_ID) -> Dict[str, str]:
    return headers_for(UserRole.AUDITOR_GENERAL, user_id)


def concessionaire_headers(offeror_id: str) -> Dict[str, str]:
    """For Concessionaire, X-User-ID is the id of the acting Offeror (PRD §2.1)."""
    return headers_for(UserRole.CONCESSIONAIRE, offeror_id)


# Alias used where the offeror-backed identity is the point of the test.
make_concessionaire_headers = concessionaire_headers


def unauthenticated_headers() -> Dict[str, str]:
    return {}


def headers_missing_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id}


def headers_missing_user(role: str = UserRole.PROGRAM_ADMINISTRATOR) -> Dict[str, str]:
    return {"X-User-Role": str(role)}


def headers_for_role_name(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for an arbitrary role name, with a per-role default principal."""
    defaults = {
        UserRole.PROGRAM_ADMINISTRATOR: ADMIN_USER_ID,
        UserRole.CONCESSION_SPECIALIST: SPECIALIST_USER_ID,
        UserRole.CONTRACTING_OFFICER: OFFICER_AWARD_USER_ID,
        UserRole.EVALUATION_PANELIST: PANELIST_ONE_USER_ID,
        UserRole.AUDITOR_GENERAL: AUDITOR_USER_ID,
    }
    if user_id is None:
        user_id = defaults.get(role, "user-01")
    return headers_for(role, user_id)
