"""Pre-built role headers for every role in the PRD (§2.1).

All eight roles are opaque: ``X-User-ID`` is not tied to any persisted entity,
so the shared constants are the canonical form. Segregation-of-duties checks
compare two ``X-User-ID`` values for equality only, so the per-user builders
exist to give a test distinct or matching engineer/inspector identities.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "site_manager_headers": build_user_headers("test-site-manager-1", "SiteManager"),
    "permit_coordinator_headers": build_user_headers("test-permit-coordinator-1", "PermitCoordinator"),
    "jurisdiction_reviewer_headers": build_user_headers("test-jurisdiction-reviewer-1", "JurisdictionReviewer"),
    "engineer_headers": build_user_headers("test-engineer-1", "Engineer"),
    "print_operator_headers": build_user_headers("test-print-operator-1", "PrintOperator"),
    "quality_inspector_headers": build_user_headers("test-quality-inspector-1", "QualityInspector"),
    "trade_contractor_headers": build_user_headers("test-trade-contractor-1", "TradeContractor"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_site_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SiteManager")


def make_permit_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PermitCoordinator")


def make_jurisdiction_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "JurisdictionReviewer")


def make_engineer_headers(user_id: str) -> dict:
    """Engineer with a specific X-User-ID — needed to control the
    submitter/decider pair for segregation-of-duties tests (PRD §3.3)."""
    return build_user_headers(user_id, "Engineer")


def make_print_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PrintOperator")


def make_quality_inspector_headers(user_id: str) -> dict:
    """QualityInspector with a specific X-User-ID — needed to control the
    recorder/dispositioner pair for segregation-of-duties tests (PRD §3.8)."""
    return build_user_headers(user_id, "QualityInspector")


def make_trade_contractor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TradeContractor")
