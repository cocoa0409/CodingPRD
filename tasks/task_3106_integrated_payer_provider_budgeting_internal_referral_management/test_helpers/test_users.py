"""Pre-built role headers — one per role the API recognises.

Seven roles are opaque operators: ``X-User-ID`` is an operator identifier the
server never compares to any entity's ``id``. The ``Provider`` role is
entity-backed: ``X-User-ID`` must be the ``id`` of the acting Provider, so
ownership-gated calls must use ``make_provider_headers(provider_id)``.
"""

from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "regional_finance_officer_headers": build_user_headers(
        "test-rfo-1", "RegionalFinanceOfficer"
    ),
    "utilization_reviewer_headers": build_user_headers(
        "test-ur-1", "UtilizationReviewer"
    ),
    "access_scheduler_headers": build_user_headers("test-as-1", "AccessScheduler"),
    "quality_review_board_headers": build_user_headers(
        "test-qrb-1", "QualityReviewBoard"
    ),
    "budget_appropriations_committee_headers": build_user_headers(
        "test-bac-1", "BudgetAppropriationsCommittee"
    ),
    "care_team_member_headers": build_user_headers("test-ctm-1", "CareTeamMember"),
    # entity_backed: shared constant is a fallback for non-ownership tests only.
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_provider_headers(provider_id: str) -> dict:
    """For Provider (entity_backed:Provider). Pass the actual Provider.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(provider_id, "Provider")