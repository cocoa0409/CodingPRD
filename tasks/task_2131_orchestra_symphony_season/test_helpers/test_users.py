"""Pre-built role headers for every role in the PRD.

Four roles carry an opaque identity (ArtisticAdmin, OrchestraManager,
BoxOfficeAgent, AdvertisingSales): their X-User-ID is never compared to any
entity's id, so a shared constant is the canonical form.

The remaining three roles (Patron, Musician, GuestArtist) carry an entity-backed
identity: X-User-ID must equal the acting Patron's id, the acting Musician's id,
or the acting GuestArtistContract's own id. Ownership-gated calls MUST use the
per-instance builders below with the real entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for the four opaque roles, and usable by
# entity-backed roles only in tests that never reach an ownership check.
TEST_USERS = {
    "artistic_admin_headers": build_user_headers("op-artistic-admin-1", "ArtisticAdmin"),
    "orchestra_manager_headers": build_user_headers(
        "op-orchestra-manager-1", "OrchestraManager"
    ),
    "box_office_headers": build_user_headers("op-box-office-1", "BoxOfficeAgent"),
    "advertising_sales_headers": build_user_headers(
        "op-advertising-sales-1", "AdvertisingSales"
    ),
    "patron_headers": build_user_headers("unbound-patron-1", "Patron"),
    "musician_headers": build_user_headers("unbound-musician-1", "Musician"),
    "guest_artist_headers": build_user_headers("unbound-guest-artist-1", "GuestArtist"),
}

ARTISTIC_ADMIN = TEST_USERS["artistic_admin_headers"]
ORCHESTRA_MANAGER = TEST_USERS["orchestra_manager_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
ADVERTISING_SALES = TEST_USERS["advertising_sales_headers"]


def make_patron_headers(patron_id: str) -> dict:
    """Patron acts for itself: X-User-ID is the id of the acting Patron record."""
    return build_user_headers(patron_id, "Patron")


def make_musician_headers(musician_id: str) -> dict:
    """Musician acts for itself: X-User-ID is the id of the acting Musician record."""
    return build_user_headers(musician_id, "Musician")


def make_guest_artist_headers(contract_id: str) -> dict:
    """GuestArtist identity IS the contract row: X-User-ID is the contract's own id."""
    return build_user_headers(contract_id, "GuestArtist")


def make_headers(role: str, user_id: str = "op-generic-1") -> dict:
    """Arbitrary role/id pair — used by role-denial tests."""
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
