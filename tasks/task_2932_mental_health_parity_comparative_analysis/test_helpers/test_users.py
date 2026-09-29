"""Identity headers for every declared role.

Two of the four roles are backed by a stored entity in this domain: an
`Administrator` acts under the identifier of its own row, so the Administrator
header builder takes the administrator id created during setup rather than a
fixed literal.  The other three roles are free-standing user identifiers.

Distinct actors always get DISTINCT `X-User-ID` values so that
segregation-of-duties rules (self-certification, approver-is-determiner) can be
exercised truthfully.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ADMINISTRATOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PLAN_SPONSOR,
    ROLE_REGULATOR,
    UNDECLARED_ROLE,
)

# ─── Canonical user identifiers ───────────────────────────────────────────────

SPONSOR_USER_ID = "user-sponsor-01"
SPONSOR_USER_ID_ALT = "user-sponsor-02"
OFFICER_USER_ID = "user-officer-01"
OFFICER_USER_ID_ALT = "user-officer-02"
REGULATOR_USER_ID = "user-regulator-01"
REGULATOR_USER_ID_ALT = "user-regulator-02"

TEST_USERS = {
    "plan_sponsor": {"user_id": SPONSOR_USER_ID, "role": ROLE_PLAN_SPONSOR},
    "plan_sponsor_alt": {"user_id": SPONSOR_USER_ID_ALT, "role": ROLE_PLAN_SPONSOR},
    "compliance_officer": {"user_id": OFFICER_USER_ID, "role": ROLE_COMPLIANCE_OFFICER},
    "compliance_officer_alt": {"user_id": OFFICER_USER_ID_ALT, "role": ROLE_COMPLIANCE_OFFICER},
    "regulator": {"user_id": REGULATOR_USER_ID, "role": ROLE_REGULATOR},
    "regulator_alt": {"user_id": REGULATOR_USER_ID_ALT, "role": ROLE_REGULATOR},
}


# ─── Per-role header builders ─────────────────────────────────────────────────


def make_sponsor_headers(user_id: str = SPONSOR_USER_ID) -> Dict[str, str]:
    """Headers for a PlanSponsor actor."""
    return build_user_headers(user_id, ROLE_PLAN_SPONSOR)


def make_administrator_headers(administrator_id: str) -> Dict[str, str]:
    """Headers for an Administrator actor.

    The Administrator role is entity-backed: the acting identifier is the id of
    the Administrator row itself, so callers must pass the id returned by the
    administrator-create call.
    """
    return build_user_headers(administrator_id, ROLE_ADMINISTRATOR)


def make_officer_headers(user_id: str = OFFICER_USER_ID) -> Dict[str, str]:
    """Headers for a ComplianceOfficer actor."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_regulator_headers(user_id: str = REGULATOR_USER_ID) -> Dict[str, str]:
    """Headers for a Regulator actor."""
    return build_user_headers(user_id, ROLE_REGULATOR)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary (user_id, role) pair."""
    return build_user_headers(user_id, role)


# ─── Malformed-identity builders ──────────────────────────────────────────────


def make_blank_user_id_headers(role: str = ROLE_PLAN_SPONSOR) -> Dict[str, str]:
    """Headers whose `X-User-ID` is genuinely empty.

    The value must be `""` and never whitespace: a whitespace-only header value
    is rejected client-side by the HTTP library before the request is ever sent.
    """
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def make_missing_role_headers(user_id: str = SPONSOR_USER_ID) -> Dict[str, str]:
    """Headers with `X-User-Role` omitted entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_missing_user_id_headers(role: str = ROLE_PLAN_SPONSOR) -> Dict[str, str]:
    """Headers with `X-User-ID` omitted entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_unknown_role_headers(
    user_id: str = SPONSOR_USER_ID, role: str = UNDECLARED_ROLE
) -> Dict[str, str]:
    """Headers naming a role that is not one of the four declared roles."""
    return build_user_headers(user_id, role)
