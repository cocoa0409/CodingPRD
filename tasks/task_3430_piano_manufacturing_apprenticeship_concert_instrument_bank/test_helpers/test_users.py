"""Pre-built role headers for the five roles in PRD section 2.1.

Three roles are entity-backed: MasterCraftsman (Craftsman.id), Apprentice
(Apprentice.id), Artist (Artist.id). For those, the shared constants below are
fallbacks ONLY for tests that never need the id to resolve or own anything;
any ownership-gated or identity-resolving call MUST use the per-instance
builder with the real entity's id. The two opaque roles (WorkshopManager,
ArtistLiaison) are canonical as shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: canonical form.
    "workshop_manager_headers": build_user_headers("test-workshop-manager-1", "WorkshopManager"),
    "artist_liaison_headers": build_user_headers("test-artist-liaison-1", "ArtistLiaison"),
    # Entity-backed roles: fallback only for tests indifferent to identity.
    "master_craftsman_headers": build_user_headers("test-master-craftsman-1", "MasterCraftsman"),
    "apprentice_headers": build_user_headers("test-apprentice-1", "Apprentice"),
    "artist_headers": build_user_headers("test-artist-1", "Artist"),
}


def make_master_craftsman_headers(craftsman_id: str) -> dict:
    """MasterCraftsman is entity_backed by Craftsman; pass the real id."""
    return build_user_headers(craftsman_id, "MasterCraftsman")


def make_apprentice_headers(apprentice_id: str) -> dict:
    """Apprentice is entity_backed by Apprentice; pass the real id."""
    return build_user_headers(apprentice_id, "Apprentice")


def make_artist_headers(artist_id: str) -> dict:
    """Artist is entity_backed by Artist; pass the real id (loan create binds it)."""
    return build_user_headers(artist_id, "Artist")
