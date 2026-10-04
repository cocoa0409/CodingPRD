"""Pre-built role headers for every role in the PRD.

OwnerRep and ESCOEngineer are entity-backed: ownership-gated calls MUST use
make_owner_rep_headers(entity["id"]) / make_esco_engineer_headers(entity["id"])
with the real entity id. The shared constants are fallbacks for tests that do
not exercise ownership (e.g. 400-on-bad-payload, 404-on-missing-resource).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "lender_officer_headers": build_user_headers("test-lender-1", "LenderOfficer"),
    # entity_backed fallbacks — non-ownership tests only
    "esco_engineer_headers": build_user_headers("test-eng-1", "ESCOEngineer"),
    "owner_rep_headers": build_user_headers("test-owner-1", "OwnerRep"),
}


def make_esco_engineer_headers(user_id: str) -> dict:
    """For ESCOEngineer (entity-backed). Pass the actual ESCOEngineer.id as
    user_id whenever the call is ownership- or identity-gated."""
    return build_user_headers(user_id, "ESCOEngineer")


def make_owner_rep_headers(user_id: str) -> dict:
    """For OwnerRep (entity-backed). Pass the actual OwnerRep.id as user_id
    whenever the call records or compares the acting owner rep."""
    return build_user_headers(user_id, "OwnerRep")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_lender_officer_headers(user_id: str = "test-lender-1") -> dict:
    return build_user_headers(user_id, "LenderOfficer")
