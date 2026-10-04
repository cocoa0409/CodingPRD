"""Pre-built role headers for every role in the PRD (§2.1).

EntityComplianceOfficer and CIPAssetManager are entity-backed roles: their
X-User-ID must be the acting RegisteredEntity's id. Use make_officer_headers /
make_cip_manager_headers with the real entity id whenever the call is
ownership-gated; the shared constants are only for non-ownership tests
(400/404 checks, or opaque-role calls).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "registration_coordinator_headers": build_user_headers("test-rc-1", "RegistrationCoordinator"),
    "auditor_headers": build_user_headers("test-auditor-1", "ComplianceAuditor"),
    "regional_reviewer_headers": build_user_headers("test-rer-1", "RegionalEntityReviewer"),
    "federal_reviewer_headers": build_user_headers("test-fed-1", "FederalReviewer"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "officer_headers": build_user_headers("test-officer-1", "EntityComplianceOfficer"),
    "cip_manager_headers": build_user_headers("test-cip-1", "CIPAssetManager"),
}


def make_officer_headers(entity_id: str) -> dict:
    """EntityComplianceOfficer headers bound to a real RegisteredEntity id."""
    return build_user_headers(entity_id, "EntityComplianceOfficer")


def make_cip_manager_headers(entity_id: str) -> dict:
    """CIPAssetManager headers bound to a real RegisteredEntity id."""
    return build_user_headers(entity_id, "CIPAssetManager")


def make_auditor_headers(user_id: str = "test-auditor-1") -> dict:
    return build_user_headers(user_id, "ComplianceAuditor")
