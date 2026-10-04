"""Pre-built role headers for every role in the PRD (PRD §2.1).

PlatformAdmin, BoardPanel and AppealsCourt are opaque identities: the server
never compares their X-User-ID to an entity id, so shared constants are the
canonical form.

Petitioner and PatentOwner are entity-backed: X-User-ID IS the acting Party's
id, and ownership checks compare resource foreign keys to it. Any call gated
on ownership MUST use make_petitioner_headers(party_id) /
make_patent_owner_headers(party_id) with the real Party id — never a shared
constant.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles (PRD §2.1): safe as shared constants.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "panel_headers": build_user_headers("test-panel-1", "BoardPanel"),
    "appeals_headers": build_user_headers("test-appeals-1", "AppealsCourt"),
    # Entity-backed roles: fallback constants for NON-ownership calls only
    # (e.g. generic GETs, or RBAC probes where no real party is needed).
    "petitioner_headers": build_user_headers("test-petitioner-1", "Petitioner"),
    "patent_owner_headers": build_user_headers("test-patent-owner-1", "PatentOwner"),
}


def make_petitioner_headers(party_id: str) -> dict:
    """Petitioner is entity-backed: X-User-ID must be the petitioner Party id."""
    return build_user_headers(party_id, "Petitioner")


def make_patent_owner_headers(party_id: str) -> dict:
    """PatentOwner is entity-backed: X-User-ID must be the owner Party id."""
    return build_user_headers(party_id, "PatentOwner")
