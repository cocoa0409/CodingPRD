"""Auth headers for every role.

PRD §2.1 says identity is opaque: the API never validates the ``X-User-ID``
against a directory, it only records it and compares it against another
recorded identifier for the segregation-of-duties checks. That is why each role
gets a primary header set plus a distinct second identity, so a test can act as
two different people holding the same role.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BREWERY_ADMIN,
    ROLE_CELLAR_OPERATOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_STATE_REGULATOR,
    ROLE_TAPROOM_STAFF,
)

# --- Opaque user identifiers ----------------------------------------------
USER_ADMIN_1 = "u_admin_1"
USER_ADMIN_2 = "u_admin_2"
USER_COMPLIANCE_1 = "u_compliance_1"
USER_COMPLIANCE_2 = "u_compliance_2"
USER_CELLAR_1 = "u_cellar_1"
USER_CELLAR_2 = "u_cellar_2"
USER_TAPROOM_1 = "u_taproom_1"
USER_TAPROOM_2 = "u_taproom_2"
USER_REGULATOR_1 = "u_regulator_1"
USER_REGULATOR_2 = "u_regulator_2"

TEST_USERS = {
    "admin_1": (USER_ADMIN_1, ROLE_BREWERY_ADMIN),
    "admin_2": (USER_ADMIN_2, ROLE_BREWERY_ADMIN),
    "compliance_1": (USER_COMPLIANCE_1, ROLE_COMPLIANCE_OFFICER),
    "compliance_2": (USER_COMPLIANCE_2, ROLE_COMPLIANCE_OFFICER),
    "cellar_1": (USER_CELLAR_1, ROLE_CELLAR_OPERATOR),
    "cellar_2": (USER_CELLAR_2, ROLE_CELLAR_OPERATOR),
    "taproom_1": (USER_TAPROOM_1, ROLE_TAPROOM_STAFF),
    "taproom_2": (USER_TAPROOM_2, ROLE_TAPROOM_STAFF),
    "regulator_1": (USER_REGULATOR_1, ROLE_STATE_REGULATOR),
    "regulator_2": (USER_REGULATOR_2, ROLE_STATE_REGULATOR),
}

# --- Ready-made header dicts ----------------------------------------------
ADMIN = build_user_headers(USER_ADMIN_1, ROLE_BREWERY_ADMIN)
ADMIN_2 = build_user_headers(USER_ADMIN_2, ROLE_BREWERY_ADMIN)
COMPLIANCE = build_user_headers(USER_COMPLIANCE_1, ROLE_COMPLIANCE_OFFICER)
COMPLIANCE_2 = build_user_headers(USER_COMPLIANCE_2, ROLE_COMPLIANCE_OFFICER)
CELLAR = build_user_headers(USER_CELLAR_1, ROLE_CELLAR_OPERATOR)
CELLAR_2 = build_user_headers(USER_CELLAR_2, ROLE_CELLAR_OPERATOR)
TAPROOM = build_user_headers(USER_TAPROOM_1, ROLE_TAPROOM_STAFF)
TAPROOM_2 = build_user_headers(USER_TAPROOM_2, ROLE_TAPROOM_STAFF)
REGULATOR = build_user_headers(USER_REGULATOR_1, ROLE_STATE_REGULATOR)
REGULATOR_2 = build_user_headers(USER_REGULATOR_2, ROLE_STATE_REGULATOR)

HEADERS_BY_ROLE = {
    ROLE_BREWERY_ADMIN: ADMIN,
    ROLE_COMPLIANCE_OFFICER: COMPLIANCE,
    ROLE_CELLAR_OPERATOR: CELLAR,
    ROLE_TAPROOM_STAFF: TAPROOM,
    ROLE_STATE_REGULATOR: REGULATOR,
}


def headers_for(role: str, user_id: str = "u_generic_1") -> dict:
    """Build headers for an arbitrary role/identity pairing."""
    return build_user_headers(user_id, role)


def headers_missing_role(user_id: str = USER_ADMIN_1) -> dict:
    """Headers carrying an identity but no ``X-User-Role`` at all (§2.1)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user_id(role: str = ROLE_BREWERY_ADMIN) -> dict:
    """Headers carrying a role but no ``X-User-ID`` at all (§2.1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_blank_role(user_id: str = USER_ADMIN_1) -> dict:
    """Headers whose role is the empty string.

    PRD §2.1: "A header supplied as an empty string counts as absent." The
    value must be exactly ``""`` and never a spaces-only string, because a
    whitespace value is rejected client-side before the request is sent.
    """
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_blank_user_id(role: str = ROLE_BREWERY_ADMIN) -> dict:
    """Headers whose identity is the empty string (§2.1)."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_unknown_role(user_id: str = USER_ADMIN_1) -> dict:
    """Headers naming a role that is not one of the five recognised roles."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "Sommelier",
        "Content-Type": "application/json",
    }


def headers_none() -> dict:
    """No auth headers at all."""
    return {"Content-Type": "application/json"}


def other_roles(role: str) -> list:
    """Every recognised role except the one named."""
    return [r for r in HEADERS_BY_ROLE if r != role]
