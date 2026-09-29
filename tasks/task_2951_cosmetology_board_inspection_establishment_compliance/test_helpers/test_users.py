"""Header builders for the seven roles of PRD 2.1.

Four roles are opaque: ``X-User-ID`` is an arbitrary operator string that the
server never resolves against a table, so a module-level constant is enough.
Three roles are entity-backed: ``X-User-ID`` must be the primary key of a
persisted ``Establishment``, ``Practitioner`` or ``School`` row, so those roles
get a per-instance builder that the caller feeds the row id.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --- Opaque operator identifiers (PRD 2.1) ----------------------------------
BOARD_ADMIN_USER_ID = "admin-001"
SECOND_BOARD_ADMIN_USER_ID = "admin-002"
INSPECTOR_USER_ID = "inspector-001"
SECOND_INSPECTOR_USER_ID = "inspector-002"
HEARING_OFFICER_USER_ID = "officer-001"
SECOND_HEARING_OFFICER_USER_ID = "officer-002"
HEALTH_LIAISON_USER_ID = "liaison-001"

BOARD_ADMIN_HEADERS: Dict[str, str] = build_user_headers(
    BOARD_ADMIN_USER_ID, "BoardAdmin"
)
SECOND_BOARD_ADMIN_HEADERS: Dict[str, str] = build_user_headers(
    SECOND_BOARD_ADMIN_USER_ID, "BoardAdmin"
)
INSPECTOR_HEADERS: Dict[str, str] = build_user_headers(
    INSPECTOR_USER_ID, "Inspector"
)
SECOND_INSPECTOR_HEADERS: Dict[str, str] = build_user_headers(
    SECOND_INSPECTOR_USER_ID, "Inspector"
)
HEARING_OFFICER_HEADERS: Dict[str, str] = build_user_headers(
    HEARING_OFFICER_USER_ID, "HearingOfficer"
)
SECOND_HEARING_OFFICER_HEADERS: Dict[str, str] = build_user_headers(
    SECOND_HEARING_OFFICER_USER_ID, "HearingOfficer"
)
HEALTH_LIAISON_HEADERS: Dict[str, str] = build_user_headers(
    HEALTH_LIAISON_USER_ID, "HealthAuthorityLiaison"
)


# --- Entity-backed roles: X-User-ID is a row id (PRD 2.1) -------------------
def make_establishment_owner_headers(establishment_id: str) -> Dict[str, str]:
    """Headers for an ``EstablishmentOwner`` acting for one establishment row."""
    return build_user_headers(establishment_id, "EstablishmentOwner")


def make_practitioner_headers(practitioner_id: str) -> Dict[str, str]:
    """Headers for a ``Practitioner`` acting for their own practitioner row."""
    return build_user_headers(practitioner_id, "Practitioner")


def make_school_registrar_headers(school_id: str) -> Dict[str, str]:
    """Headers for a ``SchoolRegistrar`` acting for one school row."""
    return build_user_headers(school_id, "SchoolRegistrar")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Free-form builder, for role-recognition and header-presence tests."""
    return build_user_headers(user_id, role)


# --- Authentication-surface fixtures (PRD 2.1) ------------------------------
# A blank header value must be sent as an empty string, never whitespace, or the
# HTTP layer rejects the request before the server can classify it.
MISSING_USER_ID_HEADERS: Dict[str, str] = build_user_headers("", "BoardAdmin")
MISSING_ROLE_HEADERS: Dict[str, str] = build_user_headers(BOARD_ADMIN_USER_ID, "")
NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers(
    BOARD_ADMIN_USER_ID, "Superintendent"
)
LOWERCASE_ROLE_HEADERS: Dict[str, str] = build_user_headers(
    BOARD_ADMIN_USER_ID, "boardadmin"
)
