"""Pre-built role headers for every role in the PRD.

Opaque roles (PlatformAdmin, MemberServicesAgent, GovernanceOfficer,
OversightAnalyst, FinanceController, StandardsReviewer, AdvocacyDirector) have
shared constants — the PRD never compares their X-User-ID to an entity id.

Entity-backed roles (Member, ProviderManager, ChapterCoordinator) MUST be
built per-instance with the actual entity id via the make_*_headers builders;
the shared constants below exist only for calls that are not ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers
from .constants import GOV_USER_ID, FIN_USER_ID

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "member_services_headers": build_user_headers("msa-1", "MemberServicesAgent"),
    # entity_backed:Member — fallback for non-ownership calls only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    # entity_backed:Provider — fallback for non-ownership calls only.
    "provider_manager_headers": build_user_headers("test-provider-1", "ProviderManager"),
    "governance_officer_headers": build_user_headers(GOV_USER_ID, "GovernanceOfficer"),
    "oversight_analyst_headers": build_user_headers("ova-1", "OversightAnalyst"),
    "finance_controller_headers": build_user_headers(FIN_USER_ID, "FinanceController"),
    "standards_reviewer_headers": build_user_headers("std-1", "StandardsReviewer"),
    # entity_backed:Chapter — fallback for non-ownership calls only.
    "chapter_coordinator_headers": build_user_headers("test-chapter-1", "ChapterCoordinator"),
    "advocacy_director_headers": build_user_headers("adv-1", "AdvocacyDirector"),
}


def make_member_headers(member_id: str) -> dict:
    """Member is entity-backed:Member — pass the actual Member.id whenever the
    call is ownership-gated (complaint filing, enrollment)."""
    return build_user_headers(member_id, "Member")


def make_provider_manager_headers(provider_id: str) -> dict:
    """ProviderManager is entity-backed:Provider — pass the actual Provider.id
    whenever the call is ownership-gated (agreement drafting, statement submission)."""
    return build_user_headers(provider_id, "ProviderManager")


def make_chapter_coordinator_headers(chapter_id: str) -> dict:
    """ChapterCoordinator is entity-backed:Chapter — pass the actual Chapter.id
    whenever the call is ownership-gated (course-session creation)."""
    return build_user_headers(chapter_id, "ChapterCoordinator")


def make_governance_officer_headers(user_id: str = GOV_USER_ID) -> dict:
    return build_user_headers(user_id, "GovernanceOfficer")


def make_finance_controller_headers(user_id: str = FIN_USER_ID) -> dict:
    return build_user_headers(user_id, "FinanceController")


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_member_services_headers(user_id: str = "msa-1") -> dict:
    return build_user_headers(user_id, "MemberServicesAgent")


def make_oversight_analyst_headers(user_id: str = "ova-1") -> dict:
    return build_user_headers(user_id, "OversightAnalyst")


def make_standards_reviewer_headers(user_id: str = "std-1") -> dict:
    return build_user_headers(user_id, "StandardsReviewer")


def make_advocacy_director_headers(user_id: str = "adv-1") -> dict:
    return build_user_headers(user_id, "AdvocacyDirector")
