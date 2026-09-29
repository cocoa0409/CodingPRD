"""Identity header builders, one per §2.1 role.

Two of the six roles are entity-backed: a ``ProgramChair``'s ``X-User-ID`` is the
``id`` of the acting ``AcademicProgram`` and an ``ExternalReviewer``'s is the
``id`` of the acting ``ExternalReviewer`` row. Those two therefore take the
entity id as an argument. The other four are opaque operator identifiers that
the server never compares to any entity's ``id``, so they are plain constants.

Ratification is a segregation-of-duties hinge, so two distinct opaque Provost
identities exist: the proposer and the ratifier must never be the same string.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- Opaque operator identifiers (§2.1) ------------------------------------
REVIEW_COORDINATOR_USER_ID = "coordinator-001"
PROVOST_PROPOSER_USER_ID = "provost-proposer"
PROVOST_RATIFIER_USER_ID = "provost-ratifier"
REGISTRAR_USER_ID = "registrar-001"
HR_PARTNER_USER_ID = "hr-partner-001"

# A second coordinator, for tests that need two distinct opaque operators in
# the same role.
SECOND_REVIEW_COORDINATOR_USER_ID = "coordinator-002"


def make_review_coordinator_headers(
    user_id: str = REVIEW_COORDINATOR_USER_ID,
) -> Dict[str, str]:
    """Headers for the provost office's process owner."""
    return build_user_headers(user_id, UserRole.REVIEW_COORDINATOR.value)


def make_provost_headers(user_id: str = PROVOST_PROPOSER_USER_ID) -> Dict[str, str]:
    """Headers for a deciding officer. Defaults to the proposing provost."""
    return build_user_headers(user_id, UserRole.PROVOST.value)


def make_provost_proposer_headers() -> Dict[str, str]:
    """The provost who proposes an outcome."""
    return build_user_headers(PROVOST_PROPOSER_USER_ID, UserRole.PROVOST.value)


def make_provost_ratifier_headers() -> Dict[str, str]:
    """The second provost, distinct from the proposer, who ratifies."""
    return build_user_headers(PROVOST_RATIFIER_USER_ID, UserRole.PROVOST.value)


def make_registrar_headers(user_id: str = REGISTRAR_USER_ID) -> Dict[str, str]:
    """Headers for the catalog / seat-ledger / displaced-student owner."""
    return build_user_headers(user_id, UserRole.REGISTRAR.value)


def make_hr_partner_headers(user_id: str = HR_PARTNER_USER_ID) -> Dict[str, str]:
    """Headers for the faculty-appointment owner."""
    return build_user_headers(user_id, UserRole.HR_PARTNER.value)


# --- Entity-backed identities (§2.1) ---------------------------------------


def make_program_chair_headers(program_id: str) -> Dict[str, str]:
    """Headers for the chair of ``program_id``.

    ``X-User-ID`` is the id of the acting ``AcademicProgram``; ownership checks
    compare a resource's program foreign key to this value, following the
    reference transitively.
    """
    return build_user_headers(program_id, UserRole.PROGRAM_CHAIR.value)


def make_external_reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    """Headers for the reviewer whose ``ExternalReviewer.id`` is ``reviewer_id``."""
    return build_user_headers(reviewer_id, UserRole.EXTERNAL_REVIEWER.value)


# --- Malformed identities, for the §2.10 check-1 / check-2 steps -----------


def make_headers_with_blank_user_id(role: str) -> Dict[str, str]:
    """A present-but-empty ``X-User-ID``. Treated exactly as an absent one."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def make_headers_with_whitespace_user_id(role: str) -> Dict[str, str]:
    """A whitespace-only ``X-User-ID``. Treated exactly as an absent one.

    Send this only inside ``api_client.allow_blank_header_values()``; ``requests``
    rejects a whitespace-only value client-side and the probe would never reach
    the server.
    """
    return {"X-User-ID": "   ", "X-User-Role": role, "Content-Type": "application/json"}


def make_headers_with_blank_role(user_id: str) -> Dict[str, str]:
    """A present-but-empty ``X-User-Role``."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def make_headers_with_whitespace_role(user_id: str) -> Dict[str, str]:
    """A whitespace-only ``X-User-Role``.

    Send this only inside ``api_client.allow_blank_header_values()``; ``requests``
    rejects a whitespace-only value client-side and the probe would never reach
    the server.
    """
    return {
        "X-User-ID": user_id,
        "X-User-Role": "   ",
        "Content-Type": "application/json",
    }


def make_headers_without_user_id(role: str) -> Dict[str, str]:
    """``X-User-ID`` omitted entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_without_role(user_id: str) -> Dict[str, str]:
    """``X-User-Role`` omitted entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_with_unknown_role(user_id: str = "someone") -> Dict[str, str]:
    """A syntactically fine role name that is not one of the six declared roles."""
    return build_user_headers(user_id, "Chancellor")


ALL_ROLES = [role.value for role in UserRole]
