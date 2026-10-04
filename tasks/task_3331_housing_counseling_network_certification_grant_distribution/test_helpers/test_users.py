"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "network_director_headers": build_user_headers("director-1", "NetworkDirector"),
    "assessor_headers": build_user_headers("assessor-1", "Assessor"),
    "training_registrar_headers": build_user_headers("registrar-1", "TrainingRegistrar"),
    "grant_officer_headers": build_user_headers("grant-officer-1", "GrantOfficer"),
    # entity_backed:NetworkMember — fallback only for non-ownership tests.
    "member_admin_headers": build_user_headers("member-admin-1", "MemberAdmin"),
    "compliance_reviewer_headers": build_user_headers("compliance-reviewer-1", "ComplianceReviewer"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
}


def make_network_director_headers(user_id: str) -> dict:
    """NetworkDirector headers bound to a specific opaque operator id."""
    return build_user_headers(user_id, "NetworkDirector")


def make_assessor_headers(user_id: str) -> dict:
    """Assessor headers bound to a specific opaque operator id."""
    return build_user_headers(user_id, "Assessor")


def make_training_registrar_headers(user_id: str) -> dict:
    """TrainingRegistrar headers bound to a specific opaque operator id."""
    return build_user_headers(user_id, "TrainingRegistrar")


def make_grant_officer_headers(user_id: str) -> dict:
    """GrantOfficer headers bound to a specific opaque operator id."""
    return build_user_headers(user_id, "GrantOfficer")


def make_member_admin_headers(user_id: str) -> dict:
    """For MemberAdmin (entity_backed:NetworkMember). Pass the actual member id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "MemberAdmin")


def make_compliance_reviewer_headers(user_id: str) -> dict:
    """ComplianceReviewer headers bound to a specific opaque operator id."""
    return build_user_headers(user_id, "ComplianceReviewer")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor headers bound to a specific opaque operator id."""
    return build_user_headers(user_id, "Auditor")
