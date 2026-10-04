"""Pre-built role headers for every role in the PRD.

Entity-backed roles (PracticeExecutive, MarketCommitteeChair,
PhysicianBoardMember) must be built per-instance via the make_*_headers
builders with the actual entity id; the shared constants for those roles
are fallbacks for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import USER_IDS

TEST_USERS = {
    "group_admin_headers": build_user_headers(USER_IDS["GROUP_ADMIN"], "GroupAdministrator"),
    "payer_officer_headers": build_user_headers(USER_IDS["PAYER_CONTRACTING_OFFICER"], "PayerContractingOfficer"),
    "credentialing_coordinator_headers": build_user_headers(USER_IDS["CREDENTIALING_COORDINATOR"], "CredentialingCoordinator"),
    # entity_backed: fallback only for tests that do not exercise ownership.
    "practice_executive_headers": build_user_headers("test-practice-exec-1", "PracticeExecutive"),
    "distribution_accountant_headers": build_user_headers(USER_IDS["DISTRIBUTION_ACCOUNTANT"], "DistributionAccountant"),
    "group_financial_controller_headers": build_user_headers(USER_IDS["GROUP_FINANCIAL_CONTROLLER"], "GroupFinancialController"),
    # entity_backed: fallback only for non-ownership paths.
    "market_committee_chair_headers": build_user_headers("test-chair-1", "MarketCommitteeChair"),
    # entity_backed: fallback only for non-ownership paths.
    "physician_board_member_headers": build_user_headers("test-board-member-1", "PhysicianBoardMember"),
    "compliance_officer_headers": build_user_headers(USER_IDS["COMPLIANCE_OFFICER"], "ComplianceOfficer"),
}


def make_practice_executive_headers(practice_id: str) -> dict:
    """PracticeExecutive is entity_backed by Practice: X-User-ID must equal
    the acting practice's id for any ownership-gated call."""
    return build_user_headers(practice_id, "PracticeExecutive")


def make_market_committee_chair_headers(provider_id: str) -> dict:
    """MarketCommitteeChair is entity_backed by Provider: pass the acting
    provider's id."""
    return build_user_headers(provider_id, "MarketCommitteeChair")


def make_physician_board_member_headers(provider_id: str) -> dict:
    """PhysicianBoardMember is entity_backed by Provider: X-User-ID must be
    the casting provider's id."""
    return build_user_headers(provider_id, "PhysicianBoardMember")
