"""Request headers for each acting role.

Three roles are scope-bound: their ``X-User-ID`` is the identifier of a
persisted entity, so their headers can only be built once that entity exists.
For those roles use the ``make_*_headers`` builders and pass the entity's own
``id``.  The other three roles are opaque operators, so their headers are fixed
constants.

Two distinct operator identifiers are provided for ``DistrictAdmin`` and
``Registrar`` because the segregation-of-duties rule requires an upstream and a
downstream operator that differ.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------
# Opaque operator identifiers
# --------------------------------------------------------------------------
DISTRICT_ADMIN_USER_ID = "admin-01"
DISTRICT_ADMIN_ALT_USER_ID = "admin-02"
REGISTRAR_USER_ID = "reg-01"
REGISTRAR_ALT_USER_ID = "reg-02"
ALT_ED_TEACHER_USER_ID = "teach-01"


# --------------------------------------------------------------------------
# Scope-bound header builders — the entity id IS the acting user id
# --------------------------------------------------------------------------
def make_placement_coordinator_headers(center_id: str) -> Dict[str, str]:
    """Headers for the coordinator acting as the given centre."""
    return build_user_headers(center_id, UserRole.PLACEMENT_COORDINATOR.value)


def make_home_school_counselor_headers(home_school_id: str) -> Dict[str, str]:
    """Headers for the counsellor acting as the given sending school."""
    return build_user_headers(home_school_id, UserRole.HOME_SCHOOL_COUNSELOR.value)


def make_support_provider_staff_headers(support_provider_id: str) -> Dict[str, str]:
    """Headers for the on-site provider acting as itself."""
    return build_user_headers(
        support_provider_id, UserRole.SUPPORT_PROVIDER_STAFF.value
    )


# --------------------------------------------------------------------------
# Opaque header builders
# --------------------------------------------------------------------------
def make_district_admin_headers(
    user_id: str = DISTRICT_ADMIN_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.DISTRICT_ADMIN.value)


def make_registrar_headers(user_id: str = REGISTRAR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.REGISTRAR.value)


def make_alt_ed_teacher_headers(
    user_id: str = ALT_ED_TEACHER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.ALT_ED_TEACHER.value)


# --------------------------------------------------------------------------
# Ready-made header sets
# --------------------------------------------------------------------------
DISTRICT_ADMIN_HEADERS = make_district_admin_headers()
DISTRICT_ADMIN_ALT_HEADERS = make_district_admin_headers(DISTRICT_ADMIN_ALT_USER_ID)
REGISTRAR_HEADERS = make_registrar_headers()
REGISTRAR_ALT_HEADERS = make_registrar_headers(REGISTRAR_ALT_USER_ID)
ALT_ED_TEACHER_HEADERS = make_alt_ed_teacher_headers()

#: Headers carrying neither identity header at all.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

#: Headers carrying a role but an empty acting user identifier.
EMPTY_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-ID": "",
    "X-User-Role": UserRole.DISTRICT_ADMIN.value,
    "Content-Type": "application/json",
}

TEST_USERS: Dict[str, Dict[str, str]] = {
    "district_admin": DISTRICT_ADMIN_HEADERS,
    "district_admin_alt": DISTRICT_ADMIN_ALT_HEADERS,
    "registrar": REGISTRAR_HEADERS,
    "registrar_alt": REGISTRAR_ALT_HEADERS,
    "alt_ed_teacher": ALT_ED_TEACHER_HEADERS,
    "no_auth": NO_AUTH_HEADERS,
    "empty_user_id": EMPTY_USER_ID_HEADERS,
}
