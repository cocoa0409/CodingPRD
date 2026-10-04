"""Pre-built role headers for the five PRD roles (PRD 2.1).

Identity kinds:
- Opaque roles (PlannerAdmin, ServiceAgent, AppUser): X-User-ID is an opaque
  operator identifier never compared to any entity id; the shared constants are
  the canonical form.
- Entity-backed roles (ChannelRep -> ChannelAccount, Assembler -> Assembler):
  X-User-ID IS the entity id and drives every ownership check. Use the
  per-instance builders make_channel_rep_headers(channel_id) /
  make_assembler_headers(assembler_id) whenever the call is ownership-gated;
  the shared constants are only for tests that do not exercise ownership
  (malformed-body, 404, role-denied probes).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared headers.
    "planner_admin_headers": build_user_headers("test-planner-admin-1", "PlannerAdmin"),
    "service_agent_headers": build_user_headers("test-service-agent-1", "ServiceAgent"),
    "app_user_headers": build_user_headers("test-app-user-1", "AppUser"),
    # Entity-backed roles — fallback for NON-ownership probes only.
    "channel_rep_headers": build_user_headers("test-channel-rep-1", "ChannelRep"),
    "assembler_headers": build_user_headers("test-assembler-1", "Assembler"),
}


def make_channel_rep_headers(channel_account_id: str) -> dict:
    """ChannelRep headers whose X-User-ID is the acting ChannelAccount's id.

    Mandatory for ownership-gated calls: allocation respond/view, sale create
    and transitions (PRD 2.1)."""
    return build_user_headers(channel_account_id, "ChannelRep")


def make_assembler_headers(assembler_id: str) -> dict:
    """Assembler headers whose X-User-ID is the acting Assembler's id.

    Mandatory for ownership-gated calls: job START/COMPLETE and reading the
    assembler's own record (PRD 2.1)."""
    return build_user_headers(assembler_id, "Assembler")
