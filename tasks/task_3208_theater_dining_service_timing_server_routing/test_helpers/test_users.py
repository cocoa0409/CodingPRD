"""Pre-built role headers for every role the PRD recognises (PRD §2.1).

Five of the six roles are opaque: their X-User-ID is an operator identifier not
tied to any persisted row, so a shared constant is the canonical form. The
`Server` role is entity-backed: X-User-ID must be the id of the acting Server
entity, so any ownership-gated call has to be issued with
make_server_headers(server["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for calls that are not
# ownership-gated. The server entry is a fallback for non-ownership tests only.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "kitchen_lead_headers": build_user_headers("test-kitchen-lead-1", "KitchenLead"),
    "programming_coordinator_headers": build_user_headers(
        "test-programming-coordinator-1", "ProgrammingCoordinator"
    ),
    "pre_show_producer_headers": build_user_headers("test-pre-show-producer-1", "PreShowProducer"),
    # The Anonymous role holds no operation at all; any request presenting it
    # fails the role check rather than passing it.
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "server_headers": build_user_headers("test-server-1", "Server"),
}


def make_server_headers(server_id: str) -> dict:
    """For the Server role (entity-backed). Pass the actual Server.id as
    server_id whenever the call is ownership-gated."""
    return build_user_headers(server_id, "Server")


def make_headers_with_unknown_role(user_id: str = "test-unknown-1") -> dict:
    """A declared-header pair whose role is not one of the six declared roles."""
    return build_user_headers(user_id, "NightAuditor")


def headers_without_user_id() -> dict:
    """Content-Type only — the X-User-ID header is absent entirely."""
    return {"Content-Type": "application/json"}


def headers_without_role(user_id: str = "test-no-role-1") -> dict:
    """X-User-ID present but the X-User-Role header is absent."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}