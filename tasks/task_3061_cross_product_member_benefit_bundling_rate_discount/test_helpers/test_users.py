"""Pre-built role headers for every role declared in the PRD §2.1."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the opaque operational roles, and for any call whose
# success does not depend on the caller owning the subject resource.
TEST_USERS = {
    "member_headers": build_user_headers("test-member-1", "Member"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "benefits_admin_headers": build_user_headers("test-benefits-admin-1", "BenefitsAdmin"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
}

# Extra operator identities used by segregation-of-duties scenarios.
ALTERNATE = {
    "benefits_admin_2": build_user_headers("test-benefits-admin-2", "BenefitsAdmin"),
    "compliance_officer_2": build_user_headers("test-compliance-officer-2", "ComplianceOfficer"),
    "compliance_officer_3": build_user_headers("test-compliance-officer-3", "ComplianceOfficer"),
    "platform_admin_2": build_user_headers("test-platform-admin-2", "PlatformAdmin"),
}

OPAQUE_OPERATOR_IDS = {
    "benefits_admin": "test-benefits-admin-1",
    "compliance_officer": "test-compliance-officer-1",
    "compliance_officer_2": "test-compliance-officer-2",
    "compliance_officer_3": "test-compliance-officer-3",
    "platform_admin": "test-platform-admin-1",
    "underwriter": "test-underwriter-1",
    "anonymous": "test-anonymous-1",
}


# --- Per-instance builders ------------------------------------------------
# `Member` is the only entity-backed role: its X-User-ID must be the id of the
# acting member entity, so every ownership-guarded call needs the real id.

def make_member_headers(user_id: str) -> dict:
    """Member (entity_backed:Member). Pass the acting Member.id as user_id."""
    return build_user_headers(user_id, "Member")


def make_underwriter_headers(user_id: str = "test-underwriter-1") -> dict:
    return build_user_headers(user_id, "Underwriter")


def make_benefits_admin_headers(user_id: str = "test-benefits-admin-1") -> dict:
    return build_user_headers(user_id, "BenefitsAdmin")


def make_compliance_officer_headers(user_id: str = "test-compliance-officer-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_anonymous_headers(user_id: str = "test-anonymous-1") -> dict:
    return build_user_headers(user_id, "Anonymous")


def headers_without_auth() -> dict:
    """No identity headers at all — a request missing both auth headers."""
    return {"Content-Type": "application/json"}


__all__ = [
    "TEST_USERS", "ALTERNATE", "OPAQUE_OPERATOR_IDS",
    "make_member_headers", "make_underwriter_headers", "make_benefits_admin_headers",
    "make_compliance_officer_headers", "make_platform_admin_headers",
    "make_anonymous_headers", "headers_without_auth",
]