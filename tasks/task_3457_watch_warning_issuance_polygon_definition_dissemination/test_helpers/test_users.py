"""Caller identities (PRD §2.1).

Two identity forms exist:

- ``PlatformAdmin``, ``VerificationAnalyst`` and ``EmergencyManager`` carry an
  opaque operator identifier the server never compares to a persisted entity, so
  a shared constant header set is canonical for them.
- ``Forecaster`` and ``MeteorologistInCharge`` are entity-backed: ``X-User-ID``
  must be the ``id`` of an existing ``Forecaster`` row, and office-scope checks
  compare that row's ``office_id`` against the resource's owning office (or a
  coordination request's target office). For those two roles always build
  headers with ``make_forecaster_headers`` / ``make_mic_headers`` around the live
  forecaster id returned by ``POST /alerts/forecasters``.

The shared ``forecaster_headers`` / ``mic_headers`` constants below are fallback
identities for tests whose outcome does NOT depend on resolving the caller (e.g.
probing that a bad id is rejected); they must never be used for an
ownership-gated call, because their user id resolves to no Forecaster row.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers, ResourceId, UserRole

# Opaque operator identifiers (never tied to a persisted entity, PRD §2.1).
PLATFORM_ADMIN_USER_ID = "test-admin-1"
VERIFICATION_ANALYST_USER_ID = "va-1"
EMERGENCY_MANAGER_USER_ID = "em-1"

TEST_USERS = {
    # Opaque roles: canonical form.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ID, UserRole.PLATFORM_ADMIN.value
    ),
    "verification_analyst_headers": build_user_headers(
        VERIFICATION_ANALYST_USER_ID, UserRole.VERIFICATION_ANALYST.value
    ),
    "emergency_manager_headers": build_user_headers(
        EMERGENCY_MANAGER_USER_ID, UserRole.EMERGENCY_MANAGER.value
    ),
    # Entity-backed roles: fallback for non-ownership probes ONLY (see docstring).
    "forecaster_headers": build_user_headers(
        "test-forecaster-unresolved", UserRole.FORECASTER.value
    ),
    "mic_headers": build_user_headers("test-mic-unresolved", UserRole.METEOROLOGIST_IN_CHARGE.value),
}


def make_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> Headers:
    """Headers for a PlatformAdmin (opaque identity)."""
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_analyst_headers(user_id: str = VERIFICATION_ANALYST_USER_ID) -> Headers:
    """Headers for a VerificationAnalyst (opaque identity)."""
    return build_user_headers(user_id, UserRole.VERIFICATION_ANALYST.value)


def make_emergency_manager_headers(user_id: str = EMERGENCY_MANAGER_USER_ID) -> Headers:
    """Headers for an EmergencyManager (opaque identity)."""
    return build_user_headers(user_id, UserRole.EMERGENCY_MANAGER.value)


def make_forecaster_headers(forecaster_id: ResourceId) -> Headers:
    """Headers for a Forecaster; ``forecaster_id`` must be a live Forecaster.id."""
    return build_user_headers(str(forecaster_id), UserRole.FORECASTER.value)


def make_mic_headers(forecaster_id: ResourceId) -> Headers:
    """Headers for a MeteorologistInCharge; the Forecaster row must carry
    ``level == MIC`` for coordination-override issuance to be permitted."""
    return build_user_headers(str(forecaster_id), UserRole.METEOROLOGIST_IN_CHARGE.value)


def headers_for_forecaster(forecaster: dict) -> Headers:
    """Convenience: Forecaster headers for a created forecaster row."""
    return make_forecaster_headers(forecaster["id"])


def headers_for_mic(forecaster: dict) -> Headers:
    """Convenience: MeteorologistInCharge headers for a created forecaster row."""
    return make_mic_headers(forecaster["id"])


def headers_without_identity() -> Headers:
    """A request carrying neither identity header (exercises ERR_UNAUTHENTICATED)."""
    return {"Content-Type": "application/json"}


def make_undeclared_role_headers(
    user_id: str = "anon-1", role: str = "Anonymous"
) -> Headers:
    """A request whose role header names no declared role (ERR_UNAUTHENTICATED)."""
    return build_user_headers(user_id, role)


__all__ = [
    "PLATFORM_ADMIN_USER_ID",
    "VERIFICATION_ANALYST_USER_ID",
    "EMERGENCY_MANAGER_USER_ID",
    "TEST_USERS",
    "make_admin_headers",
    "make_analyst_headers",
    "make_emergency_manager_headers",
    "make_forecaster_headers",
    "make_mic_headers",
    "headers_for_forecaster",
    "headers_for_mic",
    "headers_without_identity",
    "make_undeclared_role_headers",
]
