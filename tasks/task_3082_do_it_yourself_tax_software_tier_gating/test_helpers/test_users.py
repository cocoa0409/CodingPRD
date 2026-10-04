"""Pre-built role headers for every role in the PRD (§2.1).

ClaimsAdjuster and PlatformOperator use opaque operator ids, so shared
constants are canonical for them. Taxpayer is entity-backed by
TaxpayerAccount (X-User-ID equals the owning account's id): use
make_taxpayer_headers(account_id) for every ownership-gated call; the
shared constant is only a fallback for the bootstrap registration call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Entity-backed role — fallback for the bootstrap POST /tax/accounts only.
    "taxpayer_headers": build_user_headers("taxpayer-bootstrap", "Taxpayer"),
    # Opaque roles — shared constant is the canonical form.
    "claims_adjuster_headers": build_user_headers("claims-adjuster-1", "ClaimsAdjuster"),
    "platform_operator_headers": build_user_headers("platform-operator-1", "PlatformOperator"),
}


def make_taxpayer_headers(account_id: str) -> dict:
    """Taxpayer is entity-backed by TaxpayerAccount: X-User-ID must equal the
    owning account's id for any ownership-gated call."""
    return build_user_headers(account_id, "Taxpayer")


def make_claims_adjuster_headers(user_id: str = "claims-adjuster-1") -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_platform_operator_headers(user_id: str = "platform-operator-1") -> dict:
    return build_user_headers(user_id, "PlatformOperator")
