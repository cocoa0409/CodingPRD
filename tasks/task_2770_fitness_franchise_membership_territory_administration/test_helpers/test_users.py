"""Pre-built role headers for every role in the PRD.

Three roles are entity-backed: FranchiseOwner's X-User-ID is a Franchisee id,
ClubManager's is a Club id and Member's is a Member id. Those roles MUST use the
per-instance builders below whenever the call is ownership-gated. The remaining
three roles (BrandAdministrator, ComplianceAuditor, BillingPartner) are opaque,
so their shared constants are the canonical form.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles, fallback for entity-backed
# roles only in tests that do not exercise ownership.
TEST_USERS = {
    "brand_administrator_headers": build_user_headers(
        "brand-reviewer-1", "BrandAdministrator"
    ),
    "brand_administrator_alt_headers": build_user_headers(
        "brand-reviewer-2", "BrandAdministrator"
    ),
    "compliance_auditor_headers": build_user_headers("auditor-1", "ComplianceAuditor"),
    "compliance_auditor_alt_headers": build_user_headers("auditor-2", "ComplianceAuditor"),
    "billing_partner_headers": build_user_headers("billing-partner-1", "BillingPartner"),
    "franchise_owner_headers": build_user_headers("test-franchise-owner-1", "FranchiseOwner"),
    "club_manager_headers": build_user_headers("test-club-manager-1", "ClubManager"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_brand_administrator_headers(user_id: str = "brand-reviewer-1") -> dict:
    """For BrandAdministrator (opaque identity)."""
    return build_user_headers(user_id, "BrandAdministrator")


def make_compliance_auditor_headers(user_id: str = "auditor-1") -> dict:
    """For ComplianceAuditor (opaque identity). Distinct ids are required whenever a
    segregation-of-duties rule compares the acting auditor with a stamped one."""
    return build_user_headers(user_id, "ComplianceAuditor")


def make_billing_partner_headers(user_id: str = "billing-partner-1") -> dict:
    """For BillingPartner (opaque identity)."""
    return build_user_headers(user_id, "BillingPartner")


def make_franchise_owner_headers(franchisee_id: str) -> dict:
    """For FranchiseOwner. Pass the owning Franchisee's id as X-User-ID."""
    return build_user_headers(franchisee_id, "FranchiseOwner")


def make_club_manager_headers(club_id: str) -> dict:
    """For ClubManager. Pass the managed Club's id as X-User-ID."""
    return build_user_headers(club_id, "ClubManager")


def make_member_headers(member_id: str) -> dict:
    """For Member. Pass the Member's own id as X-User-ID."""
    return build_user_headers(member_id, "Member")


ALL_ROLE_NAMES = [
    "BrandAdministrator",
    "FranchiseOwner",
    "ClubManager",
    "ComplianceAuditor",
    "BillingPartner",
    "Member",
]
