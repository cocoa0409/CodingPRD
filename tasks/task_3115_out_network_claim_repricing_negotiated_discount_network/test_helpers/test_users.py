"""Pre-built role headers for every role in the PRD.

Entity-backed roles (PayerAdmin, PayerRep, ProviderRep) bind X-User-ID to the
acting entity's id — use the per-instance builders below for ownership-gated
calls. The shared constants are fallbacks for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "network_admin_headers": build_user_headers("test-network-admin-1", "NetworkAdmin"),
    "feed_operator_headers": build_user_headers("test-feed-operator-1", "FeedOperator"),
    "idr_entity_headers": build_user_headers("test-idr-entity-1", "IdrEntity"),
    # Entity-backed roles — fallback only for tests that do not exercise ownership.
    "payer_admin_headers": build_user_headers("test-payer-admin-1", "PayerAdmin"),
    "payer_rep_headers": build_user_headers("test-payer-rep-1", "PayerRep"),
    "provider_rep_headers": build_user_headers("test-provider-rep-1", "ProviderRep"),
}


def make_payer_admin_headers(payer_client_id: str) -> dict:
    """PayerAdmin is entity-backed by PayerClient: pass the payer's id."""
    return build_user_headers(payer_client_id, "PayerAdmin")


def make_payer_rep_headers(payer_client_id: str) -> dict:
    """PayerRep is entity-backed by PayerClient: pass the payer's id."""
    return build_user_headers(payer_client_id, "PayerRep")


def make_provider_rep_headers(provider_id: str) -> dict:
    """ProviderRep is entity-backed by Provider: pass the provider's id."""
    return build_user_headers(provider_id, "ProviderRep")
