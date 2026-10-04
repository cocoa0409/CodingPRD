"""Pre-built role headers for the three roles the PRD recognizes.

``Athlete`` is entity-backed: when the role is Athlete, ``X-User-ID`` must be
the ``id`` of a real Athlete row for any ownership-gated call. Fixtures and
tests therefore build athlete headers per-entity via ``make_athlete_headers``.
The shared ``TEST_USERS["athlete"]`` entry is only a fallback for calls whose
success does not depend on the caller owning a resource (registration, reads
of public resources).

``Moderator`` and ``PlatformAdmin`` are opaque: their ``X-User-ID`` is never
compared to any stored entity, so stable shared constants are canonical.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Fallback only — never use for ownership-gated calls.
    "athlete": build_user_headers("00000000-0000-4000-8000-000000000000", "Athlete"),
    "moderator": build_user_headers("moderator-op-1", "Moderator"),
    "platform_admin": build_user_headers("platform-admin-1", "PlatformAdmin"),
}


def make_athlete_headers(athlete_id: str) -> Dict[str, str]:
    """Headers for the entity-backed Athlete role.

    Pass the real Athlete.id as ``athlete_id`` whenever the call is
    ownership-gated (own activities, zones, memberships, RSVPs, beacon
    sessions, route plans, self-deletion, club-admin actions).
    """
    return build_user_headers(athlete_id, "Athlete")


def make_moderator_headers(user_id: str = "moderator-op-1") -> Dict[str, str]:
    """Headers for the opaque Moderator role."""
    return build_user_headers(user_id, "Moderator")


def make_platform_admin_headers(user_id: str = "platform-admin-1") -> Dict[str, str]:
    """Headers for the opaque PlatformAdmin role."""
    return build_user_headers(user_id, "PlatformAdmin")
