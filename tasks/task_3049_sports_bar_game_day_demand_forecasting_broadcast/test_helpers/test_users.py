"""Caller identities for the five declared roles.

All five roles use opaque operator identifiers: the server never compares
``X-User-ID`` against any persisted entity, so a stable identifier per role is
enough for every call.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": build_user_headers(
        "11111111-1111-4111-8111-111111111111", "PlatformAdmin"
    ),
    "venue_manager": build_user_headers(
        "22222222-2222-4222-8222-222222222222", "VenueManager"
    ),
    "host": build_user_headers("33333333-3333-4333-8333-333333333333", "Host"),
    "server": build_user_headers("44444444-4444-4444-8444-444444444444", "Server"),
    "scheduler": build_user_headers(
        "55555555-5555-4555-8555-555555555555", "Scheduler"
    ),
}

# Convenience aliases.
PLATFORM_ADMIN_HEADERS = TEST_USERS["platform_admin"]
VENUE_MANAGER_HEADERS = TEST_USERS["venue_manager"]
HOST_HEADERS = TEST_USERS["host"]
SERVER_HEADERS = TEST_USERS["server"]
SCHEDULER_HEADERS = TEST_USERS["scheduler"]


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role}


UNDECLARED_ROLE = "Bartender"


def headers_with_undeclared_role(user_id: str) -> Dict[str, str]:
    """Headers naming a role the contract does not recognize."""
    return build_user_headers(user_id, UNDECLARED_ROLE)
