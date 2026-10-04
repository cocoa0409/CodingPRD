"""Pre-built role headers for every role in the requirements.

``NetworkAcquirer``, ``NetworkSettlementOps``, ``NetworkCompliance``,
``NetworkDataSteward``, ``NetworkDisputeOps``, ``NetworkService`` and
``NetworkIssuer`` have opaque identities, so one shared header constant each
is the canonical form. ``Merchant`` and ``CardMember`` are entity-backed:
their ``X-User-ID`` must be a real entity ``id``, so per-instance builders are
mandatory for every ownership-gated call.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator identities — the server never compares these to a row id.
    "network_acquirer_headers": build_user_headers("test-acquirer-1", "NetworkAcquirer"),
    "network_settlement_ops_headers": build_user_headers("test-settlement-1", "NetworkSettlementOps"),
    "network_compliance_headers": build_user_headers("test-compliance-1", "NetworkCompliance"),
    "network_data_steward_headers": build_user_headers("test-steward-1", "NetworkDataSteward"),
    "network_dispute_ops_headers": build_user_headers("test-disputeops-1", "NetworkDisputeOps"),
    "network_service_headers": build_user_headers("test-service-1", "NetworkService"),
    "network_issuer_headers": build_user_headers("test-issuer-1", "NetworkIssuer"),

    # Entity-backed roles: shared constants are fallbacks for calls whose
    # success does not depend on ownership (e.g. an unrelated 400/404 probe).
    "merchant_headers": build_user_headers("test-merchant-placeholder", "Merchant"),
    "cardmember_headers": build_user_headers("test-cardmember-placeholder", "CardMember"),
}


# ─── Per-instance builders (mandatory for entity-backed roles) ───

def make_merchant_headers(merchant_id: str) -> dict:
    """Headers for the ``Merchant`` role acting as the merchant with this id.

    Pass the actual merchant's ``id`` for every ownership-gated call
    (offer consent, dispute response, merchant-scoped reads).
    """
    return build_user_headers(merchant_id, "Merchant")


def make_cardmember_headers(cardmember_id: str) -> dict:
    """Headers for the ``CardMember`` role acting as the member with this id.

    Pass the actual card member's ``id`` for every ownership-gated call
    (offer acceptance, dispute opening/withdrawal, complaint filing).
    """
    return build_user_headers(cardmember_id, "CardMember")