"""Pre-built role headers for the six board roles.

`Dealer` and `Manufacturer` are entity-backed: their `X-User-ID` is the `id`
of the acting `Dealer` / `Manufacturer` row, so ownership-gated calls MUST use
the per-instance builders below with the real row identifier. The shared
constants are only safe for reads and for calls that never touch ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Entity-backed roles: shared constants are a fallback for calls that do
    # not exercise ownership (for example a 404 or a malformed-body probe).
    "dealer_headers": build_user_headers("11111111-1111-4111-8111-111111111111", "Dealer"),
    "manufacturer_headers": build_user_headers("22222222-2222-4222-8222-222222222222", "Manufacturer"),
    # Opaque roles: the shared constant is the canonical form.
    "licensing_analyst_headers": build_user_headers("analyst-op-1", "LicensingAnalyst"),
    "hearing_clerk_headers": build_user_headers("clerk-op-1", "HearingClerk"),
    "complaint_investigator_headers": build_user_headers("investigator-op-1", "ComplaintInvestigator"),
    "board_admin_headers": build_user_headers("admin-op-1", "BoardAdmin"),
}

BOARD_ADMIN = TEST_USERS["board_admin_headers"]
LICENSING_ANALYST = TEST_USERS["licensing_analyst_headers"]
HEARING_CLERK = TEST_USERS["hearing_clerk_headers"]
COMPLAINT_INVESTIGATOR = TEST_USERS["complaint_investigator_headers"]


def make_dealer_headers(user_id: str) -> dict:
    """Headers for the `Dealer` role. Pass the acting dealership's own `id`."""
    return build_user_headers(user_id, "Dealer")


def make_manufacturer_headers(user_id: str) -> dict:
    """Headers for the `Manufacturer` role. Pass the acting franchisor's own `id`."""
    return build_user_headers(user_id, "Manufacturer")


def make_licensing_analyst_headers(user_id: str = "analyst-op-1") -> dict:
    """Headers for the `LicensingAnalyst` role (opaque operator identifier)."""
    return build_user_headers(user_id, "LicensingAnalyst")


def make_hearing_clerk_headers(user_id: str = "clerk-op-1") -> dict:
    """Headers for the `HearingClerk` role (opaque operator identifier)."""
    return build_user_headers(user_id, "HearingClerk")


def make_investigator_headers(user_id: str = "investigator-op-1") -> dict:
    """Headers for the `ComplaintInvestigator` role. The identifier is persisted
    as `investigator_user_id` when an investigation is opened."""
    return build_user_headers(user_id, "ComplaintInvestigator")


def make_board_admin_headers(user_id: str = "admin-op-1") -> dict:
    """Headers for the `BoardAdmin` role (opaque operator identifier)."""
    return build_user_headers(user_id, "BoardAdmin")
