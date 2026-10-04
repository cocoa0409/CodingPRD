"""Caller identities for the five declared roles.

Every request carries ``X-User-ID`` and ``X-User-Role`` (PRD §2.1). Four roles
are opaque: the identifier is never matched against a stored row, so a stable
constant identifier is enough. ``RetailerOps`` is entity-backed on
``Retailer``: the identifier must equal the acting retailer's ``id``, so
ownership-gated calls (line-review scheduling, sale recording) MUST use
``make_retailer_ops_headers(retailer_id)`` with the real retailer id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin": build_user_headers("11111111-1111-4111-8111-111111111111", "PlatformAdmin"),
    "brand_manager": build_user_headers("22222222-2222-4222-8222-222222222222", "BrandManager"),
    "studio_rep": build_user_headers("33333333-3333-4333-8333-333333333333", "StudioRep"),
    "safety_engineer": build_user_headers("55555555-5555-4555-8555-555555555555", "SafetyEngineer"),
    # Fallback for non-ownership calls only; ownership-gated calls must use
    # make_retailer_ops_headers with the real Retailer id.
    "retailer_ops": build_user_headers("44444444-4444-4444-8444-444444444444", "RetailerOps"),
}


def make_retailer_ops_headers(retailer_id: str) -> dict:
    """Headers for the entity-backed RetailerOps role.

    ``retailer_id`` must be the actual ``Retailer.id`` whenever the call is
    ownership-gated (scheduling a review for that retailer, recording a sale
    on a shipment whose host review belongs to that retailer).
    """
    return build_user_headers(retailer_id, "RetailerOps")
