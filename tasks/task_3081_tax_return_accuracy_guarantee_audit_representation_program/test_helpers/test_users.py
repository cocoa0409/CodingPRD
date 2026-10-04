"""Pre-built role headers for every role in the PRD.

Opaque roles (ProgramAdmin, OfficeManager, CaseManager) use shared constants.
Entity-backed roles (Client, Preparer, EnrolledAgent) expose per-instance
builders that MUST be called with the actual entity's id for ownership-gated
calls (e.g. a preparer completing their own remediation).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import RESOLVER_USER_ID, SCOPER_USER_ID

# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity-backed ownership. For ownership-gated calls, use the make_* builders.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "office_manager_headers": build_user_headers("test-om-1", "OfficeManager"),
    # Default case manager; used for non-resolve calls.
    "case_manager_headers": build_user_headers("test-cm-1", "CaseManager"),
    # Scoper case manager: the identity recorded into claim.scoped_by_user_id.
    "case_manager_scoper_headers": build_user_headers(SCOPER_USER_ID, "CaseManager"),
    # Resolver case manager: a different operator, safe for POST /tax/claims/{id}/resolve.
    "case_manager_resolver_headers": build_user_headers(RESOLVER_USER_ID, "CaseManager"),
    # Fallbacks for entity-backed roles — only for non-ownership reads.
    "client_headers": build_user_headers("test-client-1", "Client"),
    "preparer_headers": build_user_headers("test-preparer-1", "Preparer"),
    "enrolled_agent_headers": build_user_headers("test-agent-1", "EnrolledAgent"),
}


def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed: Client). Pass the actual Client.id whenever the
    call is ownership-gated (e.g. POST /tax/claims/{id}/provide-info)."""
    return build_user_headers(client_id, "Client")


def make_preparer_headers(preparer_id: str) -> dict:
    """For Preparer (entity_backed: Preparer). Pass the actual Preparer.id whenever
    the call is ownership-gated (e.g. POST /tax/remediations/{id}/complete)."""
    return build_user_headers(preparer_id, "Preparer")


def make_enrolled_agent_headers(agent_id: str) -> dict:
    """For EnrolledAgent (entity_backed: EnrolledAgent). Pass the actual
    EnrolledAgent.id whenever the call is ownership-gated (e.g. POST
    /tax/notices/{id}/abate)."""
    return build_user_headers(agent_id, "EnrolledAgent")
