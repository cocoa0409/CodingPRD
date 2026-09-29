"""Auth headers for the six declared roles.

Three of the roles authenticate as a registered staff member and two of them
authenticate as a protectee, so their ``X-User-ID`` must be a real entity
identifier created by the test.  Those roles get per-instance builders.  The
two roles whose identity the service never resolves to a stored row —
``ComplianceOfficer`` and ``SystemOperator`` — use fixed opaque identifiers.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_EXECUTIVE,
    ROLE_PROTECTION_MANAGER,
    ROLE_SECURITY_ANALYST,
    ROLE_SECURITY_DIRECTOR,
    ROLE_SYSTEM_OPERATOR,
)

# Opaque identifiers for the two roles with no backing entity.
COMPLIANCE_OFFICER_ID = "compliance-1"
SYSTEM_OPERATOR_ID = "ops-1"

TEST_USERS = {
    ROLE_COMPLIANCE_OFFICER: build_user_headers(
        COMPLIANCE_OFFICER_ID, ROLE_COMPLIANCE_OFFICER
    ),
    ROLE_SYSTEM_OPERATOR: build_user_headers(
        SYSTEM_OPERATOR_ID, ROLE_SYSTEM_OPERATOR
    ),
}

COMPLIANCE_OFFICER_HEADERS = TEST_USERS[ROLE_COMPLIANCE_OFFICER]
SYSTEM_OPERATOR_HEADERS = TEST_USERS[ROLE_SYSTEM_OPERATOR]


def make_security_analyst_headers(staff_id):
    """Headers for an analyst authenticating as the staff row ``staff_id``."""
    return build_user_headers(str(staff_id), ROLE_SECURITY_ANALYST)


def make_protection_manager_headers(staff_id):
    """Headers for a manager authenticating as the staff row ``staff_id``."""
    return build_user_headers(str(staff_id), ROLE_PROTECTION_MANAGER)


def make_security_director_headers(staff_id):
    """Headers for a director authenticating as the staff row ``staff_id``."""
    return build_user_headers(str(staff_id), ROLE_SECURITY_DIRECTOR)


def make_executive_headers(executive_id):
    """Headers for a protectee authenticating as their own executive row."""
    return build_user_headers(str(executive_id), ROLE_EXECUTIVE)


def make_compliance_officer_headers(user_id=COMPLIANCE_OFFICER_ID):
    """Headers for a compliance officer; the identifier is opaque to the service."""
    return build_user_headers(str(user_id), ROLE_COMPLIANCE_OFFICER)


def make_system_operator_headers(user_id=SYSTEM_OPERATOR_ID):
    """Headers for a system operator; the identifier is opaque to the service."""
    return build_user_headers(str(user_id), ROLE_SYSTEM_OPERATOR)


def make_headers(user_id, role):
    """Headers for an arbitrary role/identity pair."""
    return build_user_headers(str(user_id), role)


def headers_with_empty_role(user_id):
    """Headers whose ``X-User-Role`` is present but empty."""
    return {
        "X-User-ID": str(user_id),
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_with_empty_user_id(role):
    """Headers whose ``X-User-ID`` is present but empty."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_without_role(user_id):
    """Headers that omit ``X-User-Role`` entirely."""
    return {"X-User-ID": str(user_id), "Content-Type": "application/json"}


def headers_without_user_id(role):
    """Headers that omit ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
