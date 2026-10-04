"""Pre-built role headers for every role in the PRD (§2.1).

GranteeStaff is entity-backed by GranteeOrganization and Member is entity-backed
by Member: for ownership-gated calls the header's X-User-ID must equal the
actual entity id, so use the per-instance builders for those two roles.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "anonymous_headers": build_user_headers("anon-public-1", "Anonymous"),
    "officer_headers": build_user_headers("cncs-officer-1", "CNCSProgramOfficer"),
    "compliance_officer_headers": build_user_headers("co-one", "ComplianceOfficer"),
    "trust_admin_headers": build_user_headers("trust-admin-1", "TrustAdministrator"),
    # Entity-backed roles — fallback ONLY for calls that are not ownership-gated
    # (e.g. negative tests where the ownership mismatch is itself the trigger).
    "grantee_staff_headers": build_user_headers("test-org-fallback", "GranteeStaff"),
    "member_headers": build_user_headers("test-member-fallback", "Member"),
}


def make_grantee_staff_headers(org_id: str) -> dict:
    """GranteeStaff is entity-backed by GranteeOrganization: X-User-ID must be
    the acting organization's id for any org-scoped (ownership-gated) call."""
    return build_user_headers(org_id, "GranteeStaff")


def make_member_headers(member_id: str) -> dict:
    """Member is entity-backed by Member: X-User-ID must be the member's id for
    member-scoped calls (grievances, education award uses, member self-reads)."""
    return build_user_headers(member_id, "Member")


def make_compliance_officer_headers(officer_id: str) -> dict:
    """ComplianceOfficer is opaque, but segregation-of-duties compares the
    deciding officer's X-User-ID against the visit's created_by_officer_id,
    so distinct officers need distinct ids (e.g. 'co-one', 'co-two')."""
    return build_user_headers(officer_id, "ComplianceOfficer")
