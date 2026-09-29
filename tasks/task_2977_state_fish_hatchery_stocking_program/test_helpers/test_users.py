"""
Pre-built authentication headers for the five roles of PRD 2.1.

Every request carries `X-User-ID` and `X-User-Role`. Four of the five roles hold
an opaque operator identifier that the server never compares to a record's `id`,
so a fixed constant is fine for each of them. `HatcheryManager` is the one
entity-backed identity — its `X-User-ID` must be the `id` of the acting
`Hatchery` — so manager headers are always built per station through
make_hatchery_manager_headers().

Several tests need two distinct principals inside the same role: two
veterinarians to exercise segregation of duties, and two requesters to exercise
request ownership. Those are provided as separate named identities.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_FISH_HEALTH_VETERINARIAN,
    ROLE_HATCHERY_MANAGER,
    ROLE_PROGRAM_ADMIN,
    ROLE_PUBLIC_REQUESTER,
    ROLE_REGIONAL_BIOLOGIST,
)

# ─── Opaque operator identifiers ──────────────────────

ADMIN_USER_ID = "admin-pat"
ADMIN_USER_ID_ALT = "admin-quinn"

VET_ANNA_USER_ID = "vet-anna"
VET_BRUNO_USER_ID = "vet-bruno"
VET_CARA_USER_ID = "vet-cara"

BIO_CARLA_USER_ID = "bio-carla"
BIO_DANA_USER_ID = "bio-dana"
BIO_FRANK_USER_ID = "bio-frank"

PUB_ERIN_USER_ID = "pub-erin"
PUB_DANA_USER_ID = "pub-dana"
PUB_EVE_USER_ID = "pub-eve"

# ─── Ready-made header dictionaries ───────────────────

ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)
ADMIN_HEADERS_ALT = build_user_headers(ADMIN_USER_ID_ALT, ROLE_PROGRAM_ADMIN)

VET_ANNA_HEADERS = build_user_headers(VET_ANNA_USER_ID, ROLE_FISH_HEALTH_VETERINARIAN)
VET_BRUNO_HEADERS = build_user_headers(VET_BRUNO_USER_ID, ROLE_FISH_HEALTH_VETERINARIAN)
VET_CARA_HEADERS = build_user_headers(VET_CARA_USER_ID, ROLE_FISH_HEALTH_VETERINARIAN)

BIO_CARLA_HEADERS = build_user_headers(BIO_CARLA_USER_ID, ROLE_REGIONAL_BIOLOGIST)
BIO_DANA_HEADERS = build_user_headers(BIO_DANA_USER_ID, ROLE_REGIONAL_BIOLOGIST)
BIO_FRANK_HEADERS = build_user_headers(BIO_FRANK_USER_ID, ROLE_REGIONAL_BIOLOGIST)

PUB_ERIN_HEADERS = build_user_headers(PUB_ERIN_USER_ID, ROLE_PUBLIC_REQUESTER)
PUB_DANA_HEADERS = build_user_headers(PUB_DANA_USER_ID, ROLE_PUBLIC_REQUESTER)
PUB_EVE_HEADERS = build_user_headers(PUB_EVE_USER_ID, ROLE_PUBLIC_REQUESTER)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin": ADMIN_HEADERS,
    "admin_alt": ADMIN_HEADERS_ALT,
    "vet_anna": VET_ANNA_HEADERS,
    "vet_bruno": VET_BRUNO_HEADERS,
    "vet_cara": VET_CARA_HEADERS,
    "bio_carla": BIO_CARLA_HEADERS,
    "bio_dana": BIO_DANA_HEADERS,
    "bio_frank": BIO_FRANK_HEADERS,
    "pub_erin": PUB_ERIN_HEADERS,
    "pub_dana": PUB_DANA_HEADERS,
    "pub_eve": PUB_EVE_HEADERS,
}


def make_hatchery_manager_headers(hatchery_id: str) -> Dict[str, str]:
    """
    Build `HatcheryManager` headers for one station.

    PRD 2.1: "When `X-User-Role` is `HatcheryManager`, `X-User-ID` is the `id` of
    the acting `Hatchery`". Passing a different station's `id` is exactly how a
    cross-station attempt is expressed.
    """
    return build_user_headers(hatchery_id, ROLE_HATCHERY_MANAGER)


def headers_missing_user_id(role: str) -> Dict[str, str]:
    """Headers carrying only `X-User-Role`, with no `X-User-ID` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_blank_user_id(role: str) -> Dict[str, str]:
    """
    Headers whose `X-User-ID` is the empty string.

    The empty string is used deliberately rather than a whitespace-only value:
    the HTTP client refuses to transmit a header value made of spaces, so an
    empty value is how a blank principal actually reaches the server.
    """
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}
