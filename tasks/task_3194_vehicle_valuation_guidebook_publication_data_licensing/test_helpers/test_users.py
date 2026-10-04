"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership gating. For entity-backed roles (DealerPartner, Consumer, Licensee)
# use the per-instance builders below whenever the call is ownership-gated.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ValuationAdmin"),
    "dataops_headers": build_user_headers("test-dataops-1", "DataOps"),
    # Entity-backed roles: fallback for non-ownership tests only.
    "dealer_headers": build_user_headers("test-dealer-1", "DealerPartner"),
    "consumer_headers": build_user_headers("test-consumer-1", "Consumer"),
    "licensee_headers": build_user_headers("test-licensee-1", "Licensee"),
}


def make_dealer_headers(source_id: str) -> dict:
    """For DealerPartner (entity-backed by Source). Pass the actual Source.id
    whenever the call is ownership-gated (inspect / redeem / void / offer create)."""
    return build_user_headers(source_id, "DealerPartner")


def make_consumer_headers(consumer_profile_id: str) -> dict:
    """For Consumer (entity-backed by ConsumerProfile). Pass the actual
    ConsumerProfile.id whenever the call is ownership-gated (dispute withdraw)."""
    return build_user_headers(consumer_profile_id, "Consumer")


def make_licensee_headers(agreement_id: str) -> dict:
    """For Licensee (entity-backed by LicenseAgreement). Pass the actual
    LicenseAgreement.id whenever the call is license-gated."""
    return build_user_headers(agreement_id, "Licensee")
