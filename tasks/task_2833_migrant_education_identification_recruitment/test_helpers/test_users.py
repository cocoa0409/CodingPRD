"""Caller identities.

Three of the five roles carry an opaque operator identifier that "is not tied to any
persisted entity", so a shared constant is enough for them. The other two --
``Recruiter`` and ``QualityControlReviewer`` -- are backed by a persisted recruiter row
and their ``X-User-ID`` must resolve to that row, so those headers are always built
around a live recruiter identifier handed in by the caller.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_EXCHANGE_LIAISON,
    ROLE_QC_REVIEWER,
    ROLE_RECRUITER,
    ROLE_SERVICE_COORDINATOR,
    ROLE_STATE_PROGRAM_ADMIN,
)
from .types import Headers, ResourceId

# Opaque operator identifiers for the three roles the server never compares to an id.
STATE_PROGRAM_ADMIN_USER_ID = "state-office-operator-001"
SERVICE_COORDINATOR_USER_ID = "service-coordinator-operator-001"
EXCHANGE_LIAISON_USER_ID = "exchange-liaison-operator-001"

TEST_USERS = {
    ROLE_STATE_PROGRAM_ADMIN: {
        "user_id": STATE_PROGRAM_ADMIN_USER_ID,
        "role": ROLE_STATE_PROGRAM_ADMIN,
    },
    ROLE_SERVICE_COORDINATOR: {
        "user_id": SERVICE_COORDINATOR_USER_ID,
        "role": ROLE_SERVICE_COORDINATOR,
    },
    ROLE_EXCHANGE_LIAISON: {
        "user_id": EXCHANGE_LIAISON_USER_ID,
        "role": ROLE_EXCHANGE_LIAISON,
    },
}


def make_admin_headers() -> Headers:
    """Headers for the state migrant education office."""
    return build_user_headers(STATE_PROGRAM_ADMIN_USER_ID, ROLE_STATE_PROGRAM_ADMIN)


def make_coordinator_headers() -> Headers:
    """Headers for a service coordinator."""
    return build_user_headers(SERVICE_COORDINATOR_USER_ID, ROLE_SERVICE_COORDINATOR)


def make_liaison_headers() -> Headers:
    """Headers for a national-exchange liaison."""
    return build_user_headers(EXCHANGE_LIAISON_USER_ID, ROLE_EXCHANGE_LIAISON)


def make_recruiter_headers(recruiter_id: ResourceId) -> Headers:
    """Headers for a field recruiter acting as themselves.

    ``X-User-ID`` must be the id of the acting recruiter row; the server stamps it into
    the records the recruiter files.
    """
    return build_user_headers(recruiter_id, ROLE_RECRUITER)


def make_qc_reviewer_headers(recruiter_id: ResourceId) -> Headers:
    """Headers for a quality-control reviewer.

    The same recruiter table backs this role, so the identifier is a recruiter id too --
    which is exactly why quality-control decisions carry a segregation-of-duties test.
    """
    return build_user_headers(recruiter_id, ROLE_QC_REVIEWER)


def headers_for_role(role: str, recruiter_id: ResourceId = None) -> Headers:
    """Build headers for any of the five roles.

    ``recruiter_id`` is required for the two entity-backed roles and ignored otherwise.
    """
    if role == ROLE_RECRUITER:
        assert recruiter_id is not None, "Recruiter headers need a live recruiter id"
        return make_recruiter_headers(recruiter_id)
    if role == ROLE_QC_REVIEWER:
        assert recruiter_id is not None, "reviewer headers need a live recruiter id"
        return make_qc_reviewer_headers(recruiter_id)
    if role == ROLE_STATE_PROGRAM_ADMIN:
        return make_admin_headers()
    if role == ROLE_SERVICE_COORDINATOR:
        return make_coordinator_headers()
    if role == ROLE_EXCHANGE_LIAISON:
        return make_liaison_headers()
    raise AssertionError("unknown role: %s" % role)


def headers_without_identity() -> Headers:
    """A request that carries no identity headers at all."""
    return {"Content-Type": "application/json"}
