"""Operator identities and the request headers that carry them (PRD 2.1).

Every request names an ``X-User-ID`` and an ``X-User-Role``. Each distinct
business owner in a scenario gets its own ``X-User-ID`` so that the three
segregation-of-duties checks of PRD 2.10 are exercised honestly; the one place a
single identifier is deliberately reused across two roles is
``SHARED_OPERATOR``, which exists so that a test can drive an operator into
ruling on their own request.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    HEADER_USER_ID,
    HEADER_USER_ROLE,
    ROLE_COMMITTEE_CHAIR,
    ROLE_CTE_DIRECTOR,
    ROLE_GRANT_FISCAL_OFFICER,
    ROLE_SCHOOL_REGISTRAR,
    ROLE_STATE_COMPLIANCE_REVIEWER,
)
from .types import Headers, UserIdentity

# --- The stock cast --------------------------------------------------------
DIRECTOR = UserIdentity("u_dir_1", ROLE_CTE_DIRECTOR)
DIRECTOR_TWO = UserIdentity("u_dir_2", ROLE_CTE_DIRECTOR)
REVIEWER = UserIdentity("u_rev_1", ROLE_STATE_COMPLIANCE_REVIEWER)
REVIEWER_TWO = UserIdentity("u_rev_2", ROLE_STATE_COMPLIANCE_REVIEWER)
FISCAL_OFFICER = UserIdentity("u_fin_1", ROLE_GRANT_FISCAL_OFFICER)
FISCAL_OFFICER_TWO = UserIdentity("u_fin_2", ROLE_GRANT_FISCAL_OFFICER)
REGISTRAR = UserIdentity("u_reg_1", ROLE_SCHOOL_REGISTRAR)

# One identifier worn by two roles, for the separation-of-duties probes.
SHARED_OPERATOR_ID = "u_shared_1"
SHARED_DIRECTOR = UserIdentity(SHARED_OPERATOR_ID, ROLE_CTE_DIRECTOR)
SHARED_FISCAL_OFFICER = UserIdentity(SHARED_OPERATOR_ID, ROLE_GRANT_FISCAL_OFFICER)
SHARED_REVIEWER = UserIdentity(SHARED_OPERATOR_ID, ROLE_STATE_COMPLIANCE_REVIEWER)


def headers(identity: UserIdentity) -> Headers:
    """Headers for an identity, including the JSON content type."""
    return build_user_headers(identity.user_id, identity.role)


def headers_for(user_id: str, role: str) -> Headers:
    """Headers for a raw identifier and role pair."""
    return build_user_headers(user_id, role)


def chair_identity(member_id: str) -> UserIdentity:
    """The chair acts as the committee member whose ``id`` is ``member_id``."""
    return UserIdentity(member_id, ROLE_COMMITTEE_CHAIR)


def chair_headers(member_id: str) -> Headers:
    """Headers for the seated chair of a committee (PRD 2.1)."""
    return build_user_headers(member_id, ROLE_COMMITTEE_CHAIR)


def blank_user_id_headers(role: str) -> Headers:
    """Headers whose ``X-User-ID`` is present but empty."""
    return {
        HEADER_USER_ID: "",
        HEADER_USER_ROLE: role,
        "Content-Type": "application/json",
    }


def blank_role_headers(user_id: str) -> Headers:
    """Headers whose ``X-User-Role`` is present but empty."""
    return {
        HEADER_USER_ID: user_id,
        HEADER_USER_ROLE: "",
        "Content-Type": "application/json",
    }


def missing_user_id_headers(role: str) -> Headers:
    """Headers with no ``X-User-ID`` key at all."""
    return {HEADER_USER_ROLE: role, "Content-Type": "application/json"}


def missing_role_headers(user_id: str) -> Headers:
    """Headers with no ``X-User-Role`` key at all."""
    return {HEADER_USER_ID: user_id, "Content-Type": "application/json"}


def unknown_role_headers(user_id: str, role: str) -> Headers:
    """Headers naming a role outside the five the system recognises."""
    return {
        HEADER_USER_ID: user_id,
        HEADER_USER_ROLE: role,
        "Content-Type": "application/json",
    }


def override(base: Headers, **changes: Optional[str]) -> Dict[str, str]:
    """A copy of ``base`` with named header values replaced or dropped."""
    merged = dict(base)
    for key, value in changes.items():
        header = key.replace("_", "-")
        if value is None:
            merged.pop(header, None)
        else:
            merged[header] = value
    return merged
