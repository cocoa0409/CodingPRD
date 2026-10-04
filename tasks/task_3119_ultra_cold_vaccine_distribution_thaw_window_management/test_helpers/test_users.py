"""Pre-built role headers for every role named in the PRD.

``SiteCoordinator`` is the only entity-backed role: its ``X-User-ID`` is the
``id`` of the acting ``StorageSite``. Every other role is an opaque operator
identifier.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "manufacturing_qa_headers": build_user_headers("test-manufacturing-qa-1", "ManufacturingQA"),
    "regulatory_affairs_headers": build_user_headers("test-regulatory-affairs-1", "RegulatoryAffairsOfficer"),
    "distribution_planner_headers": build_user_headers("test-distribution-planner-1", "DistributionPlanner"),
    "logistics_operator_headers": build_user_headers("test-logistics-operator-1", "LogisticsOperator"),
    "cold_chain_reviewer_headers": build_user_headers("test-cold-chain-reviewer-1", "ColdChainReviewer"),
    "medical_science_liaison_headers": build_user_headers("test-medical-science-liaison-1", "MedicalScienceLiaison"),
}

# The SiteCoordinator identity is entity-backed; opaque facsimiles are supplied
# for calls that do not exercise ownership. Ownership-gated calls MUST use
# make_site_coordinator_headers(site_id).
OPAQUE_SITE_COORDINATOR_HEADERS = build_user_headers("test-site-coordinator-1", "SiteCoordinator")

# Adjudication and review are performed by different opaque operators, because
# the segregation-of-duties rule compares two operator identifiers.
ADJUDICATOR_HEADERS = build_user_headers("test-adjudicator-1", "MedicalScienceLiaison")
REVIEWER_HEADERS = build_user_headers("test-reviewer-1", "ColdChainReviewer")
APPEALS_OFFICER_HEADERS = build_user_headers("test-appeals-officer-1", "RegulatoryAffairsOfficer")
SECOND_ADJUDICATOR_HEADERS = build_user_headers("test-adjudicator-2", "MedicalScienceLiaison")


def make_site_coordinator_headers(site_id: str) -> dict:
    """Headers for a SiteCoordinator acting for ``site_id``.

    Pass the actual StorageSite id whenever the call is ownership-gated.
    """
    return build_user_headers(site_id, "SiteCoordinator")