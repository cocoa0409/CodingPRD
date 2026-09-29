"""Identity headers for the seven roles.

Six roles present an opaque operator identifier. `LaboratoryManager` is the one
identity-backed role: its `X-User-ID` is the `id` of the acting laboratory, so
its headers can only be built once a laboratory row exists, which is why
`make_laboratory_manager_headers` takes the laboratory id as an argument.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FINANCE_OFFICER,
    ROLE_LABORATORY_MANAGER,
    ROLE_SAMPLING_TECHNICIAN,
    ROLE_STATE_REGULATOR,
    ROLE_TREATMENT_ENGINEER,
    ROLE_UTILITY_ADMIN,
    UNKNOWN_ROLE,
)

# --- Opaque operator identifiers -------------------------------------------
ADMIN_USER_ID = "admin-1"
TECHNICIAN_USER_ID = "tech-1"
TECHNICIAN_2_USER_ID = "tech-2"
OFFICER_USER_ID = "officer-1"
OFFICER_2_USER_ID = "officer-2"
ENGINEER_USER_ID = "engineer-1"
FINANCE_USER_ID = "finance-1"
REGULATOR_USER_ID = "regulator-1"

UTILITY_ADMIN_HEADERS: Dict[str, str] = build_user_headers(ADMIN_USER_ID, ROLE_UTILITY_ADMIN)
SAMPLING_TECHNICIAN_HEADERS: Dict[str, str] = build_user_headers(
    TECHNICIAN_USER_ID, ROLE_SAMPLING_TECHNICIAN
)
SAMPLING_TECHNICIAN_2_HEADERS: Dict[str, str] = build_user_headers(
    TECHNICIAN_2_USER_ID, ROLE_SAMPLING_TECHNICIAN
)
COMPLIANCE_OFFICER_HEADERS: Dict[str, str] = build_user_headers(
    OFFICER_USER_ID, ROLE_COMPLIANCE_OFFICER
)
COMPLIANCE_OFFICER_2_HEADERS: Dict[str, str] = build_user_headers(
    OFFICER_2_USER_ID, ROLE_COMPLIANCE_OFFICER
)
TREATMENT_ENGINEER_HEADERS: Dict[str, str] = build_user_headers(
    ENGINEER_USER_ID, ROLE_TREATMENT_ENGINEER
)
FINANCE_OFFICER_HEADERS: Dict[str, str] = build_user_headers(
    FINANCE_USER_ID, ROLE_FINANCE_OFFICER
)
STATE_REGULATOR_HEADERS: Dict[str, str] = build_user_headers(
    REGULATOR_USER_ID, ROLE_STATE_REGULATOR
)

# A syntactically valid identity whose role is outside the seven declared roles.
UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers("stranger-1", UNKNOWN_ROLE)


def make_laboratory_manager_headers(laboratory_id: str) -> Dict[str, str]:
    """Headers for the manager of the laboratory whose id is `laboratory_id`."""
    return build_user_headers(laboratory_id, ROLE_LABORATORY_MANAGER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary identity/role pair."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str = ROLE_UTILITY_ADMIN) -> Dict[str, str]:
    """Headers that omit `X-User-ID` entirely."""
    return {"X-User-Role": role}


def headers_missing_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers that omit `X-User-Role` entirely."""
    return {"X-User-ID": user_id}


def headers_blank_user_id(role: str = ROLE_UTILITY_ADMIN) -> Dict[str, str]:
    """Headers whose `X-User-ID` is the empty string.

    The value is deliberately `""` and not a run of spaces: a whitespace header
    value is rejected by the HTTP client before the request is ever sent.
    """
    return {"X-User-ID": "", "X-User-Role": role}


def headers_blank_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers whose `X-User-Role` is the empty string."""
    return {"X-User-ID": user_id, "X-User-Role": ""}


def headers_for_role(role: str) -> Dict[str, str]:
    """A canonical opaque identity for each non-laboratory role."""
    mapping = {
        ROLE_UTILITY_ADMIN: UTILITY_ADMIN_HEADERS,
        ROLE_SAMPLING_TECHNICIAN: SAMPLING_TECHNICIAN_HEADERS,
        ROLE_COMPLIANCE_OFFICER: COMPLIANCE_OFFICER_HEADERS,
        ROLE_TREATMENT_ENGINEER: TREATMENT_ENGINEER_HEADERS,
        ROLE_FINANCE_OFFICER: FINANCE_OFFICER_HEADERS,
        ROLE_STATE_REGULATOR: STATE_REGULATOR_HEADERS,
    }
    return mapping[role]
