"""Pre-built role headers for every role the API recognises.

`Seller` is the only role whose identity is backed by a persisted row: its
X-User-ID is the id of an existing Seller, so any call that is ownership-gated
must use `make_seller_headers(seller_id)` with that row's id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "compliance_reviewer_headers": build_user_headers("test-compliance-reviewer-1", "ComplianceReviewer"),
    "claim_adjudicator_headers": build_user_headers("test-claim-adjudicator-1", "ClaimAdjudicator"),
    "trade_in_inspector_headers": build_user_headers("test-trade-in-inspector-1", "TradeInInspector"),
    "consumer_headers": build_user_headers("test-consumer-1", "Consumer"),
    "system_headers": build_user_headers("test-system-1", "System"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "seller_headers": build_user_headers("test-seller-unbound", "Seller"),
}

# Distinct operator identifiers used where a duty-separation comparison is made.
AUDITOR_OPERATOR_ID = "op_auditor"
REVIEWER_OPERATOR_ID = "op_reviewer"
EVIDENCE_OPERATOR_ID = "op_evidence_recorder"
ADJUDICATOR_OPERATOR_ID = "op_adjudicator"
VERIFIER_OPERATOR_ID = "op_verifier"

# Headers for callers whose X-User-ID is an operator identifier, not an entity id.
OPERATOR_HEADERS = {
    "auditor": build_user_headers(AUDITOR_OPERATOR_ID, "ComplianceReviewer"),
    "reviewer": build_user_headers(REVIEWER_OPERATOR_ID, "ComplianceReviewer"),
    "evidence_recorder": build_user_headers(EVIDENCE_OPERATOR_ID, "ClaimAdjudicator"),
    "adjudicator": build_user_headers(ADJUDICATOR_OPERATOR_ID, "ClaimAdjudicator"),
    "verifier": build_user_headers(VERIFIER_OPERATOR_ID, "ComplianceReviewer"),
}


def make_seller_headers(seller_id: str) -> dict:
    """Headers for the `Seller` role acting as the seller whose id is `seller_id`.

    A Seller's X-User-ID is matched against the Seller row's `id`, so ownership
    checks on a listing compare the listing's `seller_id` to this value.
    """
    return build_user_headers(seller_id, "Seller")