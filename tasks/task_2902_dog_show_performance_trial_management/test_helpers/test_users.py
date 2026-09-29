"""Pre-built role headers for every role the PRD recognises.

Three roles are backed by a persisted entity, and for those `X-User-ID` is that
entity's own `id`: `ClubOfficer` carries a `Club.id`, `Judge` carries a
`Judge.id` and `Handler` carries a `Handler.id`. Every ownership-gated call must
therefore build its headers with the real entity identifier through the
`make_*_headers` builders below; the shared `TEST_USERS` constants are only safe
for the three opaque operator roles and for calls whose success does not depend
on the caller owning the subject resource.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers. The server may record a SanctionOfficer id (as a
# show's approved_by_user_id or a protest's reviewed_by_user_id) but never
# compares it to any entity's id.
SANCTION_OFFICER_ID = "so-alpha"
SANCTION_OFFICER_BETA_ID = "so-beta"
SHOW_SECRETARY_ID = "ss-alpha"
REGISTRY_OFFICER_ID = "ro-alpha"
REGISTRY_OFFICER_BETA_ID = "ro-beta"

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — the shared constant is the canonical form.
    "sanction_officer_headers": build_user_headers(SANCTION_OFFICER_ID, "SanctionOfficer"),
    "sanction_officer_beta_headers": build_user_headers(
        SANCTION_OFFICER_BETA_ID, "SanctionOfficer"
    ),
    "show_secretary_headers": build_user_headers(SHOW_SECRETARY_ID, "ShowSecretary"),
    "registry_officer_headers": build_user_headers(REGISTRY_OFFICER_ID, "RegistryOfficer"),
    "registry_officer_beta_headers": build_user_headers(
        REGISTRY_OFFICER_BETA_ID, "RegistryOfficer"
    ),
    # Entity-backed roles — fallback constants for tests that never reach an
    # ownership check (role gating, malformed payloads, unknown path ids).
    "club_officer_headers": build_user_headers("test-club-officer-1", "ClubOfficer"),
    "judge_headers": build_user_headers("test-judge-1", "Judge"),
    "handler_headers": build_user_headers("test-handler-1", "Handler"),
}


def make_club_officer_headers(club_id: str) -> Dict[str, str]:
    """Headers for ClubOfficer. Pass the acting Club's own `id`."""
    return build_user_headers(club_id, "ClubOfficer")


def make_judge_headers(judge_id: str) -> Dict[str, str]:
    """Headers for Judge. Pass the acting Judge's own `id`."""
    return build_user_headers(judge_id, "Judge")


def make_handler_headers(handler_id: str) -> Dict[str, str]:
    """Headers for Handler. Pass the acting Handler's own `id`."""
    return build_user_headers(handler_id, "Handler")


def make_sanction_officer_headers(user_id: str = SANCTION_OFFICER_ID) -> Dict[str, str]:
    """Headers for SanctionOfficer with an explicit opaque staff identifier."""
    return build_user_headers(user_id, "SanctionOfficer")


def make_show_secretary_headers(user_id: str = SHOW_SECRETARY_ID) -> Dict[str, str]:
    """Headers for ShowSecretary with an explicit opaque operator identifier."""
    return build_user_headers(user_id, "ShowSecretary")


def make_registry_officer_headers(user_id: str = REGISTRY_OFFICER_ID) -> Dict[str, str]:
    """Headers for RegistryOfficer with an explicit opaque staff identifier."""
    return build_user_headers(user_id, "RegistryOfficer")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for any role, used by role-matrix tests."""
    return build_user_headers(user_id, role)


def headers_with_blank_user_id(role: str = "SanctionOfficer") -> Dict[str, str]:
    """Headers whose `X-User-ID` is present but empty (PRD 2.1)."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_blank_role(user_id: str = SANCTION_OFFICER_ID) -> Dict[str, str]:
    """Headers whose `X-User-Role` is present but empty (PRD 2.1)."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_without_user_id(role: str = "SanctionOfficer") -> Dict[str, str]:
    """Headers with the `X-User-ID` header absent altogether (PRD 2.1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = SANCTION_OFFICER_ID) -> Dict[str, str]:
    """Headers with the `X-User-Role` header absent altogether (PRD 2.1)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
