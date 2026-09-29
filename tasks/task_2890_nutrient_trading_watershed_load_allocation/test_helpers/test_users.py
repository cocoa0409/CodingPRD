"""Pre-built auth headers for each role, plus per-principal header builders.

§2.1 draws a load-bearing distinction between the one entity-backed role and the
six opaque-operator roles:

  * `Producer` — `X-User-ID` is the `id` of the acting `Producer` row, so a
    producer's headers can only be built after the row exists. Use
    `make_producer_headers(producer_id)`.
  * every other role — `X-User-ID` is an opaque operator identifier "that is not
    tied to any persisted entity and is never compared against any row's `id`".
    Where a workflow keeps an audit trail (a permit's `permittee_user_id`, an
    event's `inspector_user_id`, a project's two verifier ids) the identifier
    still has to be *distinct per principal*, which is what the
    `make_*_headers` builders below are for.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_PERMITTEE,
    ROLE_PERMIT_WRITER,
    ROLE_PRACTICE_VERIFIER,
    ROLE_PRODUCER,
    ROLE_PROGRAM_ADMINISTRATOR,
    ROLE_REGISTRY_ADMINISTRATOR,
    ROLE_TMDL_ANALYST,
)

# ------------------------------------------------------------- opaque operator ids
ADMIN_USER_ID = "admin-1"
ANALYST_USER_ID = "analyst-1"
PERMIT_WRITER_USER_ID = "permit-writer-1"
PERMITTEE_1_USER_ID = "user-permittee-1"
PERMITTEE_2_USER_ID = "user-permittee-2"
BASELINE_VERIFIER_USER_ID = "verifier-1"
IMPLEMENTATION_VERIFIER_USER_ID = "verifier-2"
REVERIFICATION_VERIFIER_USER_ID = "verifier-3"
REGISTRY_USER_ID = "registry-1"
REGISTRY_2_USER_ID = "registry-2"

# Shared, ready-to-use header dicts for the six opaque-operator roles.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "program_administrator": build_user_headers(
        ADMIN_USER_ID, ROLE_PROGRAM_ADMINISTRATOR
    ),
    "tmdl_analyst": build_user_headers(ANALYST_USER_ID, ROLE_TMDL_ANALYST),
    "permit_writer": build_user_headers(
        PERMIT_WRITER_USER_ID, ROLE_PERMIT_WRITER
    ),
    "permittee_1": build_user_headers(PERMITTEE_1_USER_ID, ROLE_PERMITTEE),
    "permittee_2": build_user_headers(PERMITTEE_2_USER_ID, ROLE_PERMITTEE),
    "baseline_verifier": build_user_headers(
        BASELINE_VERIFIER_USER_ID, ROLE_PRACTICE_VERIFIER
    ),
    "implementation_verifier": build_user_headers(
        IMPLEMENTATION_VERIFIER_USER_ID, ROLE_PRACTICE_VERIFIER
    ),
    "reverification_verifier": build_user_headers(
        REVERIFICATION_VERIFIER_USER_ID, ROLE_PRACTICE_VERIFIER
    ),
    "registry_administrator": build_user_headers(
        REGISTRY_USER_ID, ROLE_REGISTRY_ADMINISTRATOR
    ),
    "registry_administrator_2": build_user_headers(
        REGISTRY_2_USER_ID, ROLE_REGISTRY_ADMINISTRATOR
    ),
}

ADMIN = TEST_USERS["program_administrator"]
ANALYST = TEST_USERS["tmdl_analyst"]
PERMIT_WRITER = TEST_USERS["permit_writer"]
PERMITTEE_1 = TEST_USERS["permittee_1"]
PERMITTEE_2 = TEST_USERS["permittee_2"]
BASELINE_VERIFIER = TEST_USERS["baseline_verifier"]
IMPLEMENTATION_VERIFIER = TEST_USERS["implementation_verifier"]
REVERIFICATION_VERIFIER = TEST_USERS["reverification_verifier"]
REGISTRY = TEST_USERS["registry_administrator"]
REGISTRY_2 = TEST_USERS["registry_administrator_2"]


# ------------------------------------------------------ per-principal builders
def make_producer_headers(producer_id: str) -> Dict[str, str]:
    """Headers for the entity-backed `Producer` role.

    `X-User-ID` must be the `id` of the acting `Producer` row, because ownership
    checks compare a resource's `producer_id` against it.
    """
    return build_user_headers(producer_id, ROLE_PRODUCER)


def make_permittee_headers(permittee_user_id: str) -> Dict[str, str]:
    """Headers for a `Permittee`; the id must match the permit's
    `permittee_user_id` for annual reporting and credit proposals."""
    return build_user_headers(permittee_user_id, ROLE_PERMITTEE)


def make_verifier_headers(inspector_user_id: str) -> Dict[str, str]:
    """Headers for a `PracticeVerifier`; the id is stamped onto the event's
    `inspector_user_id` and drives the segregation-of-duties checks."""
    return build_user_headers(inspector_user_id, ROLE_PRACTICE_VERIFIER)


def make_registry_headers(registry_user_id: str) -> Dict[str, str]:
    """Headers for a `RegistryAdministrator`; the id must differ from both
    verifier ids on a project being certified."""
    return build_user_headers(registry_user_id, ROLE_REGISTRY_ADMINISTRATOR)


def make_permit_writer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `PermitWriter`."""
    return build_user_headers(user_id, ROLE_PERMIT_WRITER)


def make_program_admin_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `ProgramAdministrator`."""
    return build_user_headers(user_id, ROLE_PROGRAM_ADMINISTRATOR)


def make_analyst_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `TmdlAnalyst`."""
    return build_user_headers(user_id, ROLE_TMDL_ANALYST)


def make_raw_headers(
    user_id: Optional[str] = None, role: Optional[str] = None
) -> Dict[str, str]:
    """Build headers verbatim, omitting whichever of the two is None.

    Used by the authentication tests of §2.1. Empty values are sent as the empty
    string `""` — never as whitespace, which the HTTP client would reject before
    the request ever reached the API.
    """
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-User-Role"] = role
    return headers
