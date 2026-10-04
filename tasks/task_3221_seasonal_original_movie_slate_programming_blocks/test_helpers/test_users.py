"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. For entity-backed roles, use the per-instance builder instead.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "slate_planner_headers": build_user_headers("test-planner-1", "SlatePlanner"),
    "production_manager_headers": build_user_headers("test-pm-1", "ProductionManager"),
    # entity_backed role: fallback for non-ownership tests only.
    "talent_agent_headers": build_user_headers("test-agent-1", "TalentAgent"),
    "programming_exec_headers": build_user_headers("test-exec-1", "ProgrammingExec"),
    "ad_sales_rep_headers": build_user_headers("test-ads-1", "AdSalesRep"),
    "streaming_curator_headers": build_user_headers("test-stream-1", "StreamingCurator"),
    "licensing_manager_headers": build_user_headers("test-lic-1", "LicensingManager"),
}


def make_talent_agent_headers(talent_id: str) -> dict:
    """For TalentAgent (entity_backed:Talent). Pass the actual Talent.id as
    talent_id whenever the call is ownership-gated (deals/castings)."""
    return build_user_headers(talent_id, "TalentAgent")
