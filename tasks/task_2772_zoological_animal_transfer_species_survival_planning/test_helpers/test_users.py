"""Identity headers.

Every request carries X-User-ID and X-User-Role. Three of the four roles are
entity-backed, so their X-User-ID must be the id of a row created during the
test: a Registrar is identified by its Institution id, a ProgramCoordinator by
its SpeciesProgram id and a Veterinarian by its Veterinarian id. Only the
AccreditationAdmin identifier is opaque, so it is the only role with a usable
fixed constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ACCREDITATION_ADMIN,
    ROLE_PROGRAM_COORDINATOR,
    ROLE_REGISTRAR,
    ROLE_VETERINARIAN,
)

# The accrediting body's identifier is opaque, so a constant is legitimate here.
ADMIN_USER_ID = "aza-accreditation-desk"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin": {"user_id": ADMIN_USER_ID, "role": ROLE_ACCREDITATION_ADMIN},
}


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for the accrediting body."""
    return build_user_headers(user_id, ROLE_ACCREDITATION_ADMIN)


def make_registrar_headers(institution_id: str) -> Dict[str, str]:
    """Headers for the registrar of the institution whose id is given."""
    return build_user_headers(institution_id, ROLE_REGISTRAR)


def make_coordinator_headers(species_program_id: str) -> Dict[str, str]:
    """Headers for the coordinator of the programme whose id is given."""
    return build_user_headers(species_program_id, ROLE_PROGRAM_COORDINATOR)


def make_vet_headers(veterinarian_id: str) -> Dict[str, str]:
    """Headers for the veterinarian whose id is given."""
    return build_user_headers(veterinarian_id, ROLE_VETERINARIAN)


def headers_with_empty_user_id(role: str = ROLE_REGISTRAR) -> Dict[str, str]:
    """Headers whose X-User-ID is present but empty."""
    return build_user_headers("", role)


def headers_missing_user_id(role: str = ROLE_REGISTRAR) -> Dict[str, str]:
    """Headers with no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers with no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers naming a role outside the four the PRD recognises."""
    return build_user_headers(user_id, "Curator")


__all__ = [
    "ADMIN_USER_ID",
    "TEST_USERS",
    "make_admin_headers",
    "make_registrar_headers",
    "make_coordinator_headers",
    "make_vet_headers",
    "headers_with_empty_user_id",
    "headers_missing_user_id",
    "headers_missing_role",
    "headers_with_unknown_role",
    "ROLE_ACCREDITATION_ADMIN",
    "ROLE_PROGRAM_COORDINATOR",
    "ROLE_REGISTRAR",
    "ROLE_VETERINARIAN",
]
