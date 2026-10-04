"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the eight opaque roles (X-User-ID is never
# compared against any entity id for these). For ExhibitorFinanceUser the
# shared constant is a fallback for non-ownership paths only.
TEST_USERS = {
    "network_planner_headers": build_user_headers("test-np-1", "NetworkPlanner"),
    "contract_manager_headers": build_user_headers("test-pcm-1", "PlatformContractManager"),
    "studio_manager_headers": build_user_headers("test-srm-1", "StudioRelationshipManager"),
    "post_scheduler_headers": build_user_headers("test-pps-1", "PostProductionScheduler"),
    "qa_reviewer_headers": build_user_headers("test-qar-1", "QualityAssuranceReviewer"),
    "release_scheduler_headers": build_user_headers("test-rs-1", "ReleaseScheduler"),
    "box_office_analyst_headers": build_user_headers("test-boa-1", "BoxOfficeAnalyst"),
    "field_engineer_headers": build_user_headers("test-fe-1", "FieldEngineer"),
    # entity_backed role — fallback only; use make_exhibitor_finance_headers
    # with the real ExhibitorAgreement.id for ownership-gated calls.
    "exhibitor_finance_headers": build_user_headers("test-efu-1", "ExhibitorFinanceUser"),
}


def make_exhibitor_finance_headers(user_id: str) -> dict:
    """For ExhibitorFinanceUser (identity tied to ExhibitorAgreement). Pass the
    actual ExhibitorAgreement.id as user_id whenever the call is
    ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "ExhibitorFinanceUser")
