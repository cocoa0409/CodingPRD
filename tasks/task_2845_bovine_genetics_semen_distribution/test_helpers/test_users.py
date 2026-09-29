"""Pre-built request headers for each acting role.

PRD 2.1 requires every request to carry `X-User-ID` and `X-User-Role`.  Five of
the seven roles carry an opaque staff identifier.  The other two are backed by
a row of this API: a `FacilityManager`'s `X-User-ID` is a `Facility.id` and a
`Distributor`'s `X-User-ID` is a `Distributor.id`, so ownership-gated calls must
be made with `make_facility_headers(facility["id"])` /
`make_distributor_headers(distributor["id"])` rather than a shared constant.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BREEDING_ADVISOR,
    ROLE_DISTRIBUTOR,
    ROLE_EXPORT_COORDINATOR,
    ROLE_FACILITY_MANAGER,
    ROLE_LAB_TECHNICIAN,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_STAFF_VETERINARIAN,
)

# --- opaque identities -------------------------------------------------------
DIRECTOR_USER_ID = "dir-1"
DIRECTOR_ALT_USER_ID = "dir-2"
VET_USER_ID = "vet-1"
VET_ALT_USER_ID = "vet-2"
VET_THIRD_USER_ID = "vet-9"
TECH_USER_ID = "tech-1"
TECH_ALT_USER_ID = "tech-2"
TECH_THIRD_USER_ID = "tech-3"
COORDINATOR_USER_ID = "exp-1"
COORDINATOR_ALT_USER_ID = "exp-2"
ADVISOR_USER_ID = "adv-1"
ADVISOR_ALT_USER_ID = "adv-2"

# `X-User-ID` values for the two entity-backed roles are always a real row id,
# so no module-level constant exists for them.

TEST_USERS: Dict[str, str] = {
    ROLE_PROGRAM_DIRECTOR: DIRECTOR_USER_ID,
    ROLE_STAFF_VETERINARIAN: VET_USER_ID,
    ROLE_LAB_TECHNICIAN: TECH_USER_ID,
    ROLE_EXPORT_COORDINATOR: COORDINATOR_USER_ID,
    ROLE_BREEDING_ADVISOR: ADVISOR_USER_ID,
}


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, role)


def make_director_headers(user_id: str = DIRECTOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PROGRAM_DIRECTOR)


def make_vet_headers(user_id: str = VET_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_STAFF_VETERINARIAN)


def make_tech_headers(user_id: str = TECH_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LAB_TECHNICIAN)


def make_coordinator_headers(user_id: str = COORDINATOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_EXPORT_COORDINATOR)


def make_advisor_headers(user_id: str = ADVISOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_BREEDING_ADVISOR)


def make_facility_headers(facility_id: str) -> Dict[str, str]:
    """A FacilityManager acts as the facility whose id it presents (PRD 2.1)."""
    return build_user_headers(facility_id, ROLE_FACILITY_MANAGER)


def make_distributor_headers(distributor_id: str) -> Dict[str, str]:
    """A Distributor acts as the distributor whose id it presents (PRD 2.1)."""
    return build_user_headers(distributor_id, ROLE_DISTRIBUTOR)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Role header only: exercises the ERR_USER_ID_REQUIRED arm of PRD 2.1."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: Optional[str] = DIRECTOR_USER_ID) -> Dict[str, str]:
    """Identity header only: no role, which PRD 2.1 answers ERR_UNAUTHORIZED."""
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    return headers


ROLE_HEADER_BUILDERS = {
    ROLE_PROGRAM_DIRECTOR: make_director_headers,
    ROLE_STAFF_VETERINARIAN: make_vet_headers,
    ROLE_LAB_TECHNICIAN: make_tech_headers,
    ROLE_EXPORT_COORDINATOR: make_coordinator_headers,
    ROLE_BREEDING_ADVISOR: make_advisor_headers,
}
