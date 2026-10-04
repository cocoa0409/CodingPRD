"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests whose outcome does
# not depend on the caller owning the subject resource (bad-payload 400s,
# missing-resource 404s, RBAC denials).
TEST_USERS = {
    # entity_backed:Member — fallback only; use make_member_headers(member_id)
    # whenever the call is ownership-gated.
    "member_headers": build_user_headers("test-member-1", "Member"),
    # entity_backed:Member — fallback only; use make_guardian_headers(guardian_id).
    "guardian_headers": build_user_headers("test-guardian-1", "Guardian"),
    # opaque roles: shared constant is the canonical form.
    "record_verifier_headers": build_user_headers("rv-1", "RecordVerifier"),
    # entity_backed:ResponderCredential — use make_responder_headers(credential_id).
    "responder_headers": build_user_headers("test-responder-1", "Responder"),
    "hotline_operator_headers": build_user_headers("op-1", "HotlineOperator"),
    "fulfillment_agent_headers": build_user_headers("fa-1", "FulfillmentAgent"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}


def make_member_headers(member_id: str) -> dict:
    """Member acting on their own resources (X-User-ID == memberId)."""
    return build_user_headers(member_id, "Member")


def make_guardian_headers(guardian_member_id: str) -> dict:
    """Guardian acting on a dependent's resources (X-User-ID == guardian_member_id
    of an ACTIVE GuardianLink)."""
    return build_user_headers(guardian_member_id, "Guardian")


def make_responder_headers(responder_credential_id: str) -> dict:
    """Responder authenticating with a credential (X-User-ID == the id of the
    ResponderCredential owning the presented credential_code)."""
    return build_user_headers(responder_credential_id, "Responder")
