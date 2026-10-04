"""Pre-built role headers for every role the platform recognises.

Six roles are opaque operator principals; `ScoreConsumer` is the single
entity-backed role, whose X-User-ID is the id of the License covering the
write.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the six opaque roles and, for ScoreConsumer,
# usable only where the call is not ownership-gated.
TEST_USERS = {
    "bureau_admin_headers": build_user_headers("test-bureau-admin-1", "BureauAdministrator"),
    "model_developer_headers": build_user_headers("test-model-developer-1", "ModelDeveloper"),
    "validation_analyst_headers": build_user_headers("test-validation-analyst-1", "ValidationAnalyst"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "fair_lending_officer_headers": build_user_headers("test-fair-lending-officer-1", "FairLendingOfficer"),
    "reason_code_admin_headers": build_user_headers("test-reason-code-admin-1", "ReasonCodeAdministrator"),
    # entity_backed:License — the shared constant never equals a real licence id,
    # so ownership-gated ScoreConsumer calls MUST use make_score_consumer_headers.
    "score_consumer_headers": build_user_headers("test-score-consumer-1", "ScoreConsumer"),
    # Not a declared role — for the unauthenticated contract.
    "unknown_role_headers": build_user_headers("test-unknown-1", "UnknownRole"),
}

# Per-instance builders — required for the entity_backed role.
def make_score_consumer_headers(license_id: str) -> dict:
    """For ScoreConsumer (entity_backed:License). Pass the actual License.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(license_id, "ScoreConsumer")